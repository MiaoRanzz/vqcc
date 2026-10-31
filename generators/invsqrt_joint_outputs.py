"""Exact adjacent-output XOR-basis search on the pinned 62-qubit InvSqrt LUT.

Use CNOT conjugation to implement (f,g) as (f,f^g) or (f^g,g), with
no new wires. All controls must be available in a common final affine basis
excluding both targets. Exhaustive 256-row equality is checked before synthesis.
Finite factor-pool exhaustion is scoped; timeouts are not impossibility proofs.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time
from bisect import bisect_right
from functools import reduce
from operator import xor
from invsqrt_lookup_resynth import (ALL, INPUTS, Q, step, linear_basis,
                                   solve_columns, solve_fixed_factors, product_gates)


def normalized_representation(mask, factors, dimension):
    linear=mask&((1<<(dimension+1))-1);terms=set();low=(1<<dimension)-1
    for i,(a,b) in enumerate(factors):
        if not (mask>>(dimension+1+i))&1:continue
        ac,bc=a>>dimension,b>>dimension;a&=low;b&=low
        if ac:linear^=b
        if bc:linear^=a
        if ac and bc:linear^=1<<dimension
        if not a or not b:continue
        if a==b:linear^=a;continue
        term=tuple(sorted((a,b)))
        if term in terms:terms.remove(term)
        else:terms.add(term)
    return dict(coefficients=[list(x) for x in sorted(terms)],linear=linear,products=len(terms))


def evaluate(rep,basis):
    columns=[v for _,v in basis]+[ALL]
    value=reduce(xor,(v for j,v in enumerate(columns) if rep['linear']>>j&1),0)
    for a,b in rep['coefficients']:
        av=reduce(xor,(v for j,(_,v) in enumerate(basis) if a>>j&1),0)
        bv=reduce(xor,(v for j,(_,v) in enumerate(basis) if b>>j&1),0)
        value^=av&bv
    return value


def extract_windows(lines,complete_affine_tail=False):
    start=lines.index('R q22',240);end=lines.index('HMR q24 b12600',start)
    groups=[]
    for i in range(start,end):
        if not lines[i].startswith('CCX '):continue
        target=int(Q.findall(lines[i])[-1])
        if not groups or groups[-1]['target']!=target:groups.append(dict(target=target,indices=[]))
        groups[-1]['indices'].append(i)
    starts={g['indices'][0] for g in groups};ends={g['indices'][-1]+1 for g in groups}
    state={q:None for q in range(62)};state.update(INPUTS);snapshots={};controls={}
    for i in range(start,end):
        if complete_affine_tail or i in starts:snapshots[i]=state.copy()
        if lines[i].startswith('CCX '):
            a,b,_=map(int,Q.findall(lines[i]));controls[i]=(state[a],state[b])
        step(state,lines[i])
        if complete_affine_tail or i+1 in ends:snapshots[i+1]=state.copy()
    windows=[];rejected=[]
    for group_index,(left,right) in enumerate(zip(groups,groups[1:])):
        lo,hi=left['indices'][0],right['indices'][-1]+1;targets=[left['target'],right['target']]
        neutral=snapshots[lo].copy();expected=snapshots[hi]
        try:
            for line in lines[lo:hi]:step(neutral,line,skip_ccx=True)
        except ValueError as exc:
            rejected.append(dict(start=lo,end=hi,reason=str(exc)));continue
        if complete_affine_tail:
            limit=groups[group_index+2]['indices'][0] if group_index+2<len(groups) else end
            # Finish the existing affine uncomputation before judging whether
            # nonlinear effects escape. Never cross the next nonlinear gate.
            while hi<limit and any(neutral[q]!=expected[q] for q in state if q not in targets):
                try:step(neutral,lines[hi],skip_ccx=True)
                except ValueError:break
                hi+=1;expected=snapshots[hi]
        if any(neutral[q]!=expected[q] for q in state if q not in targets):
            rejected.append(dict(start=lo,end=hi,reason='nonlinear values escape into other live wires'));continue
        basis=linear_basis({q:v for q,v in neutral.items() if q not in targets},-1)
        base=[v for _,v in basis]+[ALL];d=len(basis)
        control_tables=[controls[i] for i in left['indices']+right['indices']]
        factors=[tuple(solve_columns(base,v) for v in pair) for pair in control_tables]
        if any(None in pair for pair in factors):
            rejected.append(dict(start=lo,end=hi,reason='original controls unavailable without targets'));continue
        columns=base+[a&b for a,b in control_tables]
        deltas=[neutral[t]^expected[t] for t in targets]
        reps=[]
        for delta in deltas:
            mask=solve_columns(columns,delta)
            if mask is None:break
            rep=normalized_representation(mask,factors,d)
            assert evaluate(rep,basis)==delta
            reps.append(rep)
        if len(reps)!=2:
            rejected.append(dict(start=lo,end=hi,reason='delta outside original product span'));continue
        windows.append(dict(start=lo,end=hi,targets=targets,original_count=len(control_tables),
            basis=basis,neutral=neutral,expected=expected,deltas=deltas,representations=reps,
            control_tables=control_tables))
    return windows,dict(start=start,end=end,groups=len(groups),windows_considered=len(groups)-1,
                        eligible_windows=len(windows),rejected=rejected)


def solve_window(job):
    window,seconds,order=job;start=time.monotonic();w=window
    baseline=w['original_count'];reps=w['representations']
    direct=sum(x['products'] for x in reps)
    result=dict(start=w['start'],end=w['end'],targets=w['targets'],original_count=baseline,
                basis_dimension=len(w['basis']),direct_products=direct,trials=[])
    if direct<baseline:
        result.update(status='improved',products=direct,mode='direct',representations=reps)
    else:result.update(status='no_improvement',products=baseline)
    # The two choices have the same h=f^g search, so use the cheaper exact
    # retained output representation. Tie-break by the first output, not hash.
    keep=min(range(2),key=lambda j:reps[j]['products'])
    bound=min(baseline,result['products'])-reps[keep]['products']-1
    if bound>=0:
        target=dict(w,delta=w['deltas'][0]^w['deltas'][1],target=-1)
        row=solve_fixed_factors((target,bound,int(seconds*1000),{'factor_xor_order':order}))
        result['trials'].append(row)
        if row['status']=='sat':
            assert evaluate(row,w['basis'])==target['delta']
            total=reps[keep]['products']+row['products']
            if total<result['products']:
                result.update(status='improved',products=total,mode='xor',keep=keep,
                              representations=[reps[keep],{k:row[k] for k in ('coefficients','linear','products')}])
        elif row['status']=='unknown' and result['status']!='improved':result['status']='unknown'
    result['elapsed_seconds']=time.monotonic()-start
    return result


def gates_for(rep,basis,target):
    qs=[q for q,_ in basis];gates=[]
    for a,b in rep['coefficients']:gates+=product_gates(a,b,qs,target)
    if rep['linear']>>len(qs)&1:gates.append(f'X q{target}')
    gates += [f'CX q{q} q{target}' for j,q in enumerate(qs) if rep['linear']>>j&1]
    return gates


def replacement(lines,window,result):
    w=window;retained=[line for line in lines[w['start']:w['end']] if not line.startswith('CCX ')]
    t0,t1=w['targets'];basis=w['basis'];reps=result['representations']
    if result['mode']=='direct':extra=gates_for(reps[0],basis,t0)+gates_for(reps[1],basis,t1)
    else:
        a,b=(t0,t1) if result['keep']==0 else (t1,t0)
        extra=[f'CX q{a} q{b}']+gates_for(reps[0],basis,a)+[f'CX q{a} q{b}']+gates_for(reps[1],basis,b)
    state=w['neutral'].copy()
    for line in extra:step(state,line)
    if state!=w['expected']:raise AssertionError('Joint replacement differs on the full 256-row live-wire table')
    return retained+extra


def select_nonoverlapping(results):
    rows=sorted((r for r in results if r['status']=='improved'),key=lambda r:(r['end'],r['start']))
    ends=[r['end'] for r in rows];dp=[(0,[])]
    for i,r in enumerate(rows):
        before=bisect_right(ends,r['start'],hi=i);gain,path=dp[before]
        take=(gain+r['original_count']-r['products'],path+[r])
        dp.append(take if take[0]>dp[-1][0] else dp[-1])
    return dp[-1][1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--parent-output',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--timeout-seconds',type=float,default=8);ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--complete-affine-tail',action='store_true')
    ap.add_argument('--factor-xor-order',type=int,choices=[1,2],default=1);ap.add_argument('--stop-by',required=True)
    args=ap.parse_args();started=time.monotonic();stop=datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None:raise ValueError('Timezone required')
    if not 1<=args.workers<=16 or not 0<args.timeout_seconds<=120:raise ValueError('Bounded resource parameters required')
    from generate import ROOT,sha256,output_workspace
    sys.path.insert(0,str(ROOT/'kickmix'));import kickmix as km
    c=args.output_dir.resolve().parent;screen=c/'screen';screen.mkdir(exist_ok=True);code=c/'code';code.mkdir(exist_ok=True)
    source=args.parent_output/'invsqrt.kmb';before=sha256(source)
    parent=km.Circuit.from_file(source);parent.to_file(screen/'parent.kmx');lines=(screen/'parent.kmx').read_text().splitlines()
    windows,structure=extract_windows(lines,args.complete_affine_tail);(screen/'windows.json').write_text(json.dumps(windows,indent=2)+'\n')
    if (stop-datetime.now(timezone.utc)).total_seconds()<args.timeout_seconds*len(windows)/args.workers+30:
        raise ValueError('Insufficient deadline margin for bounded search and save')
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(solve_window,[(w,args.timeout_seconds,args.factor_xor_order) for w in windows]):
            results.append(row)
            with (screen/'trials.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
            print(json.dumps({k:row[k] for k in ('start','end','status','original_count','products','elapsed_seconds')}),flush=True)
    selected=select_nonoverlapping(results);by_start={w['start']:w for w in windows};out=lines.copy()
    for row in sorted(selected,key=lambda r:r['start'],reverse=True):
        out[row['start']:row['end']]=replacement(lines,by_start[row['start']],row)
    report=dict(kind='adjacent_output_xor_basis',official_validation=False,parent_output=str(args.parent_output.resolve()),
        parent_sha256=before,source_generator_available=False,argv=sys.argv,parameters=vars(args).copy(),structure=structure,
        results=results,selected=selected,python_executable=sys.executable,python_prefix=sys.prefix,
        generator_sha256=sha256(Path(__file__)),solver_sha256=sha256(Path(__file__).with_name('invsqrt_lookup_resynth.py')))
    if selected:
        initial={q:None for q in range(62)};initial.update(INPUTS);original=initial.copy();changed=initial.copy()
        for line in lines[structure['start']:structure['end']]:step(original,line)
        newend=out.index('HMR q24 b12600',structure['start'])
        for line in out[structure['start']:newend]:step(changed,line)
        if changed!=original:raise AssertionError('Combined lookup mismatch')
        with output_workspace(args.output_dir) as (output,stage):
            circuit=km.Circuit('\n'.join(out)+'\n');circuit.to_file(stage/'invsqrt.kmb')
            if circuit.num_qubits!=parent.num_qubits:raise AssertionError('Qubit width changed')
        oldstats=dict(parent.operation_statistics());newstats=dict(circuit.operation_statistics())
        saving=oldstats.get('CCX',0)-newstats.get('CCX',0)
        if saving!=sum(r['original_count']-r['products'] for r in selected):raise AssertionError('Gate accounting mismatch')
        report.update(decision='requires_full_official_verification',saved_toffoli=saving,qubits=circuit.num_qubits,
            original_statistics=oldstats,output_statistics=newstats,artifacts=[{'path':'invsqrt.kmb','sha256':sha256(output/'invsqrt.kmb')}])
    else:report.update(decision='measured_no_gain_in_tested_scope',saved_toffoli=0)
    if sha256(source)!=before:raise AssertionError('Parent changed')
    for src in [Path(__file__),Path(__file__).with_name('invsqrt_lookup_resynth.py'),Path(__file__).with_name('generate.py')]:shutil.copy2(src,code/src.name)
    report['elapsed_seconds']=time.monotonic()-started
    (c/'generation.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(json.dumps({'decision':report['decision'],'saved_toffoli':report['saved_toffoli'],'eligible_windows':len(windows),'elapsed_seconds':report['elapsed_seconds']}))

if __name__=='__main__':main()
