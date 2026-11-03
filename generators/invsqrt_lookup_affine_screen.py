# SPDX-License-Identifier: Apache-2.0
"""Check every pure-lookup CCX against the exact affine live-value span.

All 256 assignments to the eight high input wires are represented exactly.
Other wires are unknown until explicitly reset. A target-dependent correction
is excluded. An empty result rules out this one-gate affine substitution family,
not broader nonlinear resynthesis or changed arithmetic.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
from generate import ROOT, sha256
from invsqrt_lookup_resynth import INPUTS, ALL, Q, step, solve_columns


def screen(lines):
    start=lines.index('R q22',240)
    end=lines.index('HMR q24 b12600',start)
    state={q:None for q in range(62)};state.update(INPUTS)
    rows=[];tested=0
    for i in range(start,end):
        line=lines[i]
        if line.startswith('CCX '):
            tested+=1;a,b,t=map(int,Q.findall(line))
            if state[a] is None or state[b] is None:
                raise ValueError('Unproved lookup input')
            available=[(q,v) for q,v in sorted(state.items()) if q!=t and v is not None]
            columns=[ALL]+[v for _,v in available]
            delta=state[a]&state[b]
            mask=solve_columns(columns,delta)
            if mask is not None:
                constant=bool(mask&1);controls=[q for j,(q,_) in enumerate(available,1) if mask>>j&1]
                actual=ALL if constant else 0
                for q in controls:actual^=state[q]
                assert actual==delta
                rows.append(dict(index=i,instruction=line,target=t,constant=constant,controls=controls))
        step(state,line)
    return dict(bounds=[start,end],ccx_tested=tested,exact_replacements=rows,
                outside_affine_live_span=tested-len(rows),assignments=256)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifact',type=Path,required=True)
    p.add_argument('--expected-sha256',required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();started=time.monotonic()
    if sha256(a.artifact)!=a.expected_sha256:raise ValueError('Pinned parent changed')
    sys.path.insert(0,str(ROOT/'kickmix'));import kickmix as km
    circuit=km.Circuit.from_file(a.artifact)
    if circuit.num_qubits!=62:raise ValueError('Requires the pinned 62-qubit architecture')
    r=screen(str(circuit).splitlines())
    r.update(kind='complete256row_single_product_affine_live_span',official_validation=False,
             artifact=str(a.artifact.resolve()),artifact_sha256=a.expected_sha256,
             argv=sys.argv,python_executable=sys.executable,python_prefix=sys.prefix,
             source_hashes={name:sha256(Path(__file__).with_name(name)) for name in
                            ['invsqrt_lookup_affine_screen.py','invsqrt_lookup_resynth.py']},
             scope='Each CCX separately, all256lookup inputs, reset-established workspace, affine corrections from current wires excluding its target. No global lower bound.',
             elapsed_seconds=time.monotonic()-started)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))


if __name__=='__main__':main()
