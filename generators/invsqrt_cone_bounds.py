# SPDX-License-Identifier: Apache-2.0
"""Cheap AND-count lower bounds for dependency-preserving lookup rewrites.

The span includes the constant, every known incoming wire (including old target
values), and all required outgoing wires. X/CX do not enlarge it; a CCX can add
at most one dimension. Thus rank(out union in)-rank(in) lower-bounds the number
of CCX in a measurement-free X/CX/CCX replacement preserving those wire values.
This is a lower bound, not a synthesis algorithm or a bound on quantum circuits
with measurements. Tables cover all 256 addresses of the pinned architecture.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import time
from invsqrt_lookup_resynth import ALL, INPUTS, step
from invsqrt_joint_outputs import extract_windows


def rank(columns):
    pivots = {}
    for value in columns:
        while value:
            bit = value.bit_length()-1
            if bit not in pivots:
                pivots[bit] = value
                break
            value ^= pivots[bit]
    return len(pivots)


def lower_bound(initial, final):
    incoming = [ALL]+[value for value in initial.values() if value is not None]
    outgoing = [value for value in final.values() if value is not None]
    before = rank(incoming)
    return rank(incoming+outgoing)-before


def screen(lines):
    _, structure = extract_windows(lines, complete_affine_tail=True)
    state = {q: None for q in range(62)}
    state.update(INPUTS)
    positions = {r[k] for r in structure['rejected'] for k in ('start', 'end')}
    snapshots = {}
    for i in range(structure['start'], structure['end']):
        if i in positions:
            snapshots[i] = state.copy()
        step(state, lines[i])
    snapshots[structure['end']] = state.copy()
    rows = []
    for item in structure['rejected']:
        lo, hi = item['start'], item['end']
        count = sum(line.startswith('CCX ') for line in lines[lo:hi])
        bound = lower_bound(snapshots[lo], snapshots[hi])
        if bound > count:
            raise AssertionError('Rank bound exceeds original implementation')
        rows.append(dict(**item, original_count=count, nonlinear_lower_bound=bound,
            maximum_possible_saving=count-bound,
            decision='rejected_by_exact_rank_bound' if bound == count else 'open_bound_not_tight'))
    return dict(structure=structure, windows=rows,
        tight_bounds=sum(row['decision']=='rejected_by_exact_rank_bound' for row in rows),
        open_windows=sum(row['decision']=='open_bound_not_tight' for row in rows))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--candidate-dir', type=Path, required=True)
    p.add_argument('--expected-parent-sha256', required=True)
    args = p.parse_args(); started = time.monotonic()
    from generate import ROOT, sha256
    sys.path.insert(0, str(ROOT/'kickmix'))
    import kickmix as km
    source = args.parent_output/'invsqrt.kmb'
    if sha256(source) != args.expected_parent_sha256:
        raise ValueError('Pinned parent changed')
    dest = args.candidate_dir/'screen'; dest.mkdir(exist_ok=True)
    km.Circuit.from_file(source).to_file(dest/'parent.kmx')
    report = screen((dest/'parent.kmx').read_text().splitlines())
    report.update(kind='dependency_preserving_and_rank_bounds', official_validation=False,
        parent_output=str(args.parent_output.resolve()), parent_sha256=sha256(source),
        source_generator_available=False, argv=sys.argv, python=sys.executable,
        prefix=sys.prefix, generator_sha256=sha256(Path(__file__)),
        elapsed_seconds=time.monotonic()-started)
    for name in ('invsqrt_cone_bounds.py', 'invsqrt_joint_outputs.py', 'invsqrt_lookup_resynth.py'):
        shutil.copy2(Path(__file__).with_name(name), args.candidate_dir/'code'/name)
    (args.candidate_dir/'generation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('kind', 'tight_bounds', 'open_windows', 'elapsed_seconds')}))


if __name__ == '__main__':
    main()
