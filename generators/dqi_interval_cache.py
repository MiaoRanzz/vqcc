# SPDX-License-Identifier: Apache-2.0
"""Cache two equal products across a certified unused clean-wire interval.

Compute a*b into a spare before the first original CCX, use CX for both original
updates, then HMR the spare and repay its phase using the second pair of controls.
The symbolic scanner certifies exact equality of both products, clean entry,
no original access to the spare, and disjoint intervals. One Toffoli is saved
per pair without increasing Q. Complete artifacts always undergo full validation.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import numpy as np
from dqi_boolean_reduce import read_binary, read_proofs, compile_scanner, MAGIC, NAMES
from generate import output_workspace, sha256


def linear_basis_gates(ma, mb):
    """Shortest reversible X-free basis change, as wire-index CX pairs."""
    if ma not in (1, 2, 3) or mb not in (1, 2, 3) or ma == mb:
        raise ValueError('Singular Boolean control basis')
    queue = [((1, 2), [])]
    seen = {(1, 2)}
    for (a, b), gates in queue:
        if (a, b) == (ma, mb):
            return gates
        for state, gate in (((a, a ^ b), (0, 1)), ((a ^ b, b), (1, 0))):
            if state not in seen:
                seen.add(state)
                queue.append((state, gates + [gate]))
    raise AssertionError('GL(2,2) basis not reachable')


def product_correction(ma, mb, ca, cb):
    """UV = ab + la*a + lb*b + constant for an invertible affine map."""
    linear_basis_gates(ma, mb)
    a, b, c, d = ma & 1, (ma >> 1) & 1, mb & 1, (mb >> 1) & 1
    return (a*c) ^ (ca*c) ^ (cb*a), (b*d) ^ (ca*d) ^ (cb*b), ca*cb


def rewrite_intervals(source, destination, proofs):
    data = read_binary(source); old = data['packets']; types = old['types']
    proofs = sorted(proofs, key=lambda p:p['op'])
    if not proofs:
        shutil.copyfile(source,destination)
        return dict(pairs=0,removed_toffolis=0,added_measurements=0,qubits=data['nq'])
    previous = -1; changes = []
    for j,p in enumerate(proofs):
        start,end,spare = p['op'],p['end'],p['spare']
        if p['kind']!='cached_pair' or not previous<start<end<len(types):
            raise ValueError('Overlapping or invalid pair intervals')
        if not 0<=spare<data['nq']:
            raise ValueError('Spare outside original width')
        previous=end; bit=data['nb']+j
        a,b,t = p['a'],p['b'],p['target']
        aa,bb,tt = p['a_last'],p['b_last'],p['target_last']
        if spare in (a,b,t,aa,bb,tt):
            raise ValueError('Spare aliases an original operand')
        ca,cb,cca,ccb=[p.get(k,0) for k in ('ca','cb','ca_last','cb_last')]
        if any(v not in (0,1) for v in (ca,cb,cca,ccb)):
            raise ValueError('Invalid complemented-factor certificate')
        first={name:[] for name in NAMES[:9]};last={name:[] for name in NAMES[:9]}
        def emit(out,op,**operands):
            out['types'].append(op)
            for name,value in operands.items():out[name].append(value)
        ma,mb,mma,mmb=[p.get(k,default) for k,default in (('ma',1),('mb',2),('ma_last',1),('mb_last',2))]
        def basis(out,x,y,m,n,c,d,inverse=False):
            gates=linear_basis_gates(m,n); wires=(x,y)
            if inverse:
                if c:emit(out,0x11,q=x)
                if d:emit(out,0x11,q=y)
            for control,target in reversed(gates) if inverse else gates:
                emit(out,0x21,a2=wires[control],t2=wires[target])
            if not inverse:
                if c:emit(out,0x11,q=x)
                if d:emit(out,0x11,q=y)
        def update(out,x,y,target,m,n,c,d):
            la,lb,constant=product_correction(m,n,c,d)
            emit(out,0x21,a2=spare,t2=target)
            if la:emit(out,0x21,a2=x,t2=target)
            if lb:emit(out,0x21,a2=y,t2=target)
            if constant:emit(out,0x11,q=target)
        basis(first,a,b,ma,mb,ca,cb)
        emit(first,0x31,a3=a,b3=b,t3=spare)
        basis(first,a,b,ma,mb,ca,cb,inverse=True)
        update(first,a,b,t,ma,mb,ca,cb)
        update(last,aa,bb,tt,mma,mmb,cca,ccb)
        basis(last,aa,bb,mma,mmb,cca,ccb)
        emit(last,0x50,q=spare,bit=bit)
        emit(last,0xa0,a2=aa,t2=bb,condition=bit)
        basis(last,aa,bb,mma,mmb,cca,ccb,inverse=True)
        changes += [(start,first,(a,b,t)),(end,last,(aa,bb,tt))]
    ops=np.array([c[0] for c in changes],dtype=np.int64)
    if np.any(types[ops]!=0x31):
        raise ValueError('Expected unconditional CCX opcodes')
    stacks=np.flatnonzero((types==0x81)|(types==1))
    depths=np.cumsum(np.where(types[stacks]==0x81,1,-1))
    if np.any(depths<0) or (len(depths) and depths[-1]):
        raise ValueError('Malformed classical condition stack')
    ranks=np.searchsorted(stacks,ops,side='right')-1
    if any(depths[k] for k in ranks if k>=0):
        raise ValueError('Original CCX is inside a classical condition')
    positions={}; op_positions={}
    for names,mask in [(['a3','b3','t3'],(types&0x30)==0x30),(['a2','t2'],(types&0x30)==0x20),(['q'],(types&0x30)==0x10),(['bit'],(types&0x40)!=0),(['condition'],(types&0x80)!=0)]:
        indices=np.flatnonzero(mask); rank=np.searchsorted(indices,ops)
        for name in names:
            positions[name]=rank;op_positions[name]=indices
    for j,(_,_,expected) in enumerate(changes):
        actual=tuple(int(old[name][positions[name][j]]) for name in ('a3','b3','t3'))
        if actual!=expected:
            raise ValueError('Proof operand mismatch')
    # Independently verify the no-access claim against original binary operands.
    for p in proofs:
        for name in ('a3','b3','t3','a2','t2','q'):
            lo,hi=np.searchsorted(op_positions[name],[p['op'],p['end']+1])
            if np.any(old[name][lo:hi]==p['spare']):
                raise ValueError('Spare referenced within the interval')
    changed={}
    for name in NAMES[:9]:
        arr=old[name];rank=ops if name=='types' else positions[name]
        pieces=[];last=0
        for pos,(_,replacement,_) in zip(rank,changes):
            pos=int(pos);remove=int(name in ('types','a3','b3','t3'))
            pieces.extend([arr[last:pos],np.asarray(replacement.get(name,[]),dtype=arr.dtype)])
            last=pos+remove
        pieces.append(arr[last:]);changed[name]=np.concatenate(pieces)
    counts=data['counts'].copy();counts[:6]=[len(changed[n]) for n in ('types','a3','a2','q','bit','condition')]
    with Path(destination).open('wb') as out:
        out.write(MAGIC);out.write(struct.pack('<4I',2,data['nq'],data['nb']+len(proofs),data['nr']))
        out.write(struct.pack('<9Q',*counts));out.write(data['registers'])
        for i,name in enumerate(NAMES,1):
            payload=changed.get(name,old[name]);out.write(struct.pack('<2Q',i,payload.nbytes));out.write(payload.tobytes())
    return dict(pairs=len(proofs),removed_toffolis=len(proofs),added_measurements=len(proofs),qubits=data['nq'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--expected-parent-sha256',required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--term-cap',type=int,default=512)
    p.add_argument('--xor-cache-limit',type=int,default=0)
    p.add_argument('--canonical-complements',action='store_true')
    p.add_argument('--canonical-planes',action='store_true')
    p.add_argument('--timeout-seconds',type=int,default=240)
    a=p.parse_args();start=time.monotonic()
    if not 1<=a.term_cap<=4096 or not 0<=a.xor_cache_limit<=262144 or not 1<=a.timeout_seconds<=900:
        p.error('Invalid bounded proof budget')
    parent=a.parent_output/'dqi.kmb'
    if sha256(parent)!=a.expected_parent_sha256:
        raise ValueError('Pinned parent changed')
    candidate=a.output_dir.parent;screen=candidate/'screen';code=candidate/'code'
    screen.mkdir(exist_ok=True);code.mkdir(exist_ok=True)
    names=['dqi_interval_cache.py','dqi_boolean_reduce.py','dqi_boolean_screen.cpp','generate.py']
    for name in names:shutil.copy2(Path(__file__).with_name(name),code/name)
    scanner=screen/'interval-scanner';source,compile_command=compile_scanner(scanner,code/'dqi_boolean_screen.cpp')
    proofs_path=screen/'proofs.tsv';summary=screen/'summary.json'
    command=[str(scanner),str(parent),str(proofs_path),str(summary),str(a.term_cap),str(a.xor_cache_limit),'0','0','4' if a.canonical_planes else '3' if a.canonical_complements else '2']
    with (screen/'scanner.log').open('w') as log:
        subprocess.run(command,check=True,stdout=log,stderr=log,timeout=a.timeout_seconds)
    proofs=read_proofs(proofs_path)
    with output_workspace(a.output_dir) as (output,stage):
        change=rewrite_intervals(parent,stage/'dqi.kmb',proofs)
    if sha256(parent)!=a.expected_parent_sha256:raise ValueError('Parent changed during generation')
    report=dict(kind='exact_idle_interval_product_cache',official_validation=False,
        argv=sys.argv,python_executable=sys.executable,python_prefix=sys.prefix,
        parent_output=str(a.parent_output.resolve()),parent_sha256=a.expected_parent_sha256,
        source_generator_available=False,parameters=dict(term_cap=a.term_cap,xor_cache_limit=a.xor_cache_limit,canonical_complements=a.canonical_complements or a.canonical_planes,canonical_planes=a.canonical_planes,selection='greedy_disjoint_latest_product_pair'),
        source_hashes={name:sha256(code/name) for name in names},compile_command=compile_command,
        screen_command=command,screen=json.loads(summary.read_text()),proof_sha256=sha256(proofs_path),
        change=change,exact_sites=len(proofs),
        artifacts=[dict(path='dqi.kmb',sha256=sha256(output/'dqi.kmb'))],elapsed_seconds=time.monotonic()-start)
    (candidate/'generation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
