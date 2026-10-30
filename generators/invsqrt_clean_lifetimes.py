"""Sound, deliberately incomplete clean-state lifetime proofs for InvSqrt.

Track XOR expressions over interned nonlinear atoms, with Boolean identities
x*x=x and x*(1+x)=0. Large expressions and conditional writes become fresh
unconstrained atoms (an overapproximation, never sampled evidence). Diagonal
operations leave values unchanged. HMR randomness is retained verbatim; only
unconditional resets and algebraically proven zero states release a wire.
This pass preserves gate order and all non-redundant operations. It does not
infer identities from legal-input samples or any particular measurement seed.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import heapq
import json
from pathlib import Path
import re
import shutil
import sys
import time

from invsqrt_reset_lifetimes import ALLOWED, Q

ZERO = frozenset()
ONE = frozenset({0})


class Algebra:
    def __init__(self, term_limit=2048):
        self.next_atom = 1
        self.products = {}
        self.term_limit = term_limit
        self.overflows = 0

    def fresh(self):
        atom = self.next_atom
        self.next_atom += 1
        return frozenset({atom})

    def xor(self, a, b):
        c = a ^ b
        if len(c) > self.term_limit:
            self.overflows += 1
            return self.fresh()
        return c

    def mul(self, a, b):
        if not a or not b:
            return ZERO
        if a == ONE or a == b:
            return b
        if b == ONE:
            return a
        if a ^ b == ONE:
            return ZERO
        key = tuple(sorted((a, b), key=lambda x: tuple(sorted(x))))
        if key not in self.products:
            self.products[key] = self.fresh()
        return self.products[key]


def pack_proven(text, term_limit=2048):
    lines = text.splitlines()
    fixed = {int(q) for line in lines if line.startswith('APPEND_TO_REGISTER ') for q in Q.findall(line)}
    if fixed != set(range(22)):
        raise ValueError('Expected exactly the 22 fixed input qubits')
    alg = Algebra(term_limit)
    state = {q: alg.fresh() for q in sorted(fixed)}
    active, intervals, uses_by_line = {}, [], []
    depth = 0
    omitted, proofs = [], []
    for index, line in enumerate(lines):
        f = line.split()
        if not f:
            uses_by_line.append({})
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
                raise ValueError('Quantum block controls are unsupported')
            depth += 1
        elif op == 'POP_CONDITION':
            depth -= 1
            if depth < 0:
                raise ValueError('Unbalanced conditions')
        # A reset of a proven zero has no effect, including on phase/random bits.
        if op == 'R' and len(qs) == 1 and state[qs[0]] == ZERO:
            omitted.append(index)
            uses_by_line.append({})
            continue
        uses = {}
        for q in sorted(set(qs) - fixed):
            if q not in active:
                active[q] = len(intervals)
                intervals.append(dict(logical=q, start=index, end=len(lines), proof=None))
            uses[q] = active[q]
        uses_by_line.append(uses)
        if op in ('X', 'CX', 'CCX'):
            delta = ONE
            for q in qs[:-1]:
                delta = alg.mul(delta, state[q])
            if delta:
                target = qs[-1]
                state[target] = alg.fresh() if cond else alg.xor(state[target], delta)
        elif op in ('SWAP', 'CSWAP'):
            a, b = qs[-2:]
            if state[a] != state[b]:
                control = state[qs[0]] if op == 'CSWAP' else ONE
                if control:
                    if cond:
                        state[a], state[b] = alg.fresh(), alg.fresh()
                    else:
                        delta = alg.mul(control, alg.xor(state[a], state[b]))
                        state[a], state[b] = alg.xor(state[a], delta), alg.xor(state[b], delta)
        elif op in ('R', 'HMR'):
            if len(qs) != 1:
                raise ValueError('Expected one reset target')
            q = qs[0]
            state[q] = alg.fresh() if cond and state[q] else ZERO
        elif op in ('APPEND_TO_REGISTER', 'REGISTER', 'Z', 'CZ', 'CCZ', 'Z_POW',
                    'NEG', 'BIT_INVERT', 'BIT_STORE0', 'BIT_STORE1',
                    'PUSH_CONDITION', 'POP_CONDITION'):
            pass
        else:
            raise ValueError(f'Unhandled operation {op}')
        for q in sorted(set(qs) - fixed):
            if state[q] == ZERO:
                k = active.pop(q)
                kind = 'unconditional_reset' if op in ('R', 'HMR') and not cond else 'algebraic_zero'
                intervals[k].update(end=index, proof=kind)
                if kind == 'algebraic_zero':
                    proofs.append(dict(line=index, logical=q))
    if depth:
        raise ValueError('Unbalanced conditions')
    free, busy, width, peak = [], [], 22, 0
    peak_ids = []
    for k, item in enumerate(intervals):
        while busy and busy[0][0] < item['start']:
            _, q, _ = heapq.heappop(busy)
            heapq.heappush(free, q)
        if free:
            physical = heapq.heappop(free)
        else:
            physical = width
            width += 1
        item['physical'] = physical
        heapq.heappush(busy, (item['end'], physical, k))
        if len(busy) > peak:
            peak = len(busy)
            peak_ids = [x[2] for x in busy]
    result = []
    omit_set = set(omitted)
    for index, (line, uses) in enumerate(zip(lines, uses_by_line)):
        if index in omit_set:
            continue
        if line.startswith('REGISTER '):
            result.append(line)
            continue
        def replace(match):
            q = int(match[1])
            return f"q{q if q in fixed else intervals[uses[q]]['physical']}"
        result.append(Q.sub(replace, line))
    return '\n'.join(result)+'\n', dict(
        original_qubits=max(state)+1, packed_qubits=width, scratch_interval_peak=peak,
        interval_count=len(intervals), intervals=intervals, algebraic_zero_proofs=proofs,
        omitted_zero_resets=omitted, opaque_product_count=len(alg.products),
        expression_overflows=alg.overflows, term_limit=term_limit, peak_interval_ids=peak_ids,
        original_operations=dict(Counter(line.split()[0] for line in lines if line.strip())))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--term-limit', type=int, default=2048)
    args = p.parse_args()
    from generate import ROOT, output_workspace, sha256
    sys.path.insert(0, str(ROOT/'kickmix'))
    import kickmix as km
    start = time.monotonic()
    candidate = args.output_dir.resolve().parent
    screen = candidate/'screen'; screen.mkdir(exist_ok=True)
    parent = args.parent_output/'invsqrt.kmb'
    circ = km.Circuit.from_file(parent); circ.to_file(screen/'parent.kmx')
    text, analysis = pack_proven((screen/'parent.kmx').read_text(), args.term_limit)
    (screen/'packed.kmx').write_text(text)
    (screen/'proofs.json').write_text(json.dumps(analysis, indent=2)+'\n')
    packed = km.Circuit.from_file(screen/'packed.kmx')
    if packed.num_qubits != analysis['packed_qubits']:
        raise AssertionError('Parsed width differs from interval model')
    with output_workspace(args.output_dir) as (output, stage):
        packed.to_file(stage/'invsqrt.kmb')
    code = candidate/'code'; code.mkdir(exist_ok=True)
    for name in ('invsqrt_clean_lifetimes.py', 'invsqrt_reset_lifetimes.py'):
        shutil.copy2(Path(__file__).with_name(name), code/name)
    report = dict(kind='symbolic_clean_state_lifetime_packing', official_validation=False,
        parent_output=str(args.parent_output.resolve()), parent_sha256=sha256(parent),
        generator_sha256=sha256(Path(__file__)), argv=sys.argv,
        python_executable=sys.executable, python_prefix=sys.prefix,
        created_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-start,
        screen={k:v for k,v in analysis.items() if k not in ('intervals','algebraic_zero_proofs','omitted_zero_resets')},
        zero_proofs=len(analysis['algebraic_zero_proofs']), omitted_resets=len(analysis['omitted_zero_resets']),
        artifacts=[dict(path='invsqrt.kmb',sha256=sha256(output/'invsqrt.kmb'))],
        decision='plausible_width_gain' if packed.num_qubits < circ.num_qubits else 'screened_out_no_width_gain')
    (candidate/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__': main()
