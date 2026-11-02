# SPDX-License-Identifier: Apache-2.0
"""Exact legal-input value certificates for the deterministic InvSqrt prefix.

Each Python integer stores the complete truth table over 1..max_x, not samples.
Before classical value control, X/CX/CCX/SWAP/CSWAP preserve basis values and
HMR resets its target to zero in every measurement branch. Diagonal operations
preserve values. Stop before a condition block or conditional value operation.
The original phase and measurement instructions are never removed by packing.
"""
from __future__ import annotations
import argparse
from fractions import Fraction
import json
from pathlib import Path
import re
import shutil
import sys
import time
import numpy as np
from invsqrt_clean_lifetimes import pack_proven
from generate import ROOT, sha256, output_workspace

Q = re.compile(r'q(\d+)\Z')
DIAGONAL = {'Z', 'CZ', 'CCZ', 'Z_POW', 'NEG'}
PASSIVE = {'APPEND_TO_REGISTER', 'REGISTER', 'BIT_INVERT', 'BIT_STORE0', 'BIT_STORE1'}
VALUE = {'X', 'CX', 'CCX', 'SWAP', 'CSWAP', 'R', 'HMR'}


def truth_inputs(width, max_x):
    if not 1 <= max_x < 1 << width:
        raise ValueError('Invalid exhaustive input range')
    xs = np.arange(1, max_x+1, dtype=np.uint32)
    return {q: int.from_bytes(np.packbits(((xs >> q) & 1).astype(np.uint8),
                    bitorder='little').tobytes(), 'little') for q in range(width)}


def unpack(value, count):
    return np.unpackbits(np.frombuffer(value.to_bytes((count+7)//8, 'little'),
                         dtype=np.uint8), bitorder='little')[:count]


def propagate(op, qs, state, one):
    if op == 'X': state[qs[0]] ^= one
    elif op == 'CX': state[qs[1]] ^= state[qs[0]]
    elif op == 'CCX': state[qs[2]] ^= state[qs[0]] & state[qs[1]]
    elif op == 'SWAP': state[qs[0]], state[qs[1]] = state[qs[1]], state[qs[0]]
    elif op == 'CSWAP':
        c,a,b = qs; delta = state[c] & (state[a] ^ state[b])
        state[a] ^= delta; state[b] ^= delta
    elif op in ('R','HMR'): state[qs[0]] = 0
    else: raise ValueError(f'Unsupported value operation {op}')


def analyze_prefix(lines, width=22, max_x=3133452, snapshots=(), phases=False):
    state = truth_inputs(width, max_x); one = (1 << max_x)-1
    zeroes = {}; saved = {}; features = []; phase = np.zeros(max_x, dtype=np.uint64) if phases else None
    rotation_rows = []; stop = len(lines)
    for i,line in enumerate(lines):
        f = line.split()
        if not f: continue
        op = f[0]; qs = [int(m[1]) for token in f[1:] if (m := Q.fullmatch(token))]
        if op in ('PUSH_CONDITION','POP_CONDITION') or ('if' in f and op in VALUE):
            stop = i; break
        if op not in VALUE | DIAGONAL | PASSIVE:
            raise ValueError(f'Unsupported operation: {line}')
        for q in qs: state.setdefault(q, 0)
        if i in snapshots: saved[i] = state.copy()
        if op in VALUE:
            if len(set(qs)) != len(qs): raise ValueError('Aliased value operands')
            propagate(op,qs,state,one)
        elif phases and op in DIAGONAL and 'if' not in f:
            value = one
            for q in qs: value &= state[q]
            angle = Fraction(f[2]) if op == 'Z_POW' else Fraction(1)
            n,d = angle.as_integer_ratio()
            units = (((n << 64)//d + 1) >> 1) & ((1 << 64)-1)
            bits = unpack(value,max_x)
            phase += bits.astype(np.uint64)*np.uint64(units)
            if op == 'Z_POW' and angle % Fraction(1,4):
                features.append(bits)
                rotation_rows.append(dict(index=i, instruction=line, half_turns=str(angle)))
        zeroes[i] = [q for q in qs if not state[q]]
    return dict(prefix_end=stop, zero_after=zeroes, snapshots=saved,
                rotation_rows=rotation_rows, features=np.array(features,dtype=np.uint8),phase=phase)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--expected-parent-sha256',required=True)
    a=p.parse_args();began=time.monotonic();parent=a.parent_output/'invsqrt.kmb'
    if sha256(parent)!=a.expected_parent_sha256:raise ValueError('Pinned artifact changed')
    sys.path.insert(0,str(ROOT/'kickmix'));import kickmix as km
    candidate=a.output_dir.parent;screen=candidate/'screen';screen.mkdir(exist_ok=True)
    km.Circuit.from_file(parent).to_file(screen/'parent.kmx')
    text=(screen/'parent.kmx').read_text();analysis=analyze_prefix(text.splitlines())
    packed,proofs=pack_proven(text,certified_zero_after=analysis['zero_after'])
    _,control=pack_proven(text)
    (screen/'packed.kmx').write_text(packed)
    (screen/'packing-proofs.json').write_text(json.dumps(proofs,indent=2)+'\n')
    with output_workspace(a.output_dir) as (output,stage):
        km.Circuit.from_file(screen/'packed.kmx').to_file(stage/'invsqrt.kmb', format='kmb')
    for name in ('invsqrt_reachable.py','invsqrt_clean_lifetimes.py','invsqrt_reset_lifetimes.py','generate.py'):
        shutil.copy2(Path(__file__).with_name(name),candidate/'code'/name)
    report=dict(kind='exhaustive_legal_domain_prefix_lifetime_packing',official_validation=False,
        argv=sys.argv,python=sys.executable,prefix=sys.prefix,parent_output=str(a.parent_output.resolve()),
        parent_sha256=sha256(parent),source_generator_available=False,domain=[1,3133452],
        prefix_end=analysis['prefix_end'],post_operation_zero_certificates=analysis['zero_after'],
        original_qubits=proofs['original_qubits'],packed_qubits=proofs['packed_qubits'],
        symbolic_control_qubits=control['packed_qubits'],zero_events=len(proofs['algebraic_zero_proofs']),
        symbolic_control_zero_events=len(control['algebraic_zero_proofs']),
        source_hashes={f.name:sha256(f) for f in (candidate/'code').glob('*.py')},
        artifacts=[dict(path='invsqrt.kmb',sha256=sha256(output/'invsqrt.kmb'))],
        seconds=time.monotonic()-began)
    (candidate/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='post_operation_zero_certificates'}))


if __name__=='__main__':main()
