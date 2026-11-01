"""Replace proved three-input borrowed-wire AND uncomputes with HMR/CCZ.

Method: manwithacat's public HW-06, independently implemented for any pinned
version-2 artifact. The existing conservative Boolean tracker proves the target
is zero after each four-CCX block. Only contiguous unconditional blocks on five
distinct wires qualify. Arbitrary dirty borrowing is restored; the conditional
CCZ repays the measured three-input phase. No sampled truth values enter proofs.
Full official validation and the pipeline's robustness gate remain required.
"""
from __future__ import annotations
import argparse,json,shutil,struct,subprocess,sys,time
from pathlib import Path
import numpy as np
from dqi_boolean_reduce import read_binary,read_proofs,compile_scanner,NAMES,MAGIC
from generate import output_workspace,sha256


def rewrite(source,destination,proofs):
    data=read_binary(source);old=data['packets'];types=old['types']
    proofs=sorted(proofs,key=lambda x:x['op']);ops=np.array([p['op'] for p in proofs],dtype=np.int64)
    if not len(ops):raise ValueError('No proved blocks')
    if ops[0]<0 or ops[-1]+3>=len(types) or np.any(np.diff(ops)<4):raise ValueError('Overlapping/out-of-range blocks')
    positions={}
    for names,mask in [(['a3','b3','t3'],(types&0x30)==0x30),(['a2','t2'],(types&0x30)==0x20),(['q'],(types&0x30)==0x10),(['bit'],(types&0x40)!=0),(['condition'],(types&0x80)!=0)]:
        rank=np.searchsorted(np.flatnonzero(mask),ops)
        for name in names:positions[name]=rank
    # The scanner attests global clean-target semantics; recheck the exact local
    # pattern and operands here before touching the binary streams.
    replacements=[]
    for j,p in enumerate(proofs):
        start=int(ops[j]);k=int(positions['a3'][j])
        gates=[tuple(int(old[n][k+i]) for n in ('a3','b3','t3')) for i in range(4)]
        A,B=gates[:2];a,b,d=A;d2,c,t=B
        if p['kind']!='borrowed3' or not np.all(types[start:start+4]==0x31):raise ValueError('Expected four unconditional CCX gates')
        if gates!=[A,B,A,B] or d!=d2 or len({a,b,c,d,t})!=5:raise ValueError('Borrowed AND pattern mismatch')
        if (p['a'],p['b'],p['target'])!=(a,b,t):raise ValueError('Proof operand mismatch')
        bit=data['nb']+j
        replacements.append(dict(types=[0x50,0xb0],q=[t],bit=[bit],a3=[a],b3=[b],t3=[c],condition=[bit]))
    changed={}
    for name in NAMES[:9]:
        arr=old[name];rank=ops if name=='types' else positions[name];parts=[];last=0
        for pos,replacement in zip(rank,replacements):
            pos=int(pos);remove=4 if name in ('types','a3','b3','t3') else 0
            parts.extend([arr[last:pos],np.asarray(replacement.get(name,[]),dtype=arr.dtype)]);last=pos+remove
        parts.append(arr[last:]);changed[name]=np.concatenate(parts)
    newbits=data['nb']+len(proofs)
    largest=max((int(changed[n].max()) for n in ('a3','b3','t3','a2','t2','q') if len(changed[n])),default=-1)
    if data['nq'] and largest<data['nq']-1:
        changed['types']=np.r_[changed['types'],np.array([0x11,0x11],dtype=np.uint8)]
        changed['q']=np.r_[changed['q'],np.array([data['nq']-1]*2,dtype='<u4')]
    counts=data['counts'].copy();counts[:6]=[len(changed[n]) for n in ('types','a3','a2','q','bit','condition')]
    with Path(destination).open('wb') as out:
        out.write(MAGIC);out.write(struct.pack('<4I',2,data['nq'],newbits,data['nr']));out.write(struct.pack('<9Q',*counts));out.write(data['registers'])
        for i,name in enumerate(NAMES,1):
            payload=changed.get(name,old[name]);out.write(struct.pack('<2Q',i,payload.nbytes));out.write(payload.tobytes())
    return dict(blocks=len(proofs),qubits=data['nq'],fresh_measurement_bits=len(proofs),static_toffoli_reduction=3*len(proofs),expected_mean_toffoli_reduction=3.5*len(proofs))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--expected-parent-sha256',required=True)
    p.add_argument('--term-cap',type=int,default=512)
    p.add_argument('--timeout-seconds',type=int,default=180)
    args=p.parse_args();started=time.monotonic()
    if not 1<=args.term_cap<=4096:p.error('Term cap must be in1..4096')
    parent=args.parent_output/'dqi.kmb'
    if sha256(parent)!=args.expected_parent_sha256:p.error('Pinned parent changed')
    candidate=args.output_dir.parent;screen=candidate/'screen';screen.mkdir(exist_ok=True);code=candidate/'code';code.mkdir(exist_ok=True)
    for name in ['dqi_borrowed_uncompute.py','dqi_boolean_reduce.py','dqi_boolean_screen.cpp','generate.py']:
        shutil.copy2(Path(__file__).with_name(name),code/name)
    scanner=screen/'borrowed-scanner';source,compile_command=compile_scanner(scanner,code/'dqi_boolean_screen.cpp')
    proofs_path=screen/'borrowed-proofs.tsv';summary=screen/'borrowed-summary.json'
    command=[str(scanner),str(parent),str(proofs_path),str(summary),str(args.term_cap),'0','0','1']
    with (screen/'scanner.log').open('w') as log:subprocess.run(command,check=True,stderr=log,timeout=args.timeout_seconds)
    proofs=read_proofs(proofs_path)
    report=dict(kind='proved_borrowed_three_and_uncompute',official_validation=False,source_generator_available=False,parent_output=str(args.parent_output.resolve()),parent_sha256=sha256(parent),parameters=dict(term_cap=args.term_cap,mode='unconditional_contiguous_borrowed3'),method_source='https://www.kaggle.com/code/manwithacat/vqcc-hedge-wizardry-notebook (HW-06 v5)',implementation='Independent sound symbolic proof and KMB transformation; no copied public implementation',argv=sys.argv,python=sys.executable,prefix=sys.prefix,compile_command=compile_command,screen_command=command,proof_sha256=sha256(proofs_path),screen=json.loads(summary.read_text()),generator_sha256=sha256(code/'dqi_borrowed_uncompute.py'),scanner_sha256=sha256(source))
    if proofs:
        with output_workspace(args.output_dir) as (output,stage):report['change']=rewrite(parent,stage/'dqi.kmb',proofs)
        report['artifacts']=[dict(path='dqi.kmb',sha256=sha256(output/'dqi.kmb'))]
        report['decision']='plausible_gain_requires_full_official_verification'
    else:report['decision']='rejected_no_proved_blocks'
    if sha256(parent)!=args.expected_parent_sha256:raise RuntimeError('Parent changed during build')
    report['elapsed_seconds']=time.monotonic()-started
    (candidate/'generation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
