# SPDX-License-Identifier: Apache-2.0
"""Exact quadratic AND bounds after retaining a sequential lookup intermediate.

Controls range over affine forms in the original external control functions and
one retained first-target function. Enumerate the complete truth-table kernel,
so Boolean relations on the 256 reachable addresses are included. The alternating
quadratic matrix of each representation has rank at most twice its AND count.
This bounds sum-of-products rewrites in this control span, not arbitrary circuits
or networks that introduce further nonlinear intermediate controls.
"""
from __future__ import annotations
import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import shutil
import sys
import time
from invsqrt_lookup_resynth import ALL, INPUTS, Q, step, linear_basis, solve_columns
from invsqrt_cone_bounds import rank


def relations(columns):
    pivots, kernel = {}, []
    for i, value in enumerate(columns):
        mask = 1 << i
        while value:
            bit = value.bit_length()-1
            if bit not in pivots:
                pivots[bit] = value, mask
                break
            v, m = pivots[bit]
            value ^= v
            mask ^= m
        if not value:
            kernel.append(mask)
    return kernel


def quadratic_bound(values, target, *, one=ALL, max_kernel=18):
    pairs = list(combinations(range(len(values)), 2))
    columns = [one]+values+[values[a]&values[b] for a,b in pairs]
    base = solve_columns(columns, target)
    if base is None:
        return dict(status='outside_quadratic_span')
    kernel = relations(columns)
    if len(kernel) > max_kernel:
        return dict(status='kernel_budget_exceeded', kernel_dimension=len(kernel))
    histogram = Counter()
    best = None
    for subset in range(1 << len(kernel)):
        mask = base
        for i, relation in enumerate(kernel):
            if subset >> i & 1:
                mask ^= relation
        rows = [0]*len(values)
        for i,(a,b) in enumerate(pairs, 1+len(values)):
            if mask >> i & 1:
                rows[a] ^= 1 << b
                rows[b] ^= 1 << a
        matrix_rank = rank(rows)
        assert matrix_rank % 2 == 0
        bound = matrix_rank//2
        histogram[bound] += 1
        if best is None or bound < best[0]:
            best = bound, mask
    # Independently check the retained minimum representation on every row.
    actual = 0
    for i,value in enumerate(columns):
        if best[1] >> i & 1:
            actual ^= value
    assert actual == target
    return dict(status='complete', control_dimension=len(values),
        truth_table_rank=len(columns)-len(kernel), columns=len(columns),
        kernel_dimension=len(kernel), representations=1 << len(kernel),
        rank_half_histogram=dict(sorted(histogram.items())),
        minimum_and_lower_bound=best[0], witness_mask=best[1],
        kernel_masks=kernel)


def screen(lines, lo, hi):
    start = lines.index('R q22', 240)
    if not start <= lo < hi <= lines.index('HMR q24 b12600', start):
        raise ValueError('Window outside the pinned pure lookup block')
    initial = {q: None for q in range(62)}
    initial.update(INPUTS)
    for line in lines[start:lo]:
        step(initial, line)
    neutral, actual = initial.copy(), initial.copy()
    external, gates, controls = [], [], []
    for i,line in enumerate(lines[lo:hi], lo):
        if line.startswith('CCX '):
            a,b,target = map(int,Q.findall(line))
            external.extend([neutral[a], neutral[b]])
            controls.append([actual[a], actual[b]])
            gates.append(dict(index=i, target=target))
        step(neutral, line, skip_ccx=True)
        step(actual, line)
    if len(gates) < 3:
        raise ValueError('Require a multi-product sequential window')
    retained, target = gates[0]['target'], gates[1]['target']
    if retained == target or any(g['target'] != target for g in gates[1:]):
        raise ValueError('Template requires one retained gate followed by one target group')
    if any(neutral[q] != actual[q] for q in initial if q not in (retained,target)):
        raise ValueError('Nonlinear effects escape into other live wires')
    if neutral[retained] != 0:
        raise ValueError('First target must initially be clean in this template')
    values = [v for _,v in linear_basis(dict(enumerate(external)),-1)]
    values.append(actual[retained])
    if len(linear_basis(dict(enumerate(values)),-1)) != len(values):
        raise ValueError('Retained intermediate must enlarge the external span')
    affine = [ALL]+values
    if any(solve_columns(affine,v) is None for pair in controls[1:] for v in pair):
        raise ValueError('Original later controls not in the tested affine span')
    # These functions must also be available after the original affine tail.
    physical = [ALL]+[v for q,v in actual.items() if q != target and v is not None]
    if any(solve_columns(physical,v) is None for v in values):
        raise ValueError('Control forms unavailable without the rewritten target')
    result = quadratic_bound(values, actual[target]^neutral[target])
    original = len(gates)-1
    if result['status'] == 'complete':
        if result['minimum_and_lower_bound'] > original:
            raise AssertionError('Bound exceeds the original construction')
        decision = ('rejected_by_exact_quadratic_bound' if result['minimum_and_lower_bound'] == original
                    else 'open_lower_bound_requires_constructive_synthesis')
    else:
        decision = result['status']
    return dict(window=[lo,hi], retained_target=retained, target=target,
        retained_gates=1, original_remaining_and=original,
        original_total_and=len(gates), controls_truth_tables=values,
        target_delta=actual[target]^neutral[target], bound=result, decision=decision,
        scope='Retain the first AND; remaining gates are products of affine forms in the recorded control functions plus an affine output correction in that same span. No new nonlinear control intermediates or outside-span functions.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--expected-parent-sha256',required=True)
    p.add_argument('--candidate-dir',type=Path,required=True)
    p.add_argument('--start',type=int,required=True)
    p.add_argument('--end',type=int,required=True)
    args=p.parse_args(); started=time.monotonic()
    from generate import ROOT,sha256
    sys.path.insert(0,str(ROOT/'kickmix'))
    import kickmix as km
    source=args.parent_output/'invsqrt.kmb'
    if sha256(source)!=args.expected_parent_sha256:
        raise ValueError('Pinned parent changed')
    dest=args.candidate_dir/'screen';dest.mkdir(exist_ok=True)
    km.Circuit.from_file(source).to_file(dest/'parent.kmx')
    report=screen((dest/'parent.kmx').read_text().splitlines(),args.start,args.end)
    report.update(kind='dependency_preserving_quadratic_span_bound',official_validation=False,
        parent_sha256=sha256(source),parent_output=str(args.parent_output.resolve()),
        source_generator_available=False,argv=sys.argv,python=sys.executable,prefix=sys.prefix,
        elapsed_seconds=time.monotonic()-started)
    report['source_hashes']={}
    for name in ('invsqrt_quadratic_span.py','invsqrt_cone_bounds.py','invsqrt_lookup_resynth.py','invsqrt_joint_outputs.py','generate.py'):
        src=Path(__file__).with_name(name)
        shutil.copy2(src,args.candidate_dir/'code'/name)
        report['source_hashes'][name]=sha256(src)
    (args.candidate_dir/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('decision','bound','elapsed_seconds')}))


if __name__ == '__main__':
    main()
