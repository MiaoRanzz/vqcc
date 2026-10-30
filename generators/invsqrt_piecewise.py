"""Reproduce the licensed piecewise-quadratic family and screen carry tradeoffs.

Original arithmetic: Houssem Alayet (marsyas), Kaggle notebook version 2.
See vendor/marsyas_invsqrt/NOTICE.md. This adapter runs no notebook cells and
never submits. All model/sample checks are screening, not official validation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from generate import ROOT, output_workspace, sha256

VENDOR = Path(__file__).parent / "vendor" / "marsyas_invsqrt"
sys.dont_write_bytecode = True
sys.path[:0] = [str(VENDOR), str(ROOT / "kickmix"), str(ROOT / "verifiers")]


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def boundary_inputs():
    """Both sides of every segment and normalization transition in the legal domain."""
    xs = {1, 2, 3, 3133452}
    for shift in range(22):
        for seg in range(129):
            center = ((1 << 21) + (seg << 14)) >> shift
            xs.update(x for x in (center - 1, center, center + 1)
                      if 1 <= x <= 3133452)
    return sorted(xs)


def circuit_boundary_check(circuit, tables, prm, layout, angles):
    import kickmix as km
    import numpy as np
    import check as Ck
    import hsplit as H

    values = boundary_inputs()
    xr = km.array(list(circuit.register_data["x"]))
    scratch = km.array([km.q(i) for i in range(circuit.num_qubits)
                        if km.q(i) not in set(xr)])
    # Fixed before any candidate is generated; this checks changed arithmetic
    # boundaries under measurement randomness, never selects circuit hashes.
    seed, batch = 20261030, 256
    sim = km.Simulator(batch_size=batch, seed=seed, debug_print=False)
    for start in range(0, len(values), batch):
        chunk = values[start:start + batch]
        xs = np.array(chunk + [chunk[-1]] * (batch - len(chunk)), dtype=np.uint64)
        sim.clear_for_shot()
        sim.write_across_shots(xr, Ck.to_bits(xs, 22))
        sim.do(circuit)
        if not np.array_equal(Ck.from_bits(sim.read_across_shots(xr)), xs):
            raise AssertionError("Input restoration failed at a segment boundary")
        if sim.read_across_shots(scratch).any():
            raise AssertionError("Scratch restoration failed at a segment boundary")
        phase = np.array([Ck.half_turns_to_units(sim.read_shot_phase(i))
                          for i in range(batch)], dtype=np.uint64)
        model = H.phases_multi(H.regs(tables, prm, layout, xs.astype(np.int64)), angles)
        if not np.array_equal(phase, model):
            raise AssertionError("Boundary circuit/model phase mismatch")
    return {"kind": "segment_and_normalization_boundaries", "distinct_inputs": len(values),
            "measurement_seed": seed, "status": "PASS", "official_validation": False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--fit-from", type=Path, help="Reuse a recorded coefficients.json without refitting")
    ap.add_argument("--qcap", type=int, help="Adder carry target; not a hard global qubit cap")
    ap.add_argument("--no-windows", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--stop-by", required=True)
    args = ap.parse_args()
    stop = datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None:
        ap.error("--stop-by must include a timezone")
    if not 1 <= args.workers <= 19 or (args.qcap is not None and not 40 <= args.qcap <= 128):
        ap.error("workers must be 1..19; qcap must be 40..128")
    if (stop - datetime.now(timezone.utc)).total_seconds() < 1200:
        ap.error("Require at least 20 minutes for fitting, generation and checkpoint")
    import numpy as np
    import model as M
    import fit as F
    import hsplit as H
    import build as B
    import check as C

    started = time.monotonic()
    candidate = args.output_dir.resolve().parent
    code = candidate / "code"
    code.mkdir(parents=True, exist_ok=True)
    prm = M.Params(F0=28, FT=19, F2=8, G0=1, sd=True, tcap=True,
                   rowsA=tuple(i for i in range(14) if i != 5))
    params = {"arithmetic": asdict(prm), "LB": 21, "S": 20, "drop": 1,
              "qcap": args.qcap, "nested_windows": not args.no_windows,
              "workers": args.workers, "boundary_measurement_seed": 20261030}
    write(code / "params.json", params)
    M.CACHE = str(candidate / "screen" / "reference.npz")
    (candidate / "screen").mkdir(exist_ok=True)
    upstream = {p.name: sha256(p) for p in sorted(VENDOR.iterdir()) if p.is_file()}
    report = {"task": "invsqrt", "parameters": params,
              "source": "marsyas/vqcc-invsqrt-13-94x-full-source version 2",
              "license": "Apache-2.0", "upstream_sha256": upstream,
              "adapter_sha256": sha256(Path(__file__)),
              "python_executable": sys.executable, "sys_prefix": sys.prefix,
              "cpu_affinity": sorted(os.sched_getaffinity(0)),
              "official_validation": False}
    write(candidate / "generation.json", {**report, "build_status": "started"})
    with output_workspace(args.output_dir) as (_, stage):
        if args.fit_from:
            saved = json.loads(args.fit_from.read_text())
            if saved["arithmetic"] != json.loads(json.dumps(asdict(prm))):
                raise ValueError("Saved coefficient arithmetic parameters differ")
            tables = np.array(saved["tables"], dtype=np.int64)
            angles = saved["angles"]
            report["fit_parent"] = {"path": str(args.fit_from.resolve()),
                                    "sha256": sha256(args.fit_from)}
        else:
            tables, fit_worst = F.fit_all(prm, workers=args.workers)
            report["fit_worst_approx_ratio"] = fit_worst
            angles = None
        if tables.shape != (256, 3):
            raise ValueError("Expected 256 three-coefficient segments")
        lay = H.layout(tables, prm, params["LB"], params["S"])
        if lay is None:
            raise ValueError("High/low layout overflows")
        if angles is None:
            calibrated = H.calibrate_multi(tables, prm, lay, drop=params["drop"], verbose=True)
            if calibrated is None:
                raise ValueError("Phase calibration failed")
            angles, _, _, _ = calibrated
        worst, margin, _, _, _ = H.check_multi(tables, prm, lay, angles)
        report["numeric_screen"] = {"kind": "exact_integer_phase_full_domain",
            "inputs": M.MAX_X, "error_over_tolerance": worst,
            "min_margin_units": int(margin), "passes_model_tolerance": worst < 1 and margin > 0,
            "official_validation": False}
        write(code / "coefficients.json", {"arithmetic": asdict(prm),
            "tables": tables.tolist(), "angles": angles, "layout": {"LB": 21, "S": 20}})
        if not report["numeric_screen"]["passes_model_tolerance"]:
            report["build_status"] = "screen_rejected"
        else:
            if (stop - datetime.now(timezone.utc)).total_seconds() < 300:
                raise TimeoutError("Insufficient remaining time for circuit screening")
            a, p, xn, _ = F._D
            windows_a = M.window_ranges1(tables, prm, xn, p)
            opts = B.Opts(WA=windows_a["A"], WB=None, gA=1)
            opts.mdel, opts.kbig, opts.qcap = True, 0, args.qcap
            opts.wins = None if args.no_windows else H.parse_plan(
                "17:11,10;15:9,8;13:7,6;11:5,4;9:3,2;7:1,0")
            opts.wcb = None if opts.wins is None else H.choose_cbits(tables, prm, lay, opts.wins)
            if opts.wins and opts.wcb is None:
                raise ValueError("Nested window counters do not fit")
            report["window_counter_bits"] = opts.wcb
            M.PHASE_FN = lambda xs: H.phases_multi(H.regs(tables, prm, lay, xs), angles)
            circuit = H.build_hsplit(tables, prm, opts, lay, angles)
            report["sample_screen"] = C.report(circuit, tables, prm,
                {"pass": True, "min_margin": margin}, nbatch=4)
            report["boundary_screen"] = circuit_boundary_check(circuit, tables, prm, lay, angles)
            circuit.to_file(stage / "invsqrt.kmb", format="kmb")
            report["circuit_sha256"] = sha256(stage / "invsqrt.kmb")
            report["build_status"] = "built"
            report["builder_tracked_peak"] = B.LAST_PEAK
    report["elapsed_seconds"] = time.monotonic() - started
    write(candidate / "generation.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
