# SPDX-License-Identifier: Apache-2.0
"""Trade one extra clean qubit for two CCX at each exact three-input AND.

The retained census selects sites, but each four-gate Boolean identity and its
unconditional context are rechecked before rewriting. A fresh global qubit
computes ab, controls the target update with c, then HMR/CZ erases ab exactly.
Any old target and dirty borrowing values are preserved. Q increases by one;
full official verification is required even when estimated Q²T gets worse.
"""
from __future__ import annotations
import argparse,json,shutil,struct,sys,time
from pathlib import Path
import numpy as np
from dqi_boolean_reduce import read_binary,NAMES,MAGIC
from dqi_and_census import classify
from generate import sha256,output_workspace


def rewrite(source, destination, sites):
    data=read_binary(source);old=data['packets'];types=old['types']
    sites=sorted(sites,key=lambda s:s['start']);ops=np.array([s['start'] for s in sites],dtype=np.int64)
    if not len(ops) or ops[0]<0 or ops[-1]+4>len(types) or np.any(np.diff(ops)<4):raise ValueError('Invalid sites')
    stack_pos=np.flatnonzero((types==0x81)|(types==1))
    depth=np.cumsum(np.where(types[stack_pos]==0x81,1,-1))
    if np.any(depth<0) or (len(depth) and depth[-1]):raise ValueError('Invalid condition stack')
    positions={}
    for names,mask in [(['a3','b3','t3'],(types&0x30)==0x30),(['a2','t2'],(types&0x30)==0x20),(['q'],(types&0x30)==0x10),(['bit'],(types&0x40)!=0),(['condition'],(types&0x80)!=0)]:
        ranks=np.searchsorted(np.flatnonzero(mask),ops)
        for name in names:positions[name]=ranks
    replacements=[];spare=data['nq']
    for j,site in enumerate(sites):
        op=int(ops[j]);offset=int(positions['a3'][j]);stack=int(np.searchsorted(stack_pos,op,side='right'))-1
        if (stack>=0 and depth[stack]) or not np.all(types[op:op+4]==0x31) or site['end']!=op+4:raise ValueError('Site must be four unconditional CCX')
        gates=list(zip(*(old[name][offset:offset+4].tolist() for name in ('a3','b3','t3'))));proof=classify(gates)
        if proof['decision']!='exact_and' or proof['degree']!=3:raise ValueError('No exact three-input AND')
        if proof['target']!=site['target'] or proof['controls']!=site['controls']:raise ValueError('Census mismatch')
        a,b,c=proof['controls'];target=proof['target'];bit=data['nb']+j
        replacements.append(dict(types=[0x31,0x31,0x50,0xa0],a3=[a,spare],b3=[b,c],t3=[spare,target],q=[spare],bit=[bit],a2=[a],t2=[b],condition=[bit]))
    changed={}
    for name in NAMES[:9]:
        arr=old[name];ranks=ops if name=='types' else positions[name];parts=[];last=0
        for pos,r in zip(ranks,replacements):
            pos=int(pos);remove=4 if name in ('types','a3','b3','t3') else 0
            parts.extend([arr[last:pos],np.asarray(r.get(name,[]),dtype=arr.dtype)]);last=pos+remove
        parts.append(arr[last:]);changed[name]=np.concatenate(parts)
    counts=data['counts'].copy();counts[:6]=[len(changed[n]) for n in ('types','a3','a2','q','bit','condition')]
    with Path(destination).open('wb') as out:
        out.write(MAGIC);out.write(struct.pack('<4I',2,data['nq']+1,data['nb']+len(sites),data['nr']));out.write(struct.pack('<9Q',*counts));out.write(data['registers'])
        for i,name in enumerate(NAMES,1):
            payload=changed.get(name,old[name]);out.write(struct.pack('<2Q',i,payload.nbytes));out.write(payload.tobytes())
    return dict(sites=len(sites),old_qubits=data['nq'],new_qubits=data['nq']+1,toffoli_reduction=2*len(sites),new_measurement_bits=len(sites))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--census',type=Path,required=True);p.add_argument('--expected-parent-sha256',required=True)
    args=p.parse_args();started=time.monotonic();source=args.parent_output/'dqi.kmb'
    if sha256(source)!=args.expected_parent_sha256:raise ValueError('Parent changed')
    census=json.loads(args.census.read_text())
    if census['parent_sha256']!=args.expected_parent_sha256:raise ValueError('Census parent mismatch')
    sites=[s for s in census['sites'] if s['degree']==3 and s['ccx']==4]
    with output_workspace(args.output_dir) as (out,stage):change=rewrite(source,stage/'dqi.kmb',sites)
    for name in ['dqi_clean_spare.py','dqi_and_census.py','dqi_boolean_reduce.py','generate.py']:shutil.copy2(Path(__file__).with_name(name),out.parent/'code'/name)
    shutil.copy2(args.census,out.parent/'code/census.json')
    report=dict(kind='one_extra_qubit_three_input_and',official_validation=False,parent_output=str(args.parent_output.resolve()),parent_sha256=args.expected_parent_sha256,census_sha256=sha256(args.census),argv=sys.argv,python=sys.executable,prefix=sys.prefix,change=change,sites=sites,generator_sha256=sha256(Path(__file__)),artifacts=[dict(path='dqi.kmb',sha256=sha256(out/'dqi.kmb'))],elapsed_seconds=time.monotonic()-started)
    (out.parent/'generation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(change))


if __name__=='__main__':main()
