"""Deterministic, bounded precision search; every result is screening only.

Uses the unchanged Apache-2.0 reference arithmetic and circuit builder. No
random inputs, circuit salts, or verifier seeds are selected by this search.
Run the ordinary generator and pipeline verifier on retained parameter sets.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "kickmix"), str(ROOT / "verifiers"), str(ROOT / "generators")]

import numpy as np
from generate import numeric_screen
from invsqrt.nr_reference_circuit import Precision, build_nr_circuit, relative_error
from invsqrt.verify_submission_invsqrt import N_P, ProblemSpecInvSqrt


def boundary_inputs(max_x: int) -> np.ndarray:
    """Include small x and both sides of all normalization/interval boundaries."""
    values = set(range(1, 4097))
    values.update(map(int, np.linspace(1, max_x, 8192, dtype=np.int64)))
    for shift in range(N_P + 1):
        for numerator in (2, 3, 4, 6, 8):
            boundary = numerator * 2 ** (2 * shift) // 2
            values.update(range(max(1, boundary - 4), min(max_x, boundary + 4) + 1))
    return np.array(sorted(x for x in values if x <= max_x), dtype=np.int64)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--full-limit", type=int, default=12)
    parser.add_argument("--stop-by", type=datetime.fromisoformat, required=True)
    args = parser.parse_args()
    if args.full_limit < 1:
        parser.error("full-limit must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    spec = ProblemSpecInvSqrt.for_n_p(N_P)
    xs = boundary_inputs(spec.max_x)
    started = time.monotonic()
    survivors, full = [], []
    source_files = [Path(__file__), ROOT / "generators/generate.py",
                    ROOT / "verifiers/invsqrt/nr_reference_circuit.py",
                    ROOT / "verifiers/LICENSE.txt"]
    metadata = {
        "official_validation": False, "python_executable": sys.executable,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in source_files},
        "license": "Reference builder/model: verifiers/LICENSE.txt (Apache-2.0); search independently authored",
        "sample_inputs": len(xs), "full_inputs": spec.max_x,
        "parameter_order": list(asdict(Precision())),
        "grid": [[11, 12, 13, 14], [15, 16, 17], [27, 28], [27, 28], [28, 29]],
    }
    (args.output_dir / "search.json").write_text(json.dumps(metadata, indent=2) + "\n")
    with (args.output_dir / "trials.jsonl").open("x", buffering=1) as log:
        for index, widths in enumerate(itertools.product(*metadata["grid"])):
            if datetime.now(timezone.utc) >= args.stop_by:
                break
            prec = Precision(*widths)
            record = {"trial": index, "parameters": asdict(prec), "official_validation": False}
            tick = time.monotonic()
            errors = relative_error(N_P, prec, xs)
            record.update(sample_worst_ratio=float(errors.max() * 2**24),
                          sample_worst_x=int(xs[errors.argmax()]))
            if record["sample_worst_ratio"] < 1:
                circuit = build_nr_circuit(N_P, prec=prec)
                record.update(qubits=circuit.num_qubits,
                              toffolis=int(circuit.operation_statistics().num_toffoli_like))
                record["cost_lower_bound"] = record["qubits"] * record["toffolis"]
                survivors.append(record)
            record["elapsed_seconds"] = time.monotonic() - tick
            log.write(json.dumps(record) + "\n")
            print(json.dumps(record), flush=True)
        for record in sorted(survivors, key=lambda r: (r["cost_lower_bound"], r["trial"]))[:args.full_limit]:
            # Reserve up to one minute for the all-input model; this is not a verifier.
            if (args.stop_by - datetime.now(timezone.utc)).total_seconds() < 60:
                break
            tick = time.monotonic()
            result = {**record, "full_domain": numeric_screen(Precision(**record["parameters"]))}
            result["full_elapsed_seconds"] = time.monotonic() - tick
            full.append(result)
            log.write(json.dumps(result) + "\n")
            print(json.dumps(result), flush=True)
            (args.output_dir / "full-domain.json").write_text(json.dumps(full, indent=2) + "\n")
    metadata.update(elapsed_seconds=time.monotonic() - started,
                    sample_survivors=len(survivors), full_evaluated=len(full))
    (args.output_dir / "search.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
