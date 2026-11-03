# SPDX-License-Identifier: Apache-2.0
"""Apply exact three-to-two AND merges found by invsqrt_deferred_products.census.

For each constructive window (lo, mid, hi) of three unconditional CCX where the
first two accumulate p0, p1 into an unread accumulator `acc` and the third
writes p2 into another wire `tgt`, the census factors p0+p1+p2 (affine ANF over
independent incoming wires) as one product plus linear terms available at `mid`.
The rewrite is:

* delete CCX at lo;
* replace CCX at mid with the census replacement (acc ^= p0+p1+p2, one CCX);
* replace CCX a b tgt at hi with the delta copy CX acc tgt; CCX a b acc;
  CX acc tgt, so tgt ^= p2 and acc ^= p2 (cancelling the extra p2).

acc is neither read nor reset inside the window (checked by the census), so acc
and tgt equal the original values after hi and no phase gate sees a changed
wire. This is the construction behind Ehan Mallick's public merges on the
yoyobar circuit. Saves one CCX per window. A sampled screen runs before writing;
full official validation remains the gate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from invsqrt_deferred_products import census  # noqa: E402
from invsqrt_transplant_hunks import ROOT, sha256, sampled_screen  # noqa: E402

Q = re.compile(r'\bq(\d+)\b')


def apply(lines, windows):
    used, edits = set(), {}
    chosen = []
    for w in windows:
        lo, mid, hi = w['positions']
        if used & set(range(lo, hi + 1)):
            continue
        used |= set(range(lo, hi + 1))
        acc = w['accumulator']
        a, b, tgt = map(int, Q.findall(lines[hi]))
        assert lines[lo].startswith('CCX ') and lines[mid].startswith('CCX ') and lines[hi].startswith('CCX ')
        assert tgt == w['reset_target'] and tgt != acc
        edits[lo] = []
        edits[mid] = list(w['replacement_product'])
        edits[hi] = [f'CX q{acc} q{tgt}', f'CCX q{a} q{b} q{acc}', f'CX q{acc} q{tgt}']
        chosen.append({'positions_1based': [lo + 1, mid + 1, hi + 1], 'accumulator': acc, 'target': tgt,
                       'original': [lines[lo], lines[mid], lines[hi]], 'mid_replacement': edits[mid],
                       'hi_replacement': edits[hi], 'saved_ccx': 3 - sum(x.startswith('CCX ') for x in edits[mid] + edits[hi])})
    out = []
    for i, line in enumerate(lines):
        out.extend(edits.get(i, [line]))
    return out, chosen


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--parent-output', type=Path, required=True)
    ap.add_argument('--expected-parent-sha256', required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--max-span', type=int, default=300)
    ap.add_argument('--only', action='append', type=int, default=[],
                    help='restrict to windows whose lo (1-based kmx line) is listed')
    ap.add_argument('--screen-shots', type=int, default=8192)
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT / 'kickmix'))
    import kickmix as km
    start = time.monotonic()
    source = args.parent_output / 'invsqrt.kmb'
    if sha256(source) != args.expected_parent_sha256:
        raise ValueError('Pinned parent changed')
    candidate = args.output_dir.resolve().parent
    work = candidate / 'screen'
    work.mkdir(parents=True, exist_ok=True)
    parent = km.Circuit.from_file(source)
    parent.to_file(work / 'parent.kmx')
    lines = (work / 'parent.kmx').read_text().splitlines()
    result = census(lines, parent.num_qubits, args.max_span, False)
    windows = [w for w in result['windows'] if w['decision'].startswith('constructive')]
    if args.only:
        windows = [w for w in windows if w['positions'][0] + 1 in args.only]
    new, chosen = apply(lines, windows)
    (work / 'merged.kmx').write_text('\n'.join(new) + '\n')
    circuit = km.Circuit.from_file(work / 'merged.kmx')
    screen = sampled_screen(km, circuit, args.screen_shots, 24680)
    report = {
        'kind': 'invsqrt_three_to_two_and_merges', 'official_validation': False,
        'created_at': datetime.now(timezone.utc).isoformat(), 'command': sys.argv,
        'generator': 'generators/invsqrt_merge_products.py',
        'source_hashes': {n: sha256(Path(__file__).with_name(n)) for n in
                          ('invsqrt_merge_products.py', 'invsqrt_deferred_products.py', 'invsqrt_lookup_resynth.py',
                           'invsqrt_cone_bounds.py', 'invsqrt_transplant_hunks.py')},
        'parent_output': str(args.parent_output.resolve()), 'parent_sha256': sha256(source),
        'census_decisions': result['decisions'], 'tested_windows': result['tested_windows'],
        'applied_windows': chosen, 'static_ccx_saved': sum(c['saved_ccx'] for c in chosen),
        'num_qubits': [parent.num_qubits, circuit.num_qubits],
        'python_executable': sys.executable, 'python_prefix': sys.prefix, 'sampled_screen': screen,
    }
    if not screen['passed'] or circuit.num_qubits > parent.num_qubits or not chosen:
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
    print(json.dumps({k: v for k, v in report.items() if k != 'applied_windows'}, indent=2))
    for c in chosen:
        print(c['positions_1based'], c['saved_ccx'])


if __name__ == '__main__':
    main()
