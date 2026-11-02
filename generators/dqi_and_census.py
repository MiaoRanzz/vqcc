# SPDX-License-Identifier: Apache-2.0
"""Exact ANF census of bounded maximal unconditional CCX runs in a pinned KMB.

A positive site changes exactly one target by one input monomial, while restoring
all dirty borrowing wires for every input. This local proof does NOT prove the
target or any spare clean at entry. No circuit is rewritten by this screen.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import time
import numpy as np
from dqi_boolean_reduce import read_binary
from generate import sha256


def multiply(a,b,cap):
    out=set()
    for x in a:
        for y in b:
            z=x|y
            if z in out:out.remove(z)
            else:out.add(z)
            if len(out)>cap:raise OverflowError('ANF term budget')
    return out


def classify(gates,cap=4096):
    wires=sorted(set(q for gate in gates for q in gate));ids={q:i for i,q in enumerate(wires)}
    state={q:{1<<ids[q]} for q in wires}
    try:
        for a,b,t in gates:
            if len({a,b,t})!=3:raise ValueError('Aliased CCX')
            state[t] ^= multiply(state[a],state[b],cap)
            if len(state[t])>cap:raise OverflowError('ANF term budget')
    except OverflowError:return dict(decision='term_budget_exceeded')
    changes={q:p^{1<<ids[q]} for q,p in state.items() if p!={1<<ids[q]}}
    if len(changes)!=1:return dict(decision='not_single_target',changed_wires=len(changes))
    t,delta=next(iter(changes.items()))
    if len(delta)!=1:return dict(decision='not_monomial',terms=len(delta))
    monomial=next(iter(delta));controls=[q for q,i in ids.items() if monomial>>i&1]
    if t in controls:return dict(decision='target_dependent_delta')
    return dict(decision='exact_and',target=t,controls=controls,degree=len(controls),
                borrowed=[q for q in wires if q!=t and q not in controls],ccx=len(gates))


def census(path,max_run=80,seconds=90):
    start=time.monotonic();d=read_binary(path);p=d['packets'];types=p['types']
    # Track the enclosing classical stack: an opcode without an explicit guard
    # is still conditional inside PUSH/POP. Changes occur only at those opcodes.
    stack_pos=np.flatnonzero((types==0x81)|(types==1))
    stack_depth=np.cumsum(np.where(types[stack_pos]==0x81,1,-1))
    if np.any(stack_depth<0) or (len(stack_depth) and stack_depth[-1]):raise ValueError('Invalid stack')
    mask=types==0x31
    edges=np.diff(np.r_[False,mask,False].astype(np.int8))
    starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
    lengths=ends-starts; histogram=dict(Counter(map(int,lengths)))
    selected=np.flatnonzero((lengths>=4)&(lengths<=max_run))
    triple_pos=np.flatnonzero((types&0x30)==0x30)
    rows=[];guarded=0
    for k in selected:
        if time.monotonic()-start>seconds:break
        lo,hi=int(starts[k]),int(ends[k]);j=np.searchsorted(stack_pos,lo,side='right')-1
        if j>=0 and stack_depth[j]:guarded+=1;continue
        offset=int(np.searchsorted(triple_pos,lo));gates=list(zip(*(p[n][offset:offset+hi-lo].tolist() for n in ('a3','b3','t3'))))
        rows.append(dict(start=lo,end=hi,**classify(gates)))
    else:
        return dict(status='complete_in_bounded_run_family',qubits=d['nq'],operations=len(types),
                    run_length_histogram=histogram,max_run=max_run,eligible_runs=len(selected),
                    guarded_runs=guarded,decisions=dict(Counter(r['decision'] for r in rows)),
                    sites=[r for r in rows if r['decision']=='exact_and'],elapsed_seconds=time.monotonic()-start)
    return dict(status='deadline_partial',decisions=dict(Counter(r['decision'] for r in rows)),
                sites=[r for r in rows if r['decision']=='exact_and'],elapsed_seconds=time.monotonic()-start)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifact',type=Path,required=True);p.add_argument('--expected-sha256',required=True)
    p.add_argument('--candidate-dir',type=Path,required=True);p.add_argument('--max-run',type=int,default=80)
    p.add_argument('--seconds',type=float,default=90);a=p.parse_args()
    if sha256(a.artifact)!=a.expected_sha256:raise ValueError('Pinned parent changed')
    r=census(a.artifact,a.max_run,a.seconds)
    r.update(kind='exact_contiguous_and_census',official_validation=False,parent_sha256=a.expected_sha256,
             artifact=str(a.artifact.resolve()),argv=sys.argv,python=sys.executable,prefix=sys.prefix,source_hashes={})
    for name in ('dqi_and_census.py','dqi_boolean_reduce.py','generate.py'):
        src=Path(__file__).with_name(name);shutil.copy2(src,a.candidate_dir/'code'/name);r['source_hashes'][name]=sha256(src)
    (a.candidate_dir/'generation.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('status','decisions','elapsed_seconds')}));print('site degrees',dict(Counter(x['degree'] for x in r['sites'])))

if __name__=='__main__':main()
