# SPDX-License-Identifier: Apache-2.0
"""Census deferred three-to-two AND rewrites across an HMR boundary.

Treat every incoming wire as independent. Track affine controls and use the
alternating quadratic rank of F1+F2+G to screen one-AND synthesis. Only consider
three consecutive unconditional CCX, first two accumulating into the same unread
wire and the third targeting a wire reset between them. This is a bounded local
family, not a bound on all measurement-assisted circuits.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import sys
import time
from invsqrt_lookup_resynth import solve_columns, product_gates
from invsqrt_cone_bounds import rank

Q = re.compile(r'\bq(\d+)\b')


def affine_product(a, b, n):
    """Return multilinear ANF as monomial bit masks; zero is the constant."""
    def terms(x):
        return [1 << i for i in range(n) if x >> i & 1] + ([0] if x >> n & 1 else [])
    out = set()
    for x in terms(a):
        for y in terms(b):
            term = x | y
            if term in out: out.remove(term)
            else: out.add(term)
    return out


def factor_one(poly, n):
    rows = [0] * n
    linear = 0
    for term in poly:
        degree = term.bit_count()
        if degree < 2:
            linear ^= term if term else 1 << n
        elif degree == 2:
            i = (term & -term).bit_length()-1
            j = (term ^ (1 << i)).bit_length()-1
            rows[i] ^= 1 << j; rows[j] ^= 1 << i
        else:
            raise ValueError('Nonquadratic polynomial')
    r = rank(rows)
    if r == 0: return dict(rank=r, a=0, b=0, linear=linear)
    if r != 2: return dict(rank=r)
    i = next(i for i, row in enumerate(rows) if row)
    j = (rows[i] & -rows[i]).bit_length()-1
    a, b = rows[j], rows[i]
    correction = linear ^ (a & b)
    check = affine_product(a, b, n)
    check ^= {1 << k for k in range(n) if correction >> k & 1}
    if correction >> n & 1: check ^= {0}
    assert check == poly
    return dict(rank=r, a=a, b=b, linear=correction)


def inspect_window(lines, positions, n, require_reset=True):
    lo, mid, hi = positions
    gates = [list(map(int, Q.findall(lines[i]))) for i in positions]
    acc = gates[0][-1]; target = gates[-1][-1]
    result = dict(positions=positions, accumulator=acc, reset_target=target)
    if gates[1][-1] != acc or target == acc:
        return dict(result, decision='target_pattern_mismatch')
    # A shared enclosing classical condition is harmless, but changing it inside
    # the rewrite region is not. Individual nonlinear conditions are excluded.
    if any('if' in lines[i].split() for i in positions):
        return dict(result, decision='conditional_product')
    state = [1 << q for q in range(n)]
    products = []; insertion = None; resets = []
    for i in range(lo, hi+1):
        line = lines[i]; f = line.split(); op = f[0]
        qs = list(map(int, Q.findall(line)))
        if i in positions:
            a,b,t = qs
            if acc in (a,b): return dict(result, decision='accumulator_read')
            products.append(affine_product(state[a], state[b], n))
            # Ignore nonlinear accumulator changes until final synthesis.
            if i == mid: insertion = state.copy()
            continue
        if op in ('PUSH_CONDITION','POP_CONDITION'):
            return dict(result, decision='control_flow_boundary')
        if acc in qs and not (op in ('X','CX') and qs[-1] == acc and 'if' not in f):
            return dict(result, decision='accumulator_read_or_reset', blocker=i)
        if op in ('Z','CZ','CCZ','Z_POW','NEG','BIT_INVERT','BIT_STORE0','BIT_STORE1'):
            continue  # Diagonal/classical operations retained byte-for-byte.
        if 'if' in f:
            return dict(result, decision='conditional_value_operation', blocker=i)
        if op == 'X': state[qs[0]] ^= 1 << n
        elif op == 'CX':
            if qs[0] == acc: return dict(result, decision='accumulator_read', blocker=i)
            state[qs[1]] ^= state[qs[0]]
        elif op == 'SWAP': state[qs[0]],state[qs[1]] = state[qs[1]],state[qs[0]]
        elif op in ('R','HMR'):
            if i < mid: return dict(result, decision='early_reset')
            state[qs[0]] = 0
            if qs[0] == target: resets.append(i)
        else: return dict(result, decision='unsupported_operation', blocker=i, operation=op)
    if require_reset and not resets: return dict(result, decision='no_target_reset')
    total = products[0] ^ products[1] ^ products[2]
    factor = factor_one(total, n)
    result.update(factor=factor, resets=resets, product_anf=[sorted(p) for p in products])
    if factor['rank'] > 2:
        return dict(result, decision='rank_exceeds_one_product')
    available = [q for q in range(n) if q != acc]
    columns = [insertion[q] for q in available] + [1 << n]
    masks = [solve_columns(columns, factor[k]) for k in ('a','b','linear')]
    if any(m is None for m in masks):
        return dict(result, decision='controls_unavailable_at_insertion')
    a,b,linear = masks; d = len(available); constant = 1 << d
    # Normalize affine factors into nonconstant products plus linear terms.
    if a & constant: linear ^= b & (constant-1)
    if b & constant: linear ^= a & (constant-1)
    if a & b & constant: linear ^= constant
    a &= constant-1; b &= constant-1
    if a == b: linear ^= a; a = b = 0
    extra = product_gates(a,b,available,acc) if a and b else []
    if linear & constant: extra.append(f'X q{acc}')
    extra.extend(f'CX q{q} q{acc}' for k,q in enumerate(available) if linear >> k & 1)
    result.update(decision='constructive_candidate_requires_phase_certificate', replacement_product=extra,
                  saved_ccx=2-sum(x.startswith('CCX ') for x in extra))
    return result


def census(lines, n=62, max_span=100, require_reset=True):
    positions = [i for i,l in enumerate(lines) if l.startswith('CCX ')]
    rows = []
    for triple in zip(positions, positions[1:], positions[2:]):
        if triple[-1]-triple[0] > max_span: continue
        gates = [Q.findall(lines[i]) for i in triple]
        if gates[0][-1] != gates[1][-1] or gates[2][-1] == gates[0][-1]: continue
        rows.append(inspect_window(lines,list(triple),n,require_reset))
    return dict(ccx_total=len(positions), max_span=max_span, require_reset=require_reset, tested_windows=len(rows),
                decisions=dict(Counter(r['decision'] for r in rows)), windows=rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--candidate-dir',type=Path,required=True)
    p.add_argument('--expected-parent-sha256',required=True)
    p.add_argument('--max-span',type=int,default=100)
    p.add_argument('--allow-live-target',action='store_true',help='Also test delta-copy into an unreset target')
    args=p.parse_args();start=time.monotonic()
    from generate import ROOT,sha256
    sys.path.insert(0,str(ROOT/'kickmix'));import kickmix as km
    source=args.parent_output/'invsqrt.kmb'
    if sha256(source)!=args.expected_parent_sha256:raise ValueError('Pinned parent changed')
    screen=args.candidate_dir/'screen';screen.mkdir(exist_ok=True)
    circuit=km.Circuit.from_file(source);circuit.to_file(screen/'parent.kmx')
    result=census((screen/'parent.kmx').read_text().splitlines(),circuit.num_qubits,args.max_span,not args.allow_live_target)
    result.update(kind='reset_crossing_deferred_product_census',official_validation=False,
        argv=sys.argv,parent_sha256=sha256(source),parent_output=str(args.parent_output.resolve()),
        python_executable=sys.executable,python_prefix=sys.prefix,source_hashes={},
        elapsed_seconds=time.monotonic()-start)
    for name in ('invsqrt_deferred_products.py','invsqrt_lookup_resynth.py','invsqrt_cone_bounds.py','invsqrt_joint_outputs.py','generate.py'):
        src=Path(__file__).with_name(name);shutil.copy2(src,args.candidate_dir/'code'/name)
        result['source_hashes'][name]=sha256(src)
    (args.candidate_dir/'generation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('tested_windows','decisions','elapsed_seconds')}))

if __name__=='__main__':main()
