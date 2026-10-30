"""Rebuild selected derivative v2 ANGLE circuits from coefficient plans.
The native emitter is our independently checked implementation of credited
paired-product/sign-borrowing methods. No teacherKMB or gated tensors are read.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
import kickmix as km
KEEP=sum(127<<(8*j) for j in range(5))

def bits(value):
    while value:
        low = value & -value
        yield low.bit_length() - 1
        value ^= low

def sign_encoded(value):
    return all(((value>>(8*j+6))&1)==((value>>(8*j+7))&1) for j in range(5))

def emit_native(products,pure,A=1220):
    masks=[m for m in range(1,A) if m<16 or m%16==0]
    b = km.CircuitBuilder()
    selection = b.create_quantum_register(11,'selection')
    words = [b.create_quantum_register(8,f'word_{j}') for j in range(5)]
    targets = [q for word in words for q in word]
    for word in words:b.cx(word[6],word[7])
    cache = {1<<i:q for i,q in enumerate(selection)}
    high = [m for m in masks if m>=16 and m.bit_count()>=2]
    low = [m for m in masks if m<16 and m.bit_count()>=2]
    assert len(high)==69 and len(low)==11
    high_qubits = b.alloc_qubits(69)
    low_extra = b.alloc_qubits(6)
    for m,q in zip(high,high_qubits):
        top=1<<(m.bit_length()-1);b.init_and(cache[m^top],cache[top],q);cache[m]=q
    for m,q in zip(low,[word[7] for word in words]+list(low_extra)):
        top=1<<(m.bit_length()-1);b.init_and(cache[m^top],cache[top],q);cache[m]=q
    for p in products:
        def wires(form):
            return {cache[m].id for m in bits(form['low'])}|{cache[h<<4].id for h in bits(form['high'])}
        aa,bb=wires(p['a']),wires(p['b'])
        assert aa and bb and aa!=bb
        pivot=min(aa);intersects=pivot in bb;other=bb^aa if intersects else bb
        second=min(other)
        inv=[(q,pivot) for q in sorted(aa-{pivot})]+[(q,second) for q in sorted(other-{second})]
        if intersects:inv.append((pivot,second))
        for src,dst in inv:b.cx(km.q(src),km.q(dst))
        fan=list(bits(p['fanout']&KEEP));target=targets[fan[0]]
        for k in fan[1:]:b.cx(target,targets[k])
        b.ccx(km.q(pivot),km.q(second),target)
        for k in fan[1:]:b.cx(target,targets[k])
        for src,dst in reversed(inv):b.cx(km.q(src),km.q(dst))
    for m,fanout in pure.items():
        for k in bits(fanout&KEEP):
            if m==0:b.x(targets[k])
            else:b.cx(cache[m],targets[k])
    for m in reversed(low):
        top=1<<(m.bit_length()-1);b.del_and(cache[m^top],cache[top],cache[m])
    for m in reversed(high):
        top=1<<(m.bit_length()-1);b.del_and(cache[m^top],cache[top],cache[m])
    b.free(low_extra);b.free(high_qubits)
    for word in words:b.cx(word[6],word[7])
    c=b.finish_circuit()
    assert c.num_qubits==126 and int(c.operation_statistics().num_toffoli_like)==80+len(products)
    return c

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parent
    mp=root/'MANIFEST.json'
    if not mp.exists():mp=root/'STAGING_MANIFEST.json'
    manifest=json.loads(mp.read_text())
    for name,digest in manifest['files'].items():
        if name.startswith('plans/') or name in ['factorization.npz','rebuild_native.py']:
            assert sha(root/name)==digest,name
    a.out.mkdir(parents=True,exist_ok=False);out=a.out/'dfthcsos';out.mkdir()
    shutil.copyfile(root/'factorization.npz',out/'submission.npz');rows=[]
    for k in range(15):
        data=json.loads((root/'plans'/f'batch_{k}.json').read_text());products=data['products'];pure={int(m):v for m,v in data['pure'].items()}
        assert len(products)<400 and all(0<=m<1220 and (m<16 or m%16==0) and sign_encoded(v) for m,v in pure.items())
        for prod in products:
            assert 0<prod['fanout']<2**40 and sign_encoded(prod['fanout'])
            for form in [prod['a'],prod['b']]:assert 0<=form['low']<2**16 and 0<=form['high']<2**77 and not(form['high']&1)
        c=emit_native(products,pure);dest=out/f'angle_k_{k}.kmb';c.to_file(dest,format='kmb')
        digest=sha(dest);assert digest==manifest['native_circuit_hashes'][dest.name]
        rows.append(dict(batch=k,T=int(c.operation_statistics().num_toffoli_like),Q=c.num_qubits,sha256=digest))
    assert sha(out/'submission.npz')==manifest['selected_factor_sha256']
    audit=dict(status='EXACT_NATIVE_REBUILD_PASS',rows=rows,T_per_pass=sum(r['T'] for r in rows),teacher_bytes_read=False,
        selected_factor_sha256=sha(out/'submission.npz'),scope='Byte identity only; native/full-chemistry receipts are separate')
    (a.out/'rebuild_audit.json').write_text(json.dumps(audit,indent=2)+'\n');print(json.dumps(audit))

if __name__=='__main__':main()
