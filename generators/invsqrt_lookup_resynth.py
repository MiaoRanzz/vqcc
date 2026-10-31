"""Bounded exact resynthesis of whole XOR/AND groups in a pinned InvSqrt lookup.

Recover all 256 rows of the eight-bit lookup locally from its operation stream.
For each multi-AND output group, solve for fewer products of affine live-wire
forms plus a linear correction. Preserve the group's affine operations and every
measurement/phase instruction outside it. SAT timeouts are unknown, never proofs
of minimality. The full official pipeline is the final gate.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import re
from itertools import combinations, islice
from functools import reduce
from operator import xor

Q = re.compile(r'\bq(\d+)\b')
ALL = (1 << 256)-1
INPUTS = {q: sum(1 << x for x in range(256) if (x >> (q-14)) & 1) for q in range(14,22)}


def step(state, line, skip_ccx=False):
    f = line.split(); op = f[0]
    qs = list(map(int, Q.findall(line)))
    if 'if' in f:
        raise ValueError('Conditional operation inside pure lookup block')
    if op == 'R':
        # Reject discarding nonzero values: this block must be phase-free.
        if state.get(qs[0]) not in (None,0):
            raise ValueError('Nonzero reset in lookup')
        state[qs[0]] = 0
    elif op in ('X','CX','CCX'):
        if op == 'CCX' and skip_ccx:
            return
        if any(state.get(q) is None for q in qs):
            raise ValueError(f'Unknown lookup wire: {line}')
        d = ALL
        for q in qs[:-1]:
            d &= state[q]
        state[qs[-1]] ^= d
    else:
        raise ValueError(f'Unexpected lookup operation: {line}')


def linear_basis(state, target):
    rows = {255:(ALL,1)}
    basis = []
    for q,v in sorted(state.items()):
        if q == target or v is None:
            continue
        w = v
        while w:
            k = w.bit_length()-1
            if k not in rows:
                rows[k] = (w,0);basis.append((q,v));break
            w ^= rows[k][0]
    return basis


def extract(lines):
    # These boundaries describe the pinned architecture, not generic defaults.
    start = lines.index('R q22',240)
    end = lines.index('HMR q24 b12600',start)
    state = {q:None for q in range(62)};state.update(INPUTS)
    nonlinear = [(i,int(Q.findall(lines[i])[-1])) for i in range(start,end) if lines[i].startswith('CCX ')]
    groups = []
    for i,t in nonlinear:
        if not groups or groups[-1]['target'] != t:
            groups.append(dict(target=t,indices=[]))
        groups[-1]['indices'].append(i)
    candidates = {g['indices'][0]:g for g in groups if len(g['indices'])>=2}
    snapshots = {}
    by_index = {i:g for g in candidates.values() for i in g['indices']}
    for g in candidates.values():g['control_tables']=[]
    for i in range(start,end):
        if i in candidates:
            snapshots[i] = state.copy()
        if i in by_index:
            a,b,_=map(int,Q.findall(lines[i]))
            by_index[i]['control_tables'].append([state[a],state[b]])
        step(state, lines[i])
        for g in candidates.values():
            if i != g['indices'][-1]:
                continue
            lo=g['indices'][0];neutral=snapshots[lo].copy()
            for line in lines[lo:i+1]:
                step(neutral,line,skip_ccx=True)
            t=g['target']
            if any(neutral[q]!=state[q] for q in state if q!=t):
                raise ValueError('Nonlinear target propagates outside its group')
            g.update(start=lo,end=i+1,delta=state[t]^neutral[t],
                     basis=linear_basis(neutral,t),neutral=neutral,
                     expected=state.copy(),original_count=len(g['indices']))
    return list(candidates.values()),dict(start=start,end=end,groups=len(groups),
                                         original_and_count=len(nonlinear))


def solve_columns(columns,target):
    rows={}
    for i,value in enumerate(columns):
        mask=1<<i
        while value:
            pivot=value.bit_length()-1
            if pivot not in rows:
                rows[pivot]=(value,mask);break
            v,c=rows[pivot];value^=v;mask^=c
    value=target;mask=0
    while value:
        pivot=value.bit_length()-1
        if pivot not in rows:return None
        v,c=rows[pivot];value^=v;mask^=c
    return mask


def solve_fixed_factors(job):
    g,products,timeout_ms,options=job
    start=time.monotonic();basis=g['basis'];d=len(basis);base=[v for q,v in basis]+[ALL]
    pools=set()
    for controls in g['control_tables']:
        for value in controls:
            mask=solve_columns(base,value)
            if mask is None:raise ValueError('Original factor unavailable in final affine basis')
            mask&=(1<<d)-1
            if mask:pools.add(mask)
    original_pool=sorted(pools)
    if options.get('factor_xor_order',1)==2:
        pools.update(a^b for a,b in combinations(original_pool,2) if a!=b)
    pool=sorted(pools)
    terms={a:[reduce(xor,(v for j,(_,v) in enumerate(basis) if a>>j&1),0)&v for _,v in basis] for a in pool}
    prior=int(options.get('resume_offset',0));tested=prior
    for factors in islice(combinations(pool,products),prior,None):
        if time.monotonic()-start>timeout_ms/1000:break
        tested+=1
        columns=base+[v for a in factors for v in terms[a]]
        mask=solve_columns(columns,g['delta'])
        if mask is None:continue
        linear=mask&((1<<(d+1))-1);coefficients=[]
        for i,a in enumerate(factors):
            b=(mask>>(d+1+i*d))&((1<<d)-1)
            if b==a:linear^=a
            elif b:coefficients.append([a,b])
        actual=reduce(xor,(v for j,v in enumerate(base) if linear>>j&1),0)
        for a,b in coefficients:
            av=reduce(xor,(v for j,(_,v) in enumerate(basis) if a>>j&1),0)
            bv=reduce(xor,(v for j,(_,v) in enumerate(basis) if b>>j&1),0)
            actual^=av&bv
        assert actual==g['delta']
        return dict(start=g['start'],end=g['end'],target=g['target'],original_count=g['original_count'],
            products=len(coefficients),basis_dimension=d,status='sat',elapsed_seconds=time.monotonic()-start,
            method='finite_factor_pool',factor_xor_order=options.get('factor_xor_order',1),prior_combinations=prior,pool_size=len(pool),combinations_tested=tested,
            coefficients=coefficients,linear=linear,basis_qubits=[q for q,_ in basis])
    else:
        return dict(start=g['start'],end=g['end'],target=g['target'],original_count=g['original_count'],
            products=products,basis_dimension=d,status='unsat',elapsed_seconds=time.monotonic()-start,
            method='finite_factor_pool',factor_xor_order=options.get('factor_xor_order',1),prior_combinations=prior,pool_size=len(pool),combinations_tested=tested)
    return dict(start=g['start'],end=g['end'],target=g['target'],original_count=g['original_count'],
        products=products,basis_dimension=d,status='unknown',elapsed_seconds=time.monotonic()-start,
        method='finite_factor_pool',factor_xor_order=options.get('factor_xor_order',1),prior_combinations=prior,pool_size=len(pool),combinations_tested=tested,reason='timeout')


def solve_group(job):
    g,products,timeout_ms,solver_path=job
    sys.path.insert(0,solver_path)
    import z3
    start=time.monotonic();basis=g['basis'];d=len(basis)
    solver=z3.SolverFor('QF_BV');solver.set(timeout=timeout_ms,random_seed=0)
    params=[];forms=[];zero=z3.BitVecVal(0,256)
    for k in range(products):
        pair=[];masks=[]
        for side in ('a','b'):
            mask=z3.BitVec(f'{side}{k}',d);masks.append(mask)
            terms=[z3.If(z3.Extract(j,j,mask)==1,z3.BitVecVal(v,256),zero) for j,(_,v) in enumerate(basis)]
            pair.append(reduce(xor,terms,zero))
            solver.add(mask!=0)
        solver.add(z3.ULT(masks[0],masks[1]))
        if params:
            solver.add(z3.ULT(params[-1][0],masks[0]))
        params.append(masks);forms.append(pair[0]&pair[1])
    linear=z3.BitVec('linear',d+1)
    terms=[z3.If(z3.Extract(j,j,linear)==1,z3.BitVecVal(v,256),zero) for j,(_,v) in enumerate(basis)]
    terms.append(z3.If(z3.Extract(d,d,linear)==1,z3.BitVecVal(ALL,256),zero))
    solver.add(reduce(xor,forms+terms,zero)==z3.BitVecVal(g['delta'],256))
    result=solver.check()
    row=dict(start=g['start'],end=g['end'],target=g['target'],original_count=g['original_count'],
             products=products,basis_dimension=d,status=str(result),elapsed_seconds=time.monotonic()-start,
             solver_version=z3.get_version_string(),random_seed=0,timeout_ms=timeout_ms)
    if result == z3.sat:
        m=solver.model();coeffs=[[m.eval(p).as_long() for p in pair] for pair in params]
        lin=m.eval(linear).as_long();actual=ALL if (lin>>d)&1 else 0
        for j,(_,v) in enumerate(basis):
            if (lin>>j)&1:actual^=v
        for a,b in coeffs:
            av=reduce(xor,(v for j,(_,v) in enumerate(basis) if a>>j&1),0)
            bv=reduce(xor,(v for j,(_,v) in enumerate(basis) if b>>j&1),0)
            actual^=av&bv
        if actual!=g['delta']:
            raise AssertionError('Independent exhaustive table check failed')
        row.update(coefficients=coeffs,linear=lin,basis_qubits=[q for q,_ in basis])
    elif result == z3.unknown:
        row['reason']=solver.reason_unknown()
    return row


def product_gates(a,b,qubits,target):
    """Conjugate CCX by an invertible affine map, using no extra wire."""
    aset={qubits[j] for j in range(len(qubits)) if a>>j&1}
    bset={qubits[j] for j in range(len(qubits)) if b>>j&1}
    if not aset or not bset or aset==bset or target in aset|bset:
        raise ValueError('Expected independent nonzero control forms')
    p=min(aset);prep=[f'CX q{q} q{p}' for q in sorted(aset-{p})]
    if p in bset:
        bset ^= aset-{p}
    others=bset-{p}
    if not others:
        raise ValueError('Dependent control forms')
    r=min(others);prep += [f'CX q{q} q{r}' for q in sorted(bset-{r})]
    return prep+[f'CCX q{p} q{r} q{target}']+list(reversed(prep))


def apply_solution(lines,groups,rows):
    replacements={}
    for g,row in zip(groups,rows):
        if row['status']!='sat':
            continue
        t=g['target'];qs=row['basis_qubits'];d=len(qs)
        retained=[l for l in lines[g['start']:g['end']] if not l.startswith('CCX ')]
        extra=[]
        for a,b in row['coefficients']:
            extra += product_gates(a,b,qs,t)
        if row['linear']>>d&1:extra.append(f'X q{t}')
        extra += [f'CX q{q} q{t}' for j,q in enumerate(qs) if row['linear']>>j&1]
        check=g['neutral'].copy()
        # The retained original affine instructions were already applied to neutral.
        for l in extra:step(check,l)
        if check!=g['expected']:
            raise AssertionError('Replacement gate-level table mismatch')
        replacements[g['start']]=(g['end'],retained+extra)
    out=[];i=0
    while i<len(lines):
        if i in replacements:
            end,new=replacements[i];out.extend(new);i=end
        else:out.append(lines[i]);i+=1
    return '\n'.join(out)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--solver-path',type=Path)
    p.add_argument('--method',choices=['sat','fixed-factors'],default='sat')
    p.add_argument('--factor-xor-order',type=int,choices=[1,2],default=1)
    p.add_argument('--timeout-seconds',type=float,default=30)
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--stop-by',required=True)
    p.add_argument('--group-limit',type=int,default=0)
    p.add_argument('--resume-candidate',type=Path)
    args=p.parse_args();start=time.monotonic()
    stop=datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None:raise ValueError('Timezone required')
    from generate import ROOT,sha256,output_workspace
    sys.path.insert(0,str(ROOT/'kickmix'));import kickmix as km
    candidate=args.output_dir.resolve().parent;screen=candidate/'screen';screen.mkdir(exist_ok=True)
    source=args.parent_output/'invsqrt.kmb';circ=km.Circuit.from_file(source);circ.to_file(screen/'parent.kmx')
    lines=(screen/'parent.kmx').read_text().splitlines();groups,structure=extract(lines)
    if args.group_limit:groups=groups[:args.group_limit]
    (screen/'lookup-groups.json').write_text(json.dumps(groups,indent=2)+'\n')
    previous={}
    if args.resume_candidate:
        if args.method!='fixed-factors':raise ValueError('Resume supports finite factor search only')
        old=json.loads((args.resume_candidate/'generation.json').read_text())
        oldargv=old['argv']
        oldorder=int(oldargv[oldargv.index('--factor-xor-order')+1]) if '--factor-xor-order' in oldargv else 1
        if old['parent_sha256']!=sha256(source) or oldorder!=args.factor_xor_order or '--method' not in oldargv or oldargv[oldargv.index('--method')+1]!='fixed-factors':
            raise ValueError('Resume parent or search domain differs')
        if sha256(screen/'lookup-groups.json')!=sha256(args.resume_candidate/'screen/lookup-groups.json'):
            raise ValueError('Resume lookup tables/interfaces differ')
        previous={r['start']:r for r in json.loads((args.resume_candidate/'screen/synthesis.json').read_text())}
    rows_by_start={k:dict(v,reused_from=str(args.resume_candidate)) for k,v in previous.items() if v['status']!='unknown'}
    todo=[g for g in groups if g['start'] not in rows_by_start]
    status='completed'
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for offset in range(0,len(todo),args.workers):
            if (stop-datetime.now(timezone.utc)).total_seconds()<args.timeout_seconds+30:
                status='bounded_deadline';break
            batch=todo[offset:offset+args.workers]
            jobs=[]
            for g in batch:
                options=str(args.solver_path) if args.method=='sat' else dict(factor_xor_order=args.factor_xor_order,resume_offset=previous.get(g['start'],{}).get('combinations_tested',0))
                jobs.append((g,g['original_count']-1,int(args.timeout_seconds*1000),options))
            solve=solve_group if args.method=='sat' else solve_fixed_factors
            for row in pool.map(solve,jobs):
                rows_by_start[row['start']]=row;print(json.dumps(row),flush=True)
                (screen/'synthesis.json').write_text(json.dumps(sorted(rows_by_start.values(),key=lambda r:r['start']),indent=2)+'\n')
    groups=[g for g in groups if g['start'] in rows_by_start]
    rows=[rows_by_start[g['start']] for g in groups]
    if any(r['status']=='unknown' for r in rows):status='partial'
    (screen/'synthesis.json').write_text(json.dumps(rows,indent=2)+'\n')
    text=apply_solution(lines,groups,rows);(screen/'transformed.kmx').write_text(text)
    transformed=km.Circuit.from_file(screen/'transformed.kmx')
    with output_workspace(args.output_dir) as (output,stage):
        if any(r['status']=='sat' for r in rows):transformed.to_file(stage/'invsqrt.kmb')
        else:shutil.copy2(source,stage/'invsqrt.kmb')
    code=candidate/'code';code.mkdir(exist_ok=True);shutil.copy2(Path(__file__),code/Path(__file__).name)
    for name in ('CREDITS.md','LICENSE.md','QCC_RELEASE_MANIFEST.json','public-manifest.json'):
        f=args.parent_output.parent/'code'/name
        if f.exists():shutil.copy2(f,code/name)
    report=dict(kind='exact_lookup_group_resynthesis',official_validation=False,status=status,
        parent_output=str(args.parent_output.resolve()),parent_sha256=sha256(source),
        generator_sha256=sha256(Path(__file__)),argv=sys.argv,python_executable=sys.executable,python_prefix=sys.prefix,
        created_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-start,structure=structure,
        groups_tested=len(rows),groups_solved=sum(r['status']=='sat' for r in rows),
        unconditional_toffolis_saved=sum(r['original_count']-r['products'] for r in rows if r['status']=='sat'),
        qubits=transformed.num_qubits,artifacts=[dict(path='invsqrt.kmb',sha256=sha256(output/'invsqrt.kmb'))])
    (candidate/'generation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
