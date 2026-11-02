# SPDX-License-Identifier: Apache-2.0
"""Exact value-span bound for a phase-free local reversible window.

All incoming wires are independent, including old targets. Every CCX or CSWAP
adds at most one Boolean function to the affine span. Thus the rank of the
outgoing nonlinear ANFs lower-bounds their count in any measurement-free
X/CX/SWAP/CCX/CSWAP replacement preserving all outgoing values. This does not
bound measurement-assisted rewrites or rewrites exploiting reachable states.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import time


def multiply(a, b):
    result = set()
    for x in a:
        for y in b:
            z = x | y
            if z in result: result.remove(z)
            else: result.add(z)
    return result


def quadratic_rank(poly, n):
    rows = [0]*n
    for monomial in poly:
        if monomial.bit_count() > 2: raise ValueError('Nonquadratic polynomial')
        if monomial.bit_count() == 2:
            low = monomial & -monomial
            i = low.bit_length()-1; j = (monomial ^ low).bit_length()-1
            rows[i] ^= 1 << j; rows[j] ^= 1 << i
    pivots = {}
    for row in rows:
        while row:
            bit = row.bit_length()-1
            if bit in pivots: row ^= pivots[bit]
            else: pivots[bit] = row; break
    return len(pivots)


def tight_span_obstruction(basis, n):
    """Necessary two-product reachability for a rank-tight implementation.

    If k gates achieve an output quotient span of rank k, every intermediate
    product must belong to that same span modulo affine inputs. The first is
    quadratic with alternating rank 2. After its nonlinear part g, any second
    product has the relaxed form L*M + g*N, where L,M,N are affine. We enumerate
    the small final span, solve its degree>2 part in g*affine, and test all
    remaining quadratic residuals. Ignoring the coupling of L,M,N only enlarges
    the feasible set, so failure is a valid obstruction, not a synthesis claim.
    """
    if len(basis) > 10: return dict(status='pending_rank_too_large')
    span = [set()]
    for p in basis: span += [s ^ p for s in span]
    first = [p for p in span[1:] if max(m.bit_count() for m in p) <= 2 and quadratic_rank(p, n) == 2]
    records = []
    for g in first:
        columns = [multiply(g, {1 << i}) for i in range(n)] + [g]
        pivots = {}; kernel = []
        for i, col in enumerate(columns):
            row = {m for m in col if m.bit_count() > 2}; combination = 1 << i
            while row:
                pivot = max(row)
                if pivot in pivots:
                    row ^= pivots[pivot][0]; combination ^= pivots[pivot][1]
                else:
                    pivots[pivot] = (row, combination); break
            if not row: kernel.append(combination)
        if len(kernel) > 10: return dict(status='pending_kernel_too_large')
        trials = []
        for target in span:
            if not target or target == g: continue
            row = {m for m in target if m.bit_count() > 2}; combination = 0
            while row:
                pivot = max(row)
                if pivot not in pivots: break
                row ^= pivots[pivot][0]; combination ^= pivots[pivot][1]
            if row:
                trials.append(dict(target=sorted(target), decision='high_degree_outside_product_span'))
                continue
            solutions = [combination]
            for k in kernel: solutions += [s ^ k for s in solutions]
            ranks = []
            for solution in solutions:
                residual = target.copy()
                for i, col in enumerate(columns):
                    if solution >> i & 1: residual ^= col
                ranks.append(quadratic_rank(residual, n))
            trials.append(dict(target=sorted(target), minimum_quadratic_rank=min(ranks),
                               decision='excluded' if min(ranks) > 2 else 'not_excluded'))
        records.append(dict(first_nonlinear_anf=sorted(g), kernel_dimension=len(kernel), trials=trials))
    blocked = len(basis) >= 2 and all(t['decision'] != 'not_excluded' for r in records for t in r['trials'])
    return dict(status='rank_tight_implementation_excluded' if blocked else 'not_excluded',
                first_product_count=len(first), first_products=records)


def analyze(lines, zero_inputs=()):
    parsed = []
    for line in lines:
        fields = line.split()
        arity = {'X': 1, 'CX': 2, 'SWAP': 2, 'CCX': 3, 'CSWAP': 3}
        if not fields or fields[0] not in arity or len(fields) != arity[fields[0]]+1:
            raise ValueError(f'Window must be unconditional and phase-free: {line}')
        if any(not q.startswith('q') or not q[1:].isdigit() for q in fields[1:]):
            raise ValueError('Invalid qubit operand')
        qs = [int(q[1:]) for q in fields[1:]]
        if len(set(qs)) != len(qs): raise ValueError('Aliased operands')
        parsed.append((fields[0], qs))
    wires = sorted({q for _, qs in parsed for q in qs})
    state = {q: {1 << i} for i, q in enumerate(wires)}
    if not set(zero_inputs) <= set(wires): raise ValueError('Zero input outside window')
    for q in zero_inputs: state[q] = set()
    original = 0
    for op, qs in parsed:
        if op == 'X': state[qs[0]] ^= {0}
        elif op == 'CX': state[qs[1]] ^= state[qs[0]]
        elif op == 'SWAP': state[qs[0]], state[qs[1]] = state[qs[1]], state[qs[0]]
        elif op == 'CCX':
            state[qs[2]] ^= multiply(state[qs[0]], state[qs[1]]); original += 1
        else:
            c, a, b = qs
            delta = multiply(state[c], state[a] ^ state[b])
            state[a] ^= delta; state[b] ^= delta; original += 1
    # Sparse Gaussian elimination over nonlinear monomials, modulo affine inputs.
    pivots = {}
    for q in wires:
        row = {m for m in state[q] if m.bit_count() > 1}
        while row:
            pivot = max(row)
            if pivot in pivots: row ^= pivots[pivot]
            else:
                pivots[pivot] = row
                break
    bound = len(pivots)
    assert bound <= original
    obstruction = tight_span_obstruction(list(pivots.values()), len(wires)) if bound < original else None
    refined = bound + int(bool(obstruction and obstruction['status'] == 'rank_tight_implementation_excluded'))
    assert refined <= original
    return dict(incoming_wires=wires, certified_zero_inputs=list(zero_inputs), original_nonlinear_gates=original,
                nonlinear_span_bound=bound, refined_lower_bound=refined, tight_span_obstruction=obstruction, maximum_saving=original-refined,
                decision='no_saving_in_specified_input_measurement_free_family' if refined == original else 'open_bound_not_tight',
                outgoing_anf={str(q): sorted(state[q]) for q in wires},
                rank_certificate=[sorted(pivots[p]) for p in sorted(pivots)],
                maximum_degree=max((m.bit_count() for poly in state.values() for m in poly), default=0))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--candidate-dir', type=Path, required=True)
    p.add_argument('--expected-parent-sha256', required=True)
    p.add_argument('--certify-reset', type=int, nargs='*', default=[], help='Require each named wire to have an unconditional R/HMR as its last preceding mention')
    p.add_argument('--start', type=int, required=True, help='Zero-based inclusive operation index')
    p.add_argument('--end', type=int, required=True, help='Zero-based exclusive operation index')
    args = p.parse_args(); start = time.monotonic()
    from generate import ROOT, sha256
    sys.path.insert(0, str(ROOT/'kickmix')); import kickmix as km
    source = args.parent_output/'invsqrt.kmb'
    if sha256(source) != args.expected_parent_sha256: raise ValueError('Pinned parent changed')
    screen = args.candidate_dir/'screen'; screen.mkdir(exist_ok=True)
    km.Circuit.from_file(source).to_file(screen/'parent.kmx')
    lines = (screen/'parent.kmx').read_text().splitlines()
    if not 0 <= args.start < args.end <= len(lines): raise ValueError('Invalid interval')
    selected = lines[args.start:args.end]
    reset_certificates = []
    for q in args.certify_reset:
        prior = next((i for i in range(args.start-1, -1, -1) if f'q{q}' in lines[i].split()), None)
        if prior is None: raise ValueError('No preceding reset certificate')
        fields = lines[prior].split()
        if fields[0] not in ('R', 'HMR') or 'if' in fields or fields[1] != f'q{q}':
            raise ValueError('Last preceding mention is not an unconditional reset')
        # A local textual reset inside a classical branch is insufficient.
        depth = 0
        for line in lines[:args.start]:
            if line.split()[0] == 'PUSH_CONDITION': depth += 1
            elif line.split()[0] == 'POP_CONDITION': depth -= 1
            if depth < 0: raise ValueError('Malformed condition nesting')
        if depth or any(line.startswith(('PUSH_CONDITION', 'POP_CONDITION')) for line in lines[prior:args.start]):
            raise ValueError('Conditional reset context is not certified')
        reset_certificates.append(dict(qubit=q, operation_index=prior, instruction=lines[prior]))
    result = analyze(selected, args.certify_reset)
    result['reset_certificates'] = reset_certificates
    if args.certify_reset: result['independent_input_control'] = analyze(selected)
    result.update(kind='exact_local_fanout_span_bound', official_validation=False,
                  interval=[args.start, args.end], instructions=selected,
                  parent_output=str(args.parent_output.resolve()), parent_sha256=sha256(source),
                  source_generator_available=False, argv=sys.argv, python=sys.executable,
                  prefix=sys.prefix, generator_sha256=sha256(Path(__file__)),
                  elapsed_seconds=time.monotonic()-start)
    shutil.copy2(__file__, args.candidate_dir/'code'/Path(__file__).name)
    (args.candidate_dir/'generation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ['decision','original_nonlinear_gates','nonlinear_span_bound','refined_lower_bound','maximum_degree','elapsed_seconds']}))


if __name__ == '__main__': main()
