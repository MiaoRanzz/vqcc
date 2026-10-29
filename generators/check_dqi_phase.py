"""Local full-field boundary checks for the direct DQI product phase.

This is deterministic screening and measurement-cleanup diagnostics, not the
full DQI verifier. Seed is supplied before results, never chosen by outcome.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "generators"), str(ROOT / "kickmix")]
import numpy as np
import dqi_adapter as adapter
from dqi_phase import product_phase_terms, emit_product_phase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("report must be new")
    start = time.monotonic()
    p = adapter.load_source(ROOT / "submission/2026-10-29/source/upstream")
    forward, backward, step, beta = adapter.field_isomorphism(p)
    km = adapter.km
    b = p.Builder()
    x, y, root = b.qubits(p.B), b.qubits(p.B), b.qubit()
    scratch = b.qubits(p.B)
    pivots = b.qubits(3)
    mask = b.bits(p.B)
    E = p.Em(b, *pivots, p.Alloc(b))
    terms = product_phase_terms(p, backward)
    emit_product_phase(p, E, root, x, y, scratch, terms, mask)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "phase.kmx"
        adapter.write_kmx(b, path, SimpleNamespace(N=0, M=0, B=p.B))
        c = km.Circuit.from_file(path, format="kmx")
    # Independent multiplication oracle uses the competition GF2Field after
    # basis conversion, rather than the emitter's p.gmul tensor expansion.
    transform = np.array([sum(((v & row).bit_count() & 1) << i
                              for i, row in enumerate(backward))
                          for v in range(1 << p.B)], dtype=np.uint64)
    field = km.GF2Field(p.B)
    parity = np.array([v.bit_count() & 1 for v in range(1 << p.B)], dtype=bool)
    qx, qy = km.array([km.q(i) for i in x]), km.array([km.q(i) for i in y])
    qr = km.array([km.q(root)])
    qm = km.array([km.b(i.id) for i in mask])
    qa = km.array([km.q(i) for i in scratch + pivots])
    rng = np.random.default_rng(args.seed)
    applications = 0

    def bits(values, width):
        return ((values[None, :] >> np.arange(width, dtype=np.uint64)[:, None]) & 1).astype(bool)

    def check(xs, ys, masks, roots, ordinal):
        nonlocal applications
        xs, ys, masks, roots = [np.asarray(v, dtype=np.uint64) for v in (xs, ys, masks, roots)]
        actual_product = np.array([field.mul(int(transform[a]), int(transform[d]))
                                   for a, d in zip(xs, ys)], dtype=np.uint64)
        expected = parity[actual_product & masks] & roots.astype(bool)
        sim = km.Simulator(batch_size=len(xs), seed=args.seed + ordinal)
        sim.use_same_registers_as(c)
        for reg, values, width in ((qx, xs, p.B), (qy, ys, p.B), (qm, masks, p.B), (qr, roots, 1)):
            sim.write_across_shots(reg, bits(values, width))
        # Twice: check the desired phase on the first pass and cancellation on
        # the second, with fresh measurement outcomes on both applications.
        for want in (expected, np.zeros(len(xs), dtype=bool)):
            sim.do(c)
            np.testing.assert_array_equal(sim.read_phase_flipped_across_shots(), want)
            for reg, values, width in ((qx, xs, p.B), (qy, ys, p.B), (qm, masks, p.B), (qr, roots, 1)):
                np.testing.assert_array_equal(sim.read_across_shots(reg), bits(values, width))
            if sim.read_across_shots(qa).any():
                raise AssertionError("phase-product scratch not clean")
            applications += len(xs)

    # All 4096 x values, all 12 y basis vectors, each of 12 output mask bits,
    # root=0 and root=1. Basis-linearity then covers every y and mask algebraically.
    xs = np.tile(np.arange(4096, dtype=np.uint64), 2)
    roots = np.repeat(np.array([0, 1], dtype=np.uint64), 4096)
    ordinal = 0
    for j in range(p.B):
        for k in range(p.B):
            check(xs, np.full(len(xs), 1 << j), np.full(len(xs), 1 << k), roots, ordinal)
            ordinal += 1
    # Mixed operands/masks stress interactions and measurement repayment.
    for _ in range(4):
        check(rng.integers(0, 4096, 8192), rng.integers(0, 4096, 8192),
              rng.integers(0, 4096, 8192), rng.integers(0, 2, 8192), ordinal)
        ordinal += 1
    # Explicit zero and all-one mask/operand boundaries.
    for value in (0, 4095):
        check(xs, np.full(len(xs), value), np.full(len(xs), value), roots, ordinal)
        ordinal += 1
    result = {"status": "PASS", "official_validation": False,
              "kind": "full_field_basis_phase_and_measurement_cleanup",
              "seed": args.seed, "cases": applications // 2, "applications": applications,
              "phase_terms": len(terms), "qubits": c.num_qubits,
              "operation_statistics": dict(c.operation_statistics()),
              "elapsed_seconds": time.monotonic() - start, "python_executable": sys.executable,
              "isomorphism_beta": beta, "primitive_exponent": step,
              "source_sha256": {name: hashlib.sha256((ROOT / "generators" / name).read_bytes()).hexdigest()
                                for name in ("dqi_phase.py", "dqi_adapter.py", "check_dqi_phase.py")}}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
