"""Transplant local diff hunks from a donor InvSqrt circuit into a target circuit.

Both circuits are decoded to KickMix text. A line diff (difflib, no autojunk)
maps donor lines to target lines; every non-equal opcode whose donor span lies
inside one of the requested donor line windows (1-based, inclusive) is applied
to the target, replacing the target's span with the donor's. Everything outside
those windows stays byte-identical to the target's text.

Typical use: port a public local rewrite (e.g. Ehan Mallick's AND merges in the
yoyobar lineage) into a sibling circuit derived from the same base. The output
is only a proposal: exactness rests on state invariants shared by both circuits,
so the result must pass the full official InvSqrt verifier. A cheap sampled
screen (random x, phase/scratch/x restoration) is run here before writing.
The license and ancestry of donor and target circuits apply to the output.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TOF = ('CCX', 'CCZ', 'CSWAP')


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def transplant(target: list[str], donor: list[str], windows: list[tuple[int, int]]):
    sm = difflib.SequenceMatcher(None, donor, target, autojunk=False)
    out, applied, pos = [], [], 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        lo = i1 + 1
        hi = max(i2, i1 + 1)
        if not any(a <= lo and hi <= b for a, b in windows):
            continue
        out.extend(target[pos:j1])
        out.extend(donor[i1:i2])
        pos = j2
        applied.append({'tag': tag, 'donor': [i1 + 1, i2], 'target': [j1 + 1, j2],
                        'donor_tof': sum(l.split()[0] in TOF for l in donor[i1:i2]),
                        'target_tof': sum(l.split()[0] in TOF for l in target[j1:j2])})
    out.extend(target[pos:])
    return out, applied


def sampled_screen(km, circuit, shots: int, seed: int):
    sys.path.insert(0, str(ROOT / 'verifiers' / 'invsqrt'))
    import verify_submission_invsqrt as v  # official helpers, read-only use
    spec = v.ProblemSpecInvSqrt.for_n_p(v.N_P)
    x_reg, scratch = v.validate_registers(circuit, spec)
    rng = np.random.default_rng(seed)
    batch = 256
    worst, tof = 0.0, 0.0
    special = np.array([1, 2, 3, 161, spec.max_x, spec.max_x - 1] + [1 << k for k in range(22) if (1 << k) <= spec.max_x], dtype=np.uint64)
    sim = km.Simulator(batch_size=batch, debug_print=False, counting_operations=True, seed=seed)
    n = 0
    while n < shots:
        xs = rng.integers(1, spec.max_x + 1, size=batch).astype(np.uint64)
        if n == 0:
            xs[:len(special)] = special
        target, tol = v.reference_values(spec, xs)
        sim.clear_for_shot()
        sim.write_across_shots(x_reg, v.to_bits(xs, spec.width))
        sim.do(circuit)
        if not np.array_equal(v.from_bits(sim.read_across_shots(x_reg)), xs):
            return {'passed': False, 'reason': 'x not restored'}
        if sim.read_across_shots(scratch).any():
            return {'passed': False, 'reason': 'dirty scratch'}
        theta = np.array([v.half_turns_to_units(sim.read_shot_phase(i)) for i in range(batch)], dtype=np.uint64)
        err = np.abs((theta - target).view(np.int64)).view(np.uint64)
        if (err > tol).any():
            i = int(np.argmax(err > tol))
            return {'passed': False, 'reason': f'phase error at x={int(xs[i])}'}
        worst = max(worst, float((err / tol).max()))
        n += batch
    st = dict(sim.operation_statistics())
    return {'passed': True, 'shots': n, 'worst_err_over_tol_noeps': worst,
            'mean_toffoli': sum(st.get(k, 0) for k in TOF) / n}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--target', type=Path, required=True, help='target invsqrt.kmb')
    ap.add_argument('--donor', type=Path, required=True, help='donor invsqrt.kmb')
    ap.add_argument('--window', action='append', required=True,
                    help='donor line window START:END (1-based inclusive, kmx text lines)')
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--screen-shots', type=int, default=8192)
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT / 'kickmix'))
    import kickmix as km
    start = time.monotonic()
    candidate = args.output_dir.resolve().parent
    work = candidate / 'screen'
    work.mkdir(parents=True, exist_ok=True)
    texts = {}
    for name, path in (('target', args.target), ('donor', args.donor)):
        km.Circuit.from_file(path).to_file(work / f'{name}.kmx')
        texts[name] = (work / f'{name}.kmx').read_text().splitlines()
    windows = [tuple(map(int, w.split(':'))) for w in args.window]
    lines, applied = transplant(texts['target'], texts['donor'], windows)
    (work / 'transplanted.kmx').write_text('\n'.join(lines) + '\n')
    circuit = km.Circuit.from_file(work / 'transplanted.kmx')
    parent = km.Circuit.from_file(args.target)
    screen = sampled_screen(km, circuit, args.screen_shots, 12345)
    report = {
        'kind': 'invsqrt_transplant_hunks', 'official_validation': False,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'generator': 'generators/invsqrt_transplant_hunks.py',
        'generator_sha256': sha256(Path(__file__)),
        'command': sys.argv,
        'target': str(args.target.resolve()), 'target_sha256': sha256(args.target),
        'donor': str(args.donor.resolve()), 'donor_sha256': sha256(args.donor),
        'windows': windows, 'applied_opcodes': applied,
        'static_toffoli_delta': sum(a['donor_tof'] - a['target_tof'] for a in applied),
        'num_qubits': [parent.num_qubits, circuit.num_qubits],
        'python_executable': sys.executable, 'python_prefix': sys.prefix,
        'sampled_screen': screen,
    }
    if not screen['passed'] or circuit.num_qubits > parent.num_qubits:
        report['decision'] = 'screen_failed_not_written'
        (candidate / 'generation.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        sys.exit(2)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    circuit.to_file(args.output_dir / 'invsqrt.kmb', format='kmb')
    report['artifacts'] = [{'path': 'invsqrt.kmb', 'sha256': sha256(args.output_dir / 'invsqrt.kmb')}]
    report['elapsed_seconds'] = time.monotonic() - start
    report['decision'] = 'written_pending_official_validation'
    (candidate / 'generation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'applied_opcodes'}, indent=2))


if __name__ == '__main__':
    main()
