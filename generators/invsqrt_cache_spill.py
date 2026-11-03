# SPDX-License-Identifier: Apache-2.0
"""Release and reconstruct idle InvSqrt caches with exact Boolean certificates.

The conservative symbolic algebra proves a cached value is an affine/quadratic
function of other live wires at BOTH ends of an unused interval. An affine
cache is erased by XOR. A quadratic cache is erased by HMR followed by a
conditional phase for every polynomial term. Reconstruction uses X/CX/CCX.
Only disjoint time intervals are combined, so certificates cannot accidentally
read another spilled cache. Classical condition boundaries are excluded.
This is a pinned-artifact transform; it does not recover the upstream generator.
"""
from __future__ import annotations
import argparse
import bisect
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
import sys
import time

from invsqrt_clean_lifetimes import Algebra, ZERO, ONE, pack_proven
from invsqrt_reset_lifetimes import Q, ALLOWED
from generate import ROOT, sha256, output_workspace


def snapshots(lines, points):
    alg = Algebra()
    state = {q: alg.fresh() for q in range(22)}
    depth = 0
    saved = {}
    for i, line in enumerate(lines):
        if i in points:
            saved[i] = (state.copy(), depth)
        f = line.split()
        if not f:
            continue
        op = f[0]
        if op not in ALLOWED:
            raise ValueError(f'Unsupported operation {op}')
        qs = list(map(int, Q.findall(line))) if op != 'REGISTER' else []
        for q in qs:
            state.setdefault(q, ZERO)
        cond = depth > 0 or 'if' in f
        if op == 'PUSH_CONDITION':
            if qs:
                raise ValueError('Quantum condition block')
            depth += 1
        elif op == 'POP_CONDITION':
            depth -= 1
            if depth < 0:
                raise ValueError('Unbalanced condition block')
        elif op in ('X', 'CX', 'CCX'):
            delta = ONE
            for q in qs[:-1]:
                delta = alg.mul(delta, state[q])
            if delta:
                state[qs[-1]] = alg.fresh() if cond else alg.xor(state[qs[-1]], delta)
        elif op in ('SWAP', 'CSWAP'):
            a, b = qs[-2:]
            if state[a] != state[b]:
                c = state[qs[0]] if op == 'CSWAP' else ONE
                if c:
                    if cond:
                        state[a], state[b] = alg.fresh(), alg.fresh()
                    else:
                        delta = alg.mul(c, alg.xor(state[a], state[b]))
                        state[a] = alg.xor(state[a], delta)
                        state[b] = alg.xor(state[b], delta)
        elif op in ('R', 'HMR'):
            state[qs[0]] = alg.fresh() if cond and state[qs[0]] else ZERO
    if depth:
        raise ValueError('Unbalanced condition block')
    return saved, alg


def recipe_solver(alg):
    @lru_cache(maxsize=None)
    def encode(expr):
        value = 0
        for atom in expr:
            value |= 1 << atom
        return value

    def solve(target, state, exclude, quadratic=True):
        available = {q: v for q, v in state.items() if q != exclude}
        exprwire = {v: q for q, v in available.items() if v}
        terms = [([], ONE)] + [([q], v) for q, v in available.items()]
        if quadratic:
            for (a, b), value in alg.products.items():
                if a in exprwire and b in exprwire and a != b:
                    terms.append(([exprwire[a], exprwire[b]], value))
        pivots = {}
        for k, (_, expr) in enumerate(terms):
            row, combo = encode(expr), 1 << k
            while row:
                bit = row.bit_length() - 1
                if bit in pivots:
                    row ^= pivots[bit][0]
                    combo ^= pivots[bit][1]
                else:
                    pivots[bit] = (row, combo)
                    break
        row, combo = encode(target), 0
        while row:
            bit = row.bit_length() - 1
            if bit not in pivots:
                return None
            row ^= pivots[bit][0]
            combo ^= pivots[bit][1]
        return [term for k, (term, _) in enumerate(terms) if combo >> k & 1]
    return solve


