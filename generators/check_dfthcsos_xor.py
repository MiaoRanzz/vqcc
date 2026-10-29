"""Targeted independent check of ANGLE XOR semantics, not official validation.

For each legal address, start from independent arbitrary word registers and
apply each circuit twice. Check the exact XOR output, address restoration,
clean workspace and phase on both passes. This targets changed measurement
uncomputation without repeating the unchanged chemistry residual calculation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "kickmix"), str(ROOT / "verifiers")]
import kickmix as km
import numpy as np
from dfthcsos.example_submission.angle_k_reference_circuit import batch_deltas
from dfthcsos.scoreinfra.circuits import read_circuit_family, register_layout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=8)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.report.exists() or args.report.resolve().is_relative_to(args.candidate.resolve()):
        parser.error("report must be new and outside candidate artifact directory")
    started = time.monotonic()
    circuits = read_circuit_family(args.candidate)
    layout = register_layout(circuits)
    with np.load(args.candidate / "submission.npz") as data:
        words = data["angle_words"]
    deltas = batch_deltas(words, layout.batch_size)
    addresses = np.tile(np.arange(len(words)), args.repeats)
    rng = np.random.default_rng(args.seed)

    def bits(values, width):
        return ((values[None, :] >> np.arange(width)[:, None]) & 1).astype(bool)

    address_bits = bits(addresses, len(layout.selection))
    for k, circuit in enumerate(circuits):
        target = rng.integers(0, 1 << layout.brot, (len(addresses), layout.batch_size))
        sim = km.Simulator(batch_size=len(addresses), seed=args.seed + k)
        sim.use_same_registers_as(circuit)
        sim.write_across_shots(layout.selection, address_bits)
        scratch = km.array([km.q(i) for i in range(circuit.num_qubits) if i not in layout.public_qubits])
        for j, word in enumerate(layout.words):
            sim.write_across_shots(word, bits(target[:, j], layout.brot))
        for expected in (target ^ deltas[k, addresses], target):
            sim.do(circuit)
            np.testing.assert_array_equal(sim.read_across_shots(layout.selection), address_bits)
            for j, word in enumerate(layout.words):
                np.testing.assert_array_equal(sim.read_across_shots(word), bits(expected[:, j], layout.brot))
            if sim.read_across_shots(scratch).any():
                raise AssertionError(f"dirty workspace in ANGLE_{k}")
            if any(sim.read_shot_phase(i) % 2 for i in range(len(addresses))):
                raise AssertionError(f"nonzero phase in ANGLE_{k}")
    result = {
        "status": "PASS", "kind": "independent_arbitrary_target_xor", "official_validation": False,
        "seed": args.seed, "repeats": args.repeats, "addresses": len(words),
        "circuits": len(circuits), "applications": 2 * len(circuits) * len(addresses),
        "elapsed_seconds": time.monotonic() - started, "python_executable": sys.executable,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(args.candidate.iterdir()) if p.is_file()},
    }
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
