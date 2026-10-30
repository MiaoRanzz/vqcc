"""Screen rank truncation in the physical two-body factors decoded from words.

Each group's X has shape [C,N*N]. Its left singular vectors define an exact
column gauge before dropping the weakest directions. This minimizes the
per-group two-body Gram truncation error (Eckart-Young); it does not minimize
the combined residual, one-body error, or LCU normalization after truncation.
A failed screen rules out this unrefitted recipe, not joint low-rank fitting.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time

from generate import sha256, output_workspace
import numpy as np
from dfthcsos.scoreinfra.dfthc_math import reconstruct_x, reconstruct_u_vectors
from dfthcsos.verify import load_inputs, evaluate_words, passes_accuracy, resource_costs
from dfthcsos.scoreinfra.circuits import load_circuits,circuit_costs


def truncate_factors(w,h,u,rank):
    if w.ndim != 3 or h.shape != (w.shape[0],w.shape[2]) or not 0 < rank < w.shape[2]:
        raise ValueError('Rank must be positive and smaller than the current column count')
    x=reconstruct_x(u,w).reshape(w.shape[0],w.shape[2],-1)
    left,singular,_=np.linalg.svd(x,full_matrices=False)
    q=left[:,:,:rank]
    return w@q,(h[:,None,:]@q)[:,0,:],dict(
        singular_values=singular.tolist(),rank_before=w.shape[2],rank_after=rank,
        per_group_two_body_truncation_frobenius=np.sqrt(np.sum(singular[:,rank:]**4,axis=1)).tolist(),
        note='Per-group optimal truncation only; combined residual and full cost require numerical evaluation'),q


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--rank',type=int,required=True)
    args=p.parse_args();start=time.monotonic();source=args.parent_output/'submission.npz'
    with np.load(source,allow_pickle=False) as d:arrays={k:np.array(d[k]) for k in d.files}
    brot=int(arrays['brot']);n=arrays['U'].shape[-1];r,b,_=arrays['W'].shape
    # Match evaluate_dfthc_angle_words: words are unsigned full-turn integers.
    vectors=reconstruct_u_vectors(arrays['angle_words'].astype(float)/2**(brot-1),arrays['tree_edges'])
    arrays['W'],arrays['H2_I'],screen,q=truncate_factors(arrays['W'],arrays['H2_I'],vectors[n:].reshape(r,b,n),args.rank)
    if 'offset_W' in arrays:arrays['offset_W']=arrays['H2_I']-arrays['W'].sum(axis=1)
    with output_workspace(args.output_dir) as (output,stage):
        np.savez(stage/'submission.npz',**arrays)
        for f in args.parent_output.glob('angle_k_*.kmb'):shutil.copy2(f,stage/f.name)
    inputs=load_inputs(output/'submission.npz')
    metrics=evaluate_words(inputs,arrays['angle_words'],arrays['tree_edges'],brot)
    circuits=load_circuits(output);stats=circuit_costs(circuits)
    resources=resource_costs(inputs,circuits,brot,2*sum(s['max_magic'] for s in stats))
    np.save(output.parent/'column_projection.npy',q)
    code=output.parent/'code';code.mkdir(exist_ok=True);shutil.copy2(__file__,code/Path(__file__).name)
    report=dict(kind='physical_factor_rank_truncation_screen',official_validation=False,
        source_npz=str(source.resolve()),source_sha256=sha256(source),generator_sha256=sha256(Path(__file__)),
        argv=sys.argv,python_executable=sys.executable,python_prefix=sys.prefix,
        created_at=datetime.now(timezone.utc).isoformat(),screen=screen,metrics=metrics,resources=resources,
        passes_numerical_gates=passes_accuracy(metrics),conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'],
        elapsed_seconds=time.monotonic()-start,artifacts=[dict(path=f.name,sha256=sha256(f)) for f in sorted(output.iterdir())])
    (output.parent/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('screen','artifacts')},indent=2))


if __name__=='__main__':main()