def select_disjoint(candidates):
    """Maximize covered original peak points, then minimize reconstruction gates."""
    items = sorted(candidates, key=lambda x: (x['hi'], x['lo'], x['q']))
    ends = [g['hi'] for g in items]
    # Score is lexicographic; the intervals are disjoint so coverage is additive.
    scores = [(0, 0, 0)]
    choices = [[]]
    for k, g in enumerate(items):
        previous = bisect.bisect_left(ends, g['lo'], 0, k)
        delta = (g['peak_coverage'], -g['extra_toffoli'], -len(g['erase'])-len(g['restore']))
        score = tuple(a+b for a, b in zip(scores[previous], delta))
        if score > scores[-1]:
            scores.append(score)
            choices.append(choices[previous] + [g])
        else:
            scores.append(scores[-1])
            choices.append(choices[-1])
    return choices[-1]


def screen(text, mode):
    lines = text.splitlines()
    _, packing = pack_proven(text)
    counts = [0] * (len(lines)+2)
    for item in packing['intervals']:
        counts[item['start']] += 1
        counts[item['end']+1] -= 1
    for i in range(1, len(counts)):
        counts[i] += counts[i-1]
    threshold = packing['packed_qubits'] - 22
    peak = [int(v >= threshold) for v in counts[:len(lines)]]
    prefix = [0]
    for value in peak:
        prefix.append(prefix[-1]+value)
    uses = {}
    for i, line in enumerate(lines):
        if line.startswith('REGISTER '):
            continue
        for q in set(map(int, Q.findall(line))):
            if q >= 22:
                uses.setdefault(q, []).append(i)
    gaps = [dict(q=q, lo=lo+1, hi=hi, peak_coverage=prefix[hi]-prefix[lo+2])
            for q, seq in uses.items() for lo, hi in zip(seq, seq[1:])
            if hi > lo+2 and prefix[hi] > prefix[lo+2]]
    points = {g[k] for g in gaps for k in ('lo', 'hi')}
    saved, alg = snapshots(lines, points)
    solve = recipe_solver(alg)
    feasible = []
    for g in gaps:
        q = g['q']
        before, depth = saved[g['lo']]
        after, end_depth = saved[g['hi']]
        target = before[q]
        if depth or end_depth or not target or after[q] != target:
            continue
        erase = solve(target, before, q, mode == 'quadratic')
        restore = solve(target, after, q, mode == 'quadratic')
        if erase is not None and restore is not None:
            feasible.append(dict(**g, erase=erase, restore=restore,
                                 extra_toffoli=sum(len(t) == 2 for t in restore)))
    return dict(mode=mode, original_qubits=packing['packed_qubits'],
                original_peak_operations=sum(peak), gaps_tested=len(gaps),
                feasible_intervals=feasible, selected=select_disjoint(feasible))


def restore_lines(q, terms):
    return [('X' if not t else 'CX' if len(t) == 1 else 'CCX') +
            ' ' + ' '.join(f'q{v}' for v in [*t, q]) for t in terms]


def erase_lines(q, terms, bit):
    if all(len(t) < 2 for t in terms):
        return restore_lines(q, terms), False
    result = [f'HMR q{q} b{bit}']
    for t in terms:
        op = 'NEG' if not t else 'Z' if len(t) == 1 else 'CZ'
        result.append(op + (' ' + ' '.join(f'q{v}' for v in t) if t else '') + f' if b{bit}')
    return result, True


