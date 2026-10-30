"""Joint-column orthogonal gauges using squared-L1 proximal steps and ADMM.

Independent implementation. For A=[W; H2_I], A Q with orthogonal Q preserves
A A.T and the represented Hamiltonian, while sum_c ||A[:,c]||_1**2 may fall.
The nonconvex ADMM search is a heuristic, not a global optimality certificate.
Only exact orthogonal iterates (never the sparse auxiliary) become candidates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time

from generate import output_workspace, sha256
import numpy as np
from dfthcsos.verify import load_inputs, evaluate_words, passes_accuracy, resource_costs
from dfthcsos.scoreinfra.circuits import load_circuits, circuit_costs


def objective(a):
    return np.sum(np.sum(np.abs(a), axis=-2)**2, axis=-1) / 4


def prox_squared_l1(v, rho):
    """argmin_x ||x||_1**2/4 + rho/2 ||x-v||_2**2, columnwise.

    The KKT threshold is t=sum_active(abs(v))/(2*rho+k). Sorting finds the
    active set exactly, including zero columns and repeated magnitudes.
    """
    if not np.isfinite(rho) or rho <= 0:
        raise ValueError('rho must be positive and finite')
    magnitudes = np.abs(v)
    ordered = np.sort(magnitudes, axis=-2)[..., ::-1, :]
    k = np.arange(1, v.shape[-2]+1).reshape((-1, 1))
    thresholds = np.cumsum(ordered, axis=-2) / (2*rho+k)
    # Threshold candidates increase until the correct active set, then decrease.
    threshold = np.max(thresholds, axis=-2, keepdims=True)
    return np.sign(v) * np.maximum(magnitudes-threshold, 0)


def polar(matrix):
    u, _, vh = np.linalg.svd(matrix, full_matrices=False)
    return u @ vh


def optimize_gauge(a, penalties, iterations, stop_by=None, record_every=25):
    a = np.array(a, dtype=np.float64, copy=True)
    if a.ndim != 3 or not np.isfinite(a).all():
        raise ValueError('Expected finite [group,row,column] factors')
    if iterations < 1 or not penalties or any(p <= 0 for p in penalties):
        raise ValueError('Positive iteration count and penalties required')
    before = objective(a)
    best, best_cost = a.copy(), before.copy()
    best_q = np.broadcast_to(np.eye(a.shape[-1]), (len(a),a.shape[-1],a.shape[-1])).copy()
    best_at = [dict(penalty=None, iteration=0) for _ in a]
    traces, complete = [], True
    for rho in penalties:
        # Each predeclared penalty starts at the same parent, no RNG selection.
        z, dual, current = a.copy(), np.zeros_like(a), a.copy()
        q = best_q.copy()
        trial = dict(penalty=rho, history=[])
        for iteration in range(1, iterations+1):
            if stop_by and datetime.now(timezone.utc) >= stop_by:
                complete = False
                break
            z_old = z
            z = prox_squared_l1(current+dual, rho)
            q = polar(a.swapaxes(-1,-2) @ (z-dual))
            current = a @ q
            dual += current-z
            values = objective(current)
            better = values < best_cost
            best[better], best_cost[better], best_q[better] = current[better], values[better], q[better]
            for group in np.flatnonzero(better):
                best_at[group] = dict(penalty=rho, iteration=iteration)
            if iteration == 1 or iteration % record_every == 0 or iteration == iterations:
                trial['history'].append(dict(iteration=iteration,
                    objective=float(values.sum()), best_objective=float(best_cost.sum()),
                    primal_norm=float(np.linalg.norm(current-z)),
                    dual_norm=float(rho*np.linalg.norm(z-z_old))))
        trial['iterations_completed'] = iteration if complete else iteration-1
        traces.append(trial)
        print(json.dumps(dict(penalty=rho,iterations=trial['iterations_completed'],
            best_lambda_h2=float(best_cost.sum()), reduction=float(before.sum()-best_cost.sum()))),flush=True)
        if not complete: break
    gram = a @ a.swapaxes(-1,-2)
    drift = float(np.max(np.abs(gram-best @ best.swapaxes(-1,-2))))
    orthogonality = float(np.max(np.abs(best_q.swapaxes(-1,-2) @ best_q-np.eye(a.shape[-1]))))
    if drift > 1e-10*max(1.,float(np.max(np.abs(gram)))) or orthogonality > 1e-10:
        raise ValueError('Orthogonal gauge invariant failed')
    return best, best_q, dict(complete=complete,method='squared_l1_proximal_polar_admm',
        penalties=penalties,iterations=iterations,lambda_h2_before=float(before.sum()),
        lambda_h2_after=float(best_cost.sum()),group_before=before.tolist(),
        group_after=best_cost.tolist(),best_at=best_at,gram_max_abs_drift=drift,
        orthogonality_max_abs=orthogonality,trials=traces)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--penalties',type=float,nargs='+',default=[0.1,1,10,100,1000])
    p.add_argument('--iterations',type=int,default=500)
    p.add_argument('--stop-by',type=datetime.fromisoformat,required=True)
    args=p.parse_args(); start=time.monotonic()
    if args.stop_by.tzinfo is None: p.error('stop-by must have a timezone')
    source=args.parent_output/'submission.npz'
    with np.load(source,allow_pickle=False) as data:
        arrays={k:np.array(data[k]) for k in data.files}
    a=np.concatenate([arrays['W'],arrays['H2_I'][:,None,:]],axis=1)
    improved,q,search=optimize_gauge(a,args.penalties,args.iterations,args.stop_by)
    arrays['W'],arrays['H2_I']=improved[:,:-1,:],improved[:,-1,:]
    if 'offset_W' in arrays:
        arrays['offset_W']=arrays['H2_I']-arrays['W'].sum(axis=1)
    with output_workspace(args.output_dir) as (output,stage):
        np.savez(stage/'submission.npz',**arrays)
        for f in sorted(args.parent_output.glob('angle_k_*.kmb')):
            shutil.copy2(f,stage/f.name)
    # Keep numerical feasibility and full circuit verification distinct.
    brot=int(arrays.get('brot',8))
    inputs=load_inputs(output/'submission.npz')
    metrics=evaluate_words(inputs,arrays['angle_words'],arrays['tree_edges'],brot)
    circuits=load_circuits(output);stats=circuit_costs(circuits)
    resources=resource_costs(inputs,circuits,brot,2*sum(s['max_magic'] for s in stats))
    np.save(output.parent/'orthogonal_gauges.npy',q)
    code=output.parent/'code';code.mkdir(exist_ok=True)
    shutil.copy2(__file__,code/Path(__file__).name)
    report=dict(kind='joint_column_polar_gauge_screen',official_validation=False,
        source_npz=str(source.resolve()),source_sha256=sha256(source),
        generator_sha256=sha256(Path(__file__)),python_executable=sys.executable,python_prefix=sys.prefix,
        argv=sys.argv,created_at=datetime.now(timezone.utc).isoformat(),search=search,
        metrics=metrics,resources=resources,passes_numerical_gates=passes_accuracy(metrics),
        conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'],
        elapsed_seconds=time.monotonic()-start,
        artifacts=[dict(path=f.name,sha256=sha256(f)) for f in sorted(output.iterdir())])
    (output.parent/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['search','artifacts']},indent=2))


if __name__=='__main__': main()
