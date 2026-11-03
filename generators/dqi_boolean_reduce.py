"""Prove and apply local Boolean CCX, CCZ and CSWAP reductions to a pinned DQI artifact.

The bounded symbolic C++ screen overapproximates conditional writes and large
expressions with fresh atoms. It cannot infer identities from sampled inputs.
The transform retains every existing classical bit, angle, tag and register;
measurement uncomputation uses fresh bits and conditional CZ phase repair.
Full unchanged official verification and independent robustness remain required.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import numpy as np
from generate import output_workspace, sha256

MAGIC = bytes.fromhex('d750c7d5c329d326e3cc9f6834f2b8bf')
NAMES = ['types','a3','b3','t3','a2','t2','q','bit','condition','angles','tags']


def read_binary(path):
    raw=np.memmap(path,mode='r',dtype=np.uint8)
    if bytes(raw[:16])!=MAGIC:raise ValueError('KMB magic')
    version,nq,nb,nr=struct.unpack_from('<4I',raw,16)
    if version!=2:raise ValueError('KMB version')
    counts=list(struct.unpack_from('<9Q',raw,32));pos=104
    for _ in range(nr):
        packet,size=struct.unpack_from('<2Q',raw,pos)
        if packet!=0:raise ValueError('Register packet')
        pos+=16+size
    registers=bytes(raw[104:pos]);packets={}
    for expected,name in enumerate(NAMES,1):
        packet,size=struct.unpack_from('<2Q',raw,pos)
        if packet!=expected:raise ValueError('Stream packet')
        pos+=16
        if pos+size>len(raw):raise ValueError('Truncated packet')
        dtype=np.uint8 if name in ('types','angles','tags') else np.dtype('<u4')
        packets[name]=np.frombuffer(raw,dtype=dtype,count=size//np.dtype(dtype).itemsize,offset=pos)
        pos+=size
    if pos!=len(raw):raise ValueError('Trailing bytes')
    return dict(raw=raw,nq=nq,nb=nb,nr=nr,counts=counts,registers=registers,packets=packets)


def rewrite(source,destination,proofs,allow_classical_guards=False):
    data=read_binary(source);old=data['packets'];types=old['types']
    proofs=sorted(proofs,key=lambda p:p['op'])
    if len({p['op'] for p in proofs})!=len(proofs):raise ValueError('Duplicate proof')
    ops=np.array([p['op'] for p in proofs],dtype=np.int64)
    if len(ops) and (ops.min()<0 or ops.max()>=len(types)):
        raise ValueError('Proof operation outside circuit')
    expected=[int(types[p['op']])&0x7f if p['kind']=='dead' else 0x30 if p['kind'].startswith('ccz_') else 0x32 if p['kind'].startswith('cswap_') else 0x31 for p in proofs]
    if any(t not in (0x30,0x31,0x32) for t in expected):
        raise ValueError('Expected three-qubit proof')
    if len(ops) and (np.any((types[ops]&0x7f)!=expected) or (not allow_classical_guards and np.any(types[ops]&0x80))):
        raise ValueError('Expected matching CCX/CCZ/CSWAP and guard authorization')
    positions={}
    for names,mask in [(['a3','b3','t3'],(types&0x30)==0x30),(['a2','t2'],(types&0x30)==0x20),(['q'],(types&0x30)==0x10),(['bit'],(types&0x40)!=0),(['condition'],(types&0x80)!=0)]:
        idx=np.flatnonzero(mask);rank=np.searchsorted(idx,ops)
        for name in names:positions[name]=rank
    newbits=data['nb'];replacements=[]
    for j,p in enumerate(proofs):
        a,b,t=(int(old[name][positions[name][j]]) for name in ('a3','b3','t3'))
        if [a,b,t]!=[p['a'],p['b'],p['target']]:raise ValueError('Proof operand mismatch')
        r={name:[] for name in NAMES[:9]}
        kind=p['kind'];qs=[a,b,t]
        if kind in ('zero','ccz_zero','cswap_zero','dead'):pass
        elif kind=='ccz_neg':r.update(types=[0x00])
        elif kind.startswith('ccz_z') and kind[-1] in '012':
            r.update(types=[0x10],q=[qs[int(kind[-1])]])
        elif kind.startswith('ccz_cz') and kind[-1] in '012':
            k=int(kind[-1]);r.update(types=[0x20],a2=[qs[k]],t2=[qs[(k+1)%3]])
        elif kind=='cswap_swap':r.update(types=[0x22],a2=[b],t2=[t])
        elif kind=='cswap_cx':r.update(types=[0x21,0x21],a2=[a,a],t2=[b,t])
        elif p['kind'] in ('cx_a','cx_b'):
            r.update(types=[0x21],a2=[a if p['kind']=='cx_a' else b],t2=[t])
        elif kind=='cached_cx':
            cached=p['cache']
            if not 0<=cached<data['nq'] or cached in (a,b,t):
                raise ValueError('Invalid independent cached-product wire')
            r.update(types=[0x21],a2=[cached],t2=[t])
        elif p['kind']=='hmr':
            r.update(types=[0x50,0xa0],q=[t],bit=[newbits],a2=[a],t2=[b],condition=[newbits]);newbits+=1
        else:raise ValueError('Unknown proof kind')
        replacements.append(r)
    changed={}
    for name in NAMES[:9]:
        arr=old[name];rank=ops if name=='types' else positions[name]
        parts=[];last=0
        for j,(p,r) in enumerate(zip(rank,replacements)):
            remove=int(name in ('types','a3','b3','t3') or (name=='condition' and bool(types[ops[j]]&0x80)))
            p=int(p);parts.extend([arr[last:p],np.asarray(r[name],dtype=arr.dtype)]);last=p+remove
        parts.append(arr[last:]);changed[name]=np.concatenate(parts)
    # KMB requires headers to match the largest referenced wire. Removing a
    # wire's sole gate must not silently change the promised register width.
    # Paired inversions are identity and have zero Toffoli cost.
    for header,names,op,stream in [(data['nq'],('a3','b3','t3','a2','t2','q'),0x11,'q'),
                                  (newbits,('bit','condition'),0x42,'bit')]:
        largest=max((int(changed[n].max()) for n in names if len(changed[n])),default=-1)
        if header and largest<header-1:
            changed['types']=np.concatenate([changed['types'],np.array([op,op],dtype=np.uint8)])
            changed[stream]=np.concatenate([changed[stream],np.array([header-1,header-1],dtype='<u4')])
    counts=data['counts'].copy()
    counts[:6]=[len(changed[n]) for n in ('types','a3','a2','q','bit','condition')]
    with Path(destination).open('wb') as out:
        out.write(MAGIC);out.write(struct.pack('<4I',2,data['nq'],newbits,data['nr']))
        out.write(struct.pack('<9Q',*counts));out.write(data['registers'])
        for i,name in enumerate(NAMES,1):
            payload=changed.get(name,old[name]);out.write(struct.pack('<2Q',i,payload.nbytes));out.write(payload.tobytes())
    return dict(removed_toffolis=len(proofs),added_measurements=newbits-data['nb'],qubits=data['nq'])


def read_proofs(path):
    with Path(path).open() as stream:
        return [{k:int(v) if k!='kind' else v for k,v in row.items()} for row in csv.DictReader(stream,delimiter='\t')]


def compile_scanner(output,source=None):
    source=source or Path(__file__).with_name('dqi_boolean_screen.cpp')
    command=['g++','-O3','-std=c++17','-Wall','-Wextra',str(source),'-o',str(output)]
    subprocess.run(command,check=True)
    return source,command


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--parent-output',type=Path,required=True)
    ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--term-cap',type=int,default=512)
    ap.add_argument('--scanner-source',type=Path,default=Path(__file__).with_name('dqi_boolean_screen.cpp'))
    ap.add_argument('--xor-cache-limit',type=int,default=0)
    ap.add_argument('--reuse-screen',type=Path,help='Pinned completed screen record; reuse matching evidence')
    ap.add_argument('--classical-guards',action='store_true')
    ap.add_argument('--timeout-seconds',type=int,default=900)
    args=ap.parse_args();start=time.monotonic()
    if not 1<=args.term_cap<=4096:raise ValueError('term cap outside bounded range')
    if not 0<=args.xor_cache_limit<=262144:raise ValueError('cache outside bounded range')
    parent=args.parent_output/'dqi.kmb';parent_hash=sha256(parent)
    candidate=args.output_dir.parent;screen=candidate/'screen';screen.mkdir(exist_ok=True)
    code=candidate/'code';code.mkdir(exist_ok=True)
    source=args.scanner_source
    if args.reuse_screen:
        saved=json.loads(args.reuse_screen.read_text())
        if saved['parent_sha256']!=parent_hash or saved['scanner_sha256']!=sha256(source):
            raise ValueError('Stale source/parent screen evidence')
        if saved['term_cap']!=args.term_cap or saved['xor_cache_limit']!=args.xor_cache_limit or bool(saved.get('classical_guards',False))!=args.classical_guards:
            raise ValueError('Screen parameter mismatch')
        proofs_path=Path(saved['proofs_path']);summary=Path(saved['summary_path'])
        if sha256(proofs_path)!=saved['proof_sha256'] or sha256(summary)!=saved['summary_sha256']:
            raise ValueError('Screen evidence changed')
        command=saved['command'];compile_command=saved['compile_command']
    else:
        scanner=screen/'boolean-scanner';source,compile_command=compile_scanner(scanner,source)
        proofs_path=screen/'transform-proofs.tsv';summary=screen/'transform-summary.json'
        command=[str(scanner),str(parent),str(proofs_path),str(summary),str(args.term_cap)]
        if args.xor_cache_limit or args.classical_guards:command.append(str(args.xor_cache_limit))
        if args.classical_guards:command.append('1')
        with (screen/'transform-scanner.stderr').open('w') as log:
            subprocess.run(command,check=True,stderr=log,timeout=args.timeout_seconds)
    proofs=read_proofs(proofs_path)
    report=dict(kind='exact_boolean_three_qubit_reduction',official_validation=False,
        created_at=datetime.now(timezone.utc).isoformat(),parent_output=str(args.parent_output.resolve()),
        parent_sha256=parent_hash,source_generator_available=False,
        reproducibility='Pinned artifact transformation; original high-level decoder recipe remains unavailable',
        parameters={'term_cap':args.term_cap,'xor_cache_limit':args.xor_cache_limit,'classical_guards':args.classical_guards},scanner_sha256=sha256(source),generator_sha256=sha256(Path(__file__)),
        compile_command=compile_command,screen_command=command,argv=sys.argv,
        screen=json.loads(summary.read_text()),proof_sha256=sha256(proofs_path),
        python_executable=sys.executable,python_prefix=sys.prefix)
    if proofs:
        with output_workspace(args.output_dir) as (output,stage):
            report['change']=rewrite(parent,stage/'dqi.kmb',proofs,allow_classical_guards=args.classical_guards)
            import kickmix as km
            circuit=km.Circuit.from_file(stage/'dqi.kmb')
            report['output_operation_statistics']=dict(circuit.operation_statistics())
            if circuit.num_qubits!=report['change']['qubits']:raise AssertionError('Qubit header changed')
        report['artifacts']=[{'path':'dqi.kmb','sha256':sha256(output/'dqi.kmb')}]
        report['decision']='plausible_gain_requires_full_verification'
    else:report['decision']='screened_out_no_proved_reduction'
    if sha256(parent)!=parent_hash:raise RuntimeError('Parent changed during transformation')
    for src in [source,Path(__file__),Path(__file__).with_name('generate.py')]:shutil.copy2(src,code/src.name)
    report['elapsed_seconds']=time.monotonic()-start
    (candidate/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
