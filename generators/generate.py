"""Build isolated VQCC candidates; generation is not official validation.

Run with the project's resolved vqcc interpreter. The output directory must
be empty and outside the immutable historical submissions and reference files.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "kickmix"), str(ROOT / "verifiers")]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_destination(path: Path) -> Path:
    resolved = path.resolve()
    protected = [ROOT / name for name in (
        "submission", "sample_submission", "verifiers", "kickmix", "generators",
        "automation", ".agents", ".git")]
    if resolved == ROOT or any(resolved == p or p in resolved.parents for p in protected):
        raise ValueError(f"Refusing to write to protected project path: {resolved}")
    if path.is_symlink():
        raise ValueError("The destination itself must not be a symlink")
    return resolved


def check_output(path: Path) -> Path:
    resolved = check_destination(path)
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise FileExistsError(f"Output directory must be empty: {resolved}")
    return resolved


@contextmanager
def output_workspace(path: Path):
    """Reserve an empty output directory and build off to the side in that directory."""
    output = check_output(path)
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".generation.lock"
    with lock.open("x"):
        pass
    try:
        with tempfile.TemporaryDirectory(prefix=".building-", dir=output) as tmp:
            stage = Path(tmp)
            yield output, stage
            for item in stage.iterdir():
                item.rename(output / item.name)
    finally:
        lock.unlink(missing_ok=True)


def integer(params: dict, key: str, default: int, low: int, high: int) -> int:
    value = params.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{key} must be an integer in [{low}, {high}]")
    return value


def numeric_screen(prec, *, chunk_size: int = 131072) -> dict:
    """Evaluate the arithmetic model over the real competition input domain."""
    import numpy as np
    from invsqrt.nr_reference_circuit import relative_error
    from invsqrt.verify_submission_invsqrt import N_P, ProblemSpecInvSqrt

    spec = ProblemSpecInvSqrt.for_n_p(N_P)
    worst_error, worst_x = -1.0, 0
    for start in range(1, spec.max_x + 1, chunk_size):
        xs = np.arange(start, min(start + chunk_size, spec.max_x + 1), dtype=np.int64)
        errors = relative_error(N_P, prec, xs)
        if not np.isfinite(errors).all():
            raise ValueError("Non-finite arithmetic model error")
        offset = int(errors.argmax())
        if float(errors[offset]) > worst_error:
            worst_error, worst_x = float(errors[offset]), int(xs[offset])
    tolerance = 2.0 ** -spec.precision_bits
    return {
        "kind": "arithmetic_model_full_input_domain", "inputs": spec.max_x,
        "worst_relative_error": worst_error, "worst_x": worst_x,
        "tolerance": tolerance, "error_over_tolerance": worst_error / tolerance,
        "passes_model_tolerance": worst_error <= tolerance,
        "official_validation": False,
    }


def generate_invsqrt(stage: Path, params: dict, args) -> dict:
    from dataclasses import asdict
    from invsqrt.nr_reference_circuit import Precision, build_nr_circuit
    from invsqrt.verify_submission_invsqrt import N_P

    allowed = {"delta_bits", "coef_bits", "square_bits", "product_bits", "result_bits"}
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"Unknown invsqrt parameters: {sorted(unknown)}")
    defaults = asdict(Precision())
    # int64 model and circuit widths are deliberately bounded. New arithmetic
    # families can define their own proven bounds in a new generator revision.
    bounds = {"delta_bits": (2, 20), "coef_bits": (3, 30),
              "square_bits": (3, 40), "product_bits": (3, 40), "result_bits": (3, 40)}
    values = {k: integer(params, k, v, *bounds[k]) for k, v in defaults.items()}
    if values["delta_bits"] >= values["coef_bits"]:
        raise ValueError("delta_bits must be less than coef_bits for this Horner generator")
    prec = Precision(**values)
    screen = numeric_screen(prec)
    if not screen["passes_model_tolerance"]:
        # Preserve the measured negative result, but do not generate a circuit
        # already known to fail the arithmetic contract.
        return {"parameters": values, "numeric_screen": screen, "build_status": "screen_rejected"}
    circuit = build_nr_circuit(N_P, prec=prec)
    circuit.to_file(stage / "invsqrt.kmb", format="kmb")
    return {"parameters": values, "numeric_screen": screen, "build_status": "built",
            "qubits": circuit.num_qubits, "instructions": len(circuit),
            "operation_statistics": dict(circuit.operation_statistics())}


def requantize_words(words, source_brot: int, brot: int):
    """Round the periodic angle/2 fixed-point words when changing precision."""
    import numpy as np
    words = np.asarray(words)
    if words.ndim != 2 or not np.issubdtype(words.dtype, np.integer):
        raise ValueError("angle_words must be a 2-D integer array")
    if np.any(words < 0) or np.any(words >= 1 << source_brot):
        raise ValueError("angle_words do not fit source_brot")
    words = words.astype(np.int64)
    if brot >= source_brot:
        return words << (brot - source_brot)
    shift = source_brot - brot
    return ((words + (1 << (shift - 1))) >> shift) % (1 << brot)


def generate_dfthcsos(stage: Path, params: dict, args) -> dict:
    import numpy as np
    from dfthcsos.example_submission.angle_k_reference_circuit import (
        build_angle_k_family, write_kmx_family,
    )

    unknown = set(params) - {"brot", "source_brot", "batch_size", "prefix_bits"}
    if unknown:
        raise ValueError(f"Unknown dfthcsos parameters: {sorted(unknown)}")
    source = Path(args.source_npz).resolve()
    source_brot = integer(params, "source_brot", 12, 1, 30)
    brot = integer(params, "brot", source_brot, 1, 30)
    batch_size = integer(params, "batch_size", 8, 1, 75)
    with np.load(source, allow_pickle=False) as data:
        required = {"U", "W", "H2_I", "H1_I", "Hsym_lower", "tree_edges", "angle_words"}
        if not required.issubset(data.files):
            raise ValueError(f"Missing NPZ fields: {sorted(required - set(data.files))}")
        arrays = {key: np.array(data[key]) for key in data.files}
    words = requantize_words(arrays["angle_words"], source_brot, brot)
    arrays["angle_words"] = words
    num_bits = (words.shape[0] - 1).bit_length()
    prefix_bits = integer(params, "prefix_bits", 0, 0, num_bits)
    if prefix_bits:
        from dfthcsos_prefix import build_prefix_family, workspace_bits
        estimated_qubits = num_bits + brot * batch_size + workspace_bits(num_bits, prefix_bits)
    else:
        estimated_qubits = 2 * num_bits - 1 + brot * batch_size
    if estimated_qubits > 128:
        raise ValueError(f"QROM construction needs {estimated_qubits} qubits, exceeding ANGLE limit 128")
    circuits = (build_prefix_family(words, brot, batch_size, prefix_bits) if prefix_bits
                else build_angle_k_family(words, brot, batch_size))
    if any(c.num_qubits > 128 for c in circuits):
        raise ValueError("An ANGLE circuit exceeds the 128-qubit limit")
    write_kmx_family(circuits, stage, format="kmb")
    if brot == source_brot:
        shutil.copyfile(source, stage / "submission.npz")
    else:
        np.savez(stage / "submission.npz", **arrays)
    return {
        "parameters": {"brot": brot, "source_brot": source_brot, "batch_size": batch_size,
                       "prefix_bits": prefix_bits},
        "builder_family": "prefix_recomputed" if prefix_bits else "reference",
        "builder_sha256": sha256(Path(__file__).with_name("dfthcsos_prefix.py")) if prefix_bits else None,
        "build_status": "built", "source_npz": str(source), "source_npz_sha256": sha256(source),
        "factorization_arrays_preserved": True, "npz_byte_identical": brot == source_brot,
        "angle_precision_changed": brot != source_brot,
        "circuits": [{"index": i, "qubits": c.num_qubits, "instructions": len(c),
                      "operation_statistics": dict(c.operation_statistics())}
                     for i, c in enumerate(circuits)],
    }


def generate_dqi(stage: Path, params: dict, args) -> dict:
    unknown = set(params) - {"stack_cap", "sweep_mode"}
    if unknown:
        raise ValueError(f"Unknown dqi parameters: {sorted(unknown)}")
    stack_cap = integer(params, "stack_cap", 1, 1, 35)
    sweep_mode = params.get("sweep_mode", "product")
    if sweep_mode not in ("product", "phase"):
        raise ValueError("sweep_mode must be product or phase")
    command = [sys.executable, str(ROOT / "generators/dqi_adapter.py"),
               "--output-dir", str(stage), "--upstream", str(Path(args.upstream).resolve()),
               "--stack-cap", str(stack_cap), "--sweep-mode", sweep_mode,
               "--report", str(stage / "build_report.json")]
    subprocess.run(command, cwd=ROOT, check=True)
    report = json.loads((stage / "build_report.json").read_text())
    (stage / "build_report.json").unlink()
    return {"parameters": {"stack_cap": stack_cap, "sweep_mode": sweep_mode},
            "build_status": "built", "adapter_report": report}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("task", choices=("invsqrt", "dfthcsos", "dqi"))
    result.add_argument("--output-dir", required=True, type=Path, help="An empty candidate artifact directory")
    result.add_argument("--params", type=Path, help="JSON object with task-specific generator parameters")
    result.add_argument("--report", type=Path,
                        help="Generation metadata outside the artifact directory (default: OUTPUT_PARENT/generation.json)")
    result.add_argument("--source-npz", default=str(ROOT / "sample_submission/dfthcsos/submission.npz"))
    result.add_argument("--upstream", default=str(ROOT / "submission/2026-10-29/source/upstream"))
    return result


def main() -> int:
    args = parser().parse_args()
    params = json.loads(args.params.read_text()) if args.params else {}
    if not isinstance(params, dict):
        raise ValueError("--params must contain a JSON object")
    report_path = check_destination(args.report or args.output_dir.parent / "generation.json")
    output_path = args.output_dir.resolve()
    if report_path == output_path or output_path in report_path.parents:
        raise ValueError("Generation report must be outside the artifact directory")
    if report_path.exists():
        raise FileExistsError(f"Generation report already exists: {report_path}")
    started = time.monotonic()
    with output_workspace(args.output_dir) as (output, stage):
        report = globals()[f"generate_{args.task}"](stage, params, args)
        report.update({
            "task": args.task, "created_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.monotonic() - started, "official_validation": "not_run",
            "generator_sha256": sha256(Path(__file__)), "python_executable": sys.executable,
            "artifacts": [{"path": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)}
                          for p in sorted(stage.iterdir()) if p.is_file()],
        })
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output_dir": str(output), **report}, indent=2))
    return 0 if report["build_status"] == "built" else 2


if __name__ == "__main__":
    raise SystemExit(main())