def transform(text, selected):
    lines = text.splitlines()
    for previous, current in zip(selected, selected[1:]):
        if previous['hi'] >= current['lo']:
            raise ValueError('Spills overlap or share a boundary')
    saved, alg = snapshots(lines, {g[k] for g in selected for k in ('lo', 'hi')})
    def evaluate(terms, state, q):
        result = ZERO
        for term in terms:
            if len(term) > 2 or q in term or len(set(term)) != len(term):
                raise ValueError('Invalid or self-dependent term')
            value = ONE
            for wire in term:
                value = alg.mul(value, state[wire])
            result = alg.xor(result, value)
        return result
    insertions = {}
    bit = 1 + max((int(b) for b in re.findall(r'\bb(\d+)\b', text)), default=-1)
    measurements = 0
    for g in selected:
        q, lo, hi = g['q'], g['lo'], g['hi']
        if q < 22 or not 0 <= lo < hi < len(lines):
            raise ValueError('Invalid spill interval')
        if any(q in map(int, Q.findall(line)) for line in lines[lo:hi]):
            raise ValueError('Cache used inside spill gap')
        before, d = saved[lo]
        after, ed = saved[hi]
        if d or ed or not before[q] or before[q] != after[q]:
            raise ValueError('Uncertified interval context')
        if evaluate(g['erase'], before, q) != before[q] or evaluate(g['restore'], after, q) != after[q]:
            raise ValueError('Recipe does not prove both boundary values')
        erase, measured = erase_lines(q, g['erase'], bit)
        insertions[lo] = erase
        insertions[hi] = restore_lines(q, g['restore'])
        bit += int(measured)
        measurements += int(measured)
    out = []
    for i, line in enumerate(lines):
        out.extend(insertions.get(i, []))
        out.append(line)
    return '\n'.join(out)+'\n', measurements


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--expected-parent-sha256', required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--mode', choices=['linear', 'quadratic'], required=True)
    a = p.parse_args()
    started = time.monotonic()
    parent = a.parent_output/'invsqrt.kmb'
    if sha256(parent) != a.expected_parent_sha256:
        raise ValueError('Pinned parent changed')
    sys.path.insert(0, str(ROOT/'kickmix'))
    import kickmix as km
    candidate = a.output_dir.parent
    work = candidate/'screen'
    work.mkdir(exist_ok=True)
    km.Circuit.from_file(parent).to_file(work/'parent.kmx')
    text = (work/'parent.kmx').read_text()
    result = screen(text, a.mode)
    changed, measurements = transform(text, result['selected'])
    packed, packing = pack_proven(changed)
    (work/'spilled.kmx').write_text(changed)
    (work/'packed.kmx').write_text(packed)
    (work/'plan.json').write_text(json.dumps(result, indent=2)+'\n')
    (work/'packing.json').write_text(json.dumps(packing, indent=2)+'\n')
    with output_workspace(a.output_dir) as (output, stage):
        circuit = km.Circuit.from_file(work/'packed.kmx')
        circuit.to_file(stage/'invsqrt.kmb', format='kmb')
    for name in ('invsqrt_cache_spill.py', 'invsqrt_clean_lifetimes.py', 'invsqrt_reset_lifetimes.py', 'generate.py'):
        shutil.copy2(Path(__file__).with_name(name), candidate/'code'/name)
    report = dict(kind='exact_idle_cache_rematerialization', official_validation=False,
                  argv=sys.argv, python=sys.executable, prefix=sys.prefix,
                  parent_sha256=sha256(parent), parent_output=str(a.parent_output.resolve()),
                  source_generator_available=False, mode=a.mode,
                  feasible_intervals=len(result['feasible_intervals']), selected_intervals=len(result['selected']),
                  selected=result['selected'], added_measurements=measurements,
                  extra_toffoli=sum(g['extra_toffoli'] for g in result['selected']),
                  original_qubits=result['original_qubits'], packed_qubits=circuit.num_qubits,
                  source_hashes={f.name:sha256(f) for f in (candidate/'code').glob('*.py')},
                  artifacts=[dict(path='invsqrt.kmb', sha256=sha256(output/'invsqrt.kmb'))],
                  seconds=time.monotonic()-started)
    (candidate/'generation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'selected'}))


if __name__ == '__main__':
    main()
