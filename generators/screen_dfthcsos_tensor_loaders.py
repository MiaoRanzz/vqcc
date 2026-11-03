# SPDX-License-Identifier: Apache-2.0
"""Static per-slot Toffoli screen of the pinned public tensorqrom loader compiler (no simulation).

Compiles the ANGLE_k loader for selected batches of a submission.npz word table with
Marculera tensorqrom (dfthc-merge-pipeline, Apache-2.0, sha256 2518358332cd...) using the
same coded-layout rules as its build_family, and prints products/Toffolis/qubits per slot.
Usage: screen_dfthcsos_tensor_loaders.py NPZ K[,K...] TRIALS [OUT.json]
No official PASS is claimed; compare against the parent family with circuit_costs.
"""
import sys, time, json, os, hashlib, importlib
from pathlib import Path
ROOT=Path('/home/ubuntu/miaoran/project/vqcc')
BANK=ROOT/'artifacts/inputs/public/scan-20261103-63589e/marculera_dfthc-merge-pipeline/dfthc_refit'
assert hashlib.sha256((BANK/'tensorqrom.py').read_bytes()).hexdigest().startswith('2518358332cd')
sys.path[:0]=[str(ROOT/'kickmix'),str(ROOT/'verifiers'),str(BANK)]
import numpy as np
tq=importlib.import_module('tensorqrom'); fq=importlib.import_module('fourqrom')
npz=Path(sys.argv[1]); ks=[int(x) for x in sys.argv[2].split(',')]; trials=int(sys.argv[3])
w=np.load(npz)['angle_words'].astype(np.int64); brot=8; J=5
sg=((w>>(brot-1))^(w>>(brot-2)))&1
print('signed gauge violations',int(sg.sum()))
A=len(w)
def affine_ok(col):
    b=col&1; L=16
    affs=np.array([[c^(bin(m&a).count('1')&1) for a in range(16)] for c in (0,1) for m in range(16)])
    for s in range(0,A,16):
        seg=b[s:s+16]; n=len(seg)
        if not np.any(np.all(affs[:,:n]==seg,axis=1)): return False
    return True
coded=[c for c in range(75) if affine_ok(w[:,c])]
print('coded cols',len(coded),coded)
deltas=list(fq.batch_deltas(w,J)); n_sel=(A-1).bit_length()
res={}
for k in ks:
    t=time.time(); d=deltas[k]
    cw=[i for i in range(d.shape[1]) if J*k+i in coded and (k==0 or J*(k-1)+i in coded)]
    perm,sz=tq.coded_layout(cw,d.shape[1],brot)
    if cw: d=tq.pad_affine(d,cw)
    terms,grouped=tq._one((d,n_sel,brot,4,sz,trials,k,perm))
    c=(tq.build_circuit(d,terms,n_sel,brot,4,groups=tq.low_groups(4),scratch=True) if grouped else tq.build_circuit(d,terms,n_sel,brot,4))
    st=c.operation_statistics()
    res[k]=dict(coded_words=cw,products=len(terms),toffoli=int(st.num_toffoli_like),qubits=c.num_qubits,grouped=grouped,seconds=round(time.time()-t,1))
    print(k,res[k],flush=True)
if len(sys.argv)>4: json.dump(res,open(sys.argv[4],'w'),indent=1)
