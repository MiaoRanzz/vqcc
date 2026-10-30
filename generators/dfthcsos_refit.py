"""Bounded fixed-word weight refit with exact-metric inequality penalties.

This is a numerical screen/generator. Promotion requires the unchanged official
pipeline. The solver uses deterministic augmented Lagrangian stages and retains
all checkpoints; it never selects verifier randomness.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import time
from dataclasses import replace
from generate import sha256,output_workspace
import numpy as np
from scipy.optimize import minimize
from dfthcsos_fixed_words import from_inputs,near_identity_rank_drop
from dfthcsos.verify import load_inputs,evaluate_words,resource_costs,passes_accuracy
from dfthcsos.scoreinfra.circuits import load_circuits,circuit_costs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--cache',type=Path)
    p.add_argument('--initial',type=Path)
    p.add_argument('--drop-one-column',action='store_true',help='Construct the deterministic near-identity rank-drop start from the explicit parent')
    p.add_argument('--iterations',type=int,default=500)
    p.add_argument('--penalties',type=float,nargs='+',default=[10,100,1000,10000])
    p.add_argument('--stop-by',required=True)
    p.add_argument('--stage-dir',type=Path,required=True)
    args=p.parse_args();start=time.monotonic();stop=datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None:raise ValueError('stop-by must include timezone')
    args.stage_dir.mkdir(parents=True,exist_ok=True)
    source=args.parent_output/'submission.npz';arrays=dict(np.load(source,allow_pickle=False));inputs=load_inputs(source)
    model=from_inputs(inputs,arrays,dict(np.load(args.cache)) if args.cache else None)
    if args.initial and args.drop_one_column:
        raise ValueError('Choose either a saved initial point or --drop-one-column')
    if args.initial:
        init=dict(np.load(args.initial));w=init['w'];d=init['d']
    elif args.drop_one_column:
        w,d,_,_=near_identity_rank_drop(inputs.w,inputs.W,model.ar)
    else:w,d=inputs.w.copy(),inputs.W.copy()
    shape=w.shape;split=w.size
    def unpack(x):return x[:split].reshape(shape),x[split:].reshape(shape[0],shape[2])
    def pack(w,d):return np.r_[w.ravel(),d.ravel()]
    x=pack(w,d);mu=np.zeros(3);calls=0;best=None;best_metric=None;history=[];last_time=0
    error_limit=.01999990;gap_floor=3.9148990
    trace=(args.stage_dir/'trace.jsonl').open('w')
    class Deadline(Exception):pass
    def constraints(m):
        return np.array([(m['error_1']/error_limit)**2-1,(m['error_2']/error_limit)**2-1,(gap_floor-m['E_gap'])/.1])
    def eligible(m):return m['error_1']<=.02 and m['error_2']<=.02 and m['E_gap']>3.914898 and m['E_gap']<2*m['Lambda'] and m['Lambda']>49
    initial_metrics=model.evaluate(w,d)
    if eligible(initial_metrics):best=x.copy();best_metric=initial_metrics
    last_x=x.copy();last_m=initial_metrics
    try:
        for stage,rho in enumerate(args.penalties):
            stage_start=time.monotonic();stage_calls=0
            def fun(xx):
                nonlocal calls,best,best_metric,last_x,last_m,last_time,stage_calls
                if datetime.now(timezone.utc)>=stop:raise Deadline()
                ww,dd=unpack(xx);m,grads=model.evaluate(ww,dd,True)
                g=constraints(m);active=np.maximum(mu+rho*g,0)
                lam,gap=m['Lambda'],m['E_gap']
                obj=gap*(2*lam-gap)/48.3**2+(np.sum(active**2)-np.sum(mu**2))/(2*rho)
                lw,ld=grads['Lambda'];ew,ed=grads['E_gap']
                gw=(2*gap*lw+2*(lam-gap)*ew)/48.3**2
                gd=(2*gap*ld+2*(lam-gap)*ed)/48.3**2
                for weight,key,scale in zip(active,['error_1_squared','error_2_squared','E_gap'],[1/error_limit**2,1/error_limit**2,-10.]):
                    a,b=grads[key];gw+=weight*scale*a;gd+=weight*scale*b
                calls+=1;stage_calls+=1;last_x=xx.copy();last_m=m
                if eligible(m) and (best_metric is None or m['lambda_eff']<best_metric['lambda_eff']):
                    best=xx.copy();best_metric=m.copy()
                if calls%50==0:
                    row=dict(stage=stage,rho=rho,calls=calls,elapsed_seconds=time.monotonic()-start,objective=float(obj),constraints=g.tolist(),metrics=m,best=best_metric)
                    trace.write(json.dumps(row)+'\n');trace.flush();print(json.dumps(row),flush=True)
                if time.monotonic()-last_time>60:
                    np.savez(args.stage_dir/'latest.npz',w=ww,d=dd)
                    if best is not None:
                        bw,bd=unpack(best);np.savez(args.stage_dir/'best.npz',w=bw,d=bd)
                    last_time=time.monotonic()
                return obj,pack(gw,gd)
            result=minimize(fun,x,jac=True,method='L-BFGS-B',options=dict(maxiter=args.iterations,maxls=40,maxcor=20,ftol=1e-14,gtol=1e-9))
            x=result.x;m=model.evaluate(*unpack(x));g=constraints(m);mu=np.maximum(0,mu+rho*g)
            ww,dd=unpack(x);np.savez(args.stage_dir/f'stage-{stage}.npz',w=ww,d=dd)
            row=dict(stage=stage,rho=rho,iterations=int(result.nit),calls=stage_calls,message=str(result.message),metrics=m,constraints=g.tolist(),multipliers=mu.tolist(),elapsed_seconds=time.monotonic()-stage_start)
            history.append(row);print('STAGE '+json.dumps(row),flush=True)
    except Deadline:
        x=last_x
        history.append(dict(deadline=True,calls=calls,metrics=last_m))
    finally:trace.close()
    chosen=best if best is not None else x
    w,d=unpack(chosen);arrays['W']=w;arrays['H2_I']=d+w.sum(axis=1)
    if 'offset_W' in arrays:arrays['offset_W']=d
    with output_workspace(args.output_dir) as (output,stage):
        np.savez(stage/'submission.npz',**arrays)
        for f in args.parent_output.glob('angle_k_*.kmb'):shutil.copy2(f,stage/f.name)
    # Official numerical check is separate from the reduced screening model.
    final_inputs=replace(inputs,params=arrays,w=w,W=d,factorization_file=output/'submission.npz')
    metrics=evaluate_words(final_inputs,arrays['angle_words'],arrays['tree_edges'],int(arrays['brot']))
    predicted=model.evaluate(w,d)
    assert all(abs(metrics[k]-predicted[k])<2e-8 for k in predicted),(metrics,predicted)
    circuits=load_circuits(output);stats=circuit_costs(circuits)
    resources=resource_costs(final_inputs,circuits,int(arrays['brot']),2*sum(s['max_magic'] for s in stats))
    code=output.parent/'code';code.mkdir(exist_ok=True)
    for f in [Path(__file__),Path(__file__).with_name('dfthcsos_fixed_words.py')]:shutil.copy2(f,code/f.name)
    report=dict(kind='fixed_word_augmented_lagrangian_refit',official_validation=False,source_npz=str(source.resolve()),source_sha256=sha256(source),generator_sha256=sha256(Path(__file__)),model_sha256=sha256(Path(__file__).with_name('dfthcsos_fixed_words.py')),argv=sys.argv,python_executable=sys.executable,python_prefix=sys.prefix,initial_metrics=initial_metrics,metrics=metrics,predicted_metrics=predicted,resources=resources,passes_numerical_gates=passes_accuracy(metrics),conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'],best_feasible_found=best is not None,calls=calls,stages=history,elapsed_seconds=time.monotonic()-start,artifacts=[dict(path=f.name,sha256=sha256(f)) for f in sorted(output.iterdir())],input_cache_sha256=sha256(args.cache) if args.cache else None,initial_sha256=sha256(args.initial) if args.initial else None)
    (output.parent/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FINAL '+json.dumps({k:report[k] for k in ['metrics','resources','conditional_cost','passes_numerical_gates','best_feasible_found','calls','elapsed_seconds']}),flush=True)

if __name__=='__main__':main()
