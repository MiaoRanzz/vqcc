"""Build-only DQI lifetime screening; does not expand or verify a circuit."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time
import dqi_adapter as adapter


def profile(builder):
    live, owned = set(), defaultdict(set)
    phase, peaks = "init", {}
    for kind, value, token, count in builder.wire_log:
        if kind == "mark":
            phase = value
        elif kind == "alloc":
            live.add(value)
        elif kind == "free":
            live.remove(value)
        elif kind == "claim":
            name, wires = value
            owned[name].update(wires)
        elif kind == "release":
            name, wires = value
            owned[name].difference_update(wires)
        # Claims follow allocation; record at equal counts to capture ownership.
        if len(live) >= peaks.get(phase, {}).get("live", -1):
            sizes = {name: len(ids & live) for name, ids in owned.items() if ids & live}
            unclaimed = len(live - set().union(*owned.values()))
            previous = peaks.get(phase)
            # Allocation precedes claim and release precedes recycle. At an
            # equal peak prefer the fully claimed state, not transient bookkeeping.
            if (previous is None or len(live) > previous["live"]
                    or unclaimed < previous["unclaimed"]):
                peaks[phase] = {"live": len(live), "owners": sizes,
                                "unclaimed": unclaimed}
    return {"num_qubits": builder.next_qubit, "peak_live": builder.peak_qubits,
            "peak_phase": builder.peak_phase, "phase_peaks": peaks,
            "upstream_phase_summary": builder.phase_summary(),
            "cost_warning": "Upstream bills classical-controlled CZ as Toffoli; kickmix official cost differs. This phase summary is a liveness/emission profile, not an official cost."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-mode", choices=("product", "phase"), required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("report must be new")
    started = time.monotonic()
    p = adapter.load_source(adapter.ROOT / "submission/2026-10-29/source/upstream")
    forward, backward, step, beta = adapter.field_isomorphism(p)
    adapter.install_adapter(p, forward, backward, step, args.sweep_mode)
    b, _ = p.build()
    result = {"kind": "build_only_lifetime_screen", "official_validation": False,
              "sweep_mode": args.sweep_mode, "elapsed_seconds": time.monotonic() - started,
              "python_executable": sys.executable, **profile(b),
              "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                for name in ("dqi_adapter.py", "dqi_phase.py", "profile_dqi.py")}}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k:result[k] for k in ("sweep_mode", "num_qubits", "peak_live", "peak_phase", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
