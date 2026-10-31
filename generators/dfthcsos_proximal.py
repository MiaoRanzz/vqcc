"""Sign-aware constrained proximal steps for fixed-word DFTHC weights.

Use a weighted L1 local model of Lambda and solve its three-dimensional dual
on the constraint tangent plane. Newton retraction keeps newly zero entries at
zero; subsequent proximal steps may reactivate them. Accept only actual Lambda
decrease with the official residual/gap equalities. Numerical screening only.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import time
import numpy as np


def soft_threshold(x,threshold):
    return np.sign(x)*np.maximum(np.abs(x)-threshold,0)


def tangent_prox(x,gradient,weights,jac,step,tolerance=1e-11,max_iterations=60):
    """Solve a convex weighted-L1 proximal model with J(y-x)=0."""
    norms=np.linalg.norm(jac,axis=1)
    u=jac/norms[:,None]
    smooth=gradient-weights*np.sign(x)
    dual=-np.linalg.solve(u@u.T,u@gradient)
    def evaluate(lam):
        z=x-step*(smooth+u.T@lam)
        y=soft_threshold(z,step*weights)
        return y,u@(y-x),np.abs(z)>step*weights
    for iteration in range(max_iterations):
        y,residual,active=evaluate(dual)
        norm=float(np.linalg.norm(residual))
        if norm<tolerance:
            return y,dict(iterations=iteration,residual_norm=norm,active=int(active.sum()),dual=dual.tolist())
        v=u[:,active]
        delta=np.linalg.lstsq(v@v.T,residual/step,rcond=1e-12)[0]
        for k in range(24):
            trial=dual+2.**(-k)*delta
            if np.linalg.norm(evaluate(trial)[1])<norm:
                dual=trial;break
        else:
            return None,dict(iterations=iteration,residual_norm=norm,status='dual_stalled')
    return None,dict(iterations=max_iterations,residual_norm=norm,status='dual_iteration_limit')


def main():
    from generate import sha256,output_workspace
    from dfthcsos_fixed_words import from_inputs
    from dfthcsos.verify import load_inputs,evaluate_words,passes_accuracy,resource_costs
    from dfthcsos.scoreinfra.circuits import load_circuits,circuit_costs
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--iterations',type=int,default=500)
    p.add_argument('--initial-step',type=float,default=1e-4)
    p.add_argument('--step-growth',type=float,default=2.)
    p.add_argument('--initial',type=Path)
    p.add_argument('--stall-window',type=int,default=20)
    p.add_argument('--minimum-lambda-progress',type=float,default=1e-8)
    p.add_argument('--stop-by',required=True)
    args=p.parse_args();start=time.monotonic();stop=datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None:raise ValueError('Timezone required')
    source=args.parent_output/'submission.npz';arrays=dict(np.load(source,allow_pickle=False));inputs=load_inputs(source)
    model=from_inputs(inputs,arrays,dict(np.load(args.cache)))
    shape=inputs.w.shape;size=inputs.w.size
    def pack(w,h):return np.r_[w.ravel(),h.ravel()]
    def unpack(x):
        w=x[:size].reshape(shape);h=x[size:].reshape(shape[0],shape[2]);return w,h-w.sum(axis=1)
    x=pack(inputs.w,arrays['H2_I'])
    if args.initial:
        initial=dict(np.load(args.initial,allow_pickle=False))
        x=pack(initial['w'],initial['d']+initial['w'].sum(axis=1))
    target_error=.01999990;target_gap=3.9148990
    calls=0;accepted=0;best=x.copy();best_metrics=model.evaluate(*unpack(x));initial_metrics=best_metrics.copy()
    screen=args.output_dir.parent/'screen';screen.mkdir(exist_ok=True)
    trace=(screen/'trace.jsonl').open('w')
    class Deadline(Exception):pass
    def evalpoint(x):
        nonlocal calls
        if datetime.now(timezone.utc)>=stop:raise Deadline()
        w,d=unpack(x);m,g=model.evaluate(w,d,True);calls+=1
        def convert(key,scale):
            gw,gd=g[key];return pack(gw-gd[:,None,:],gd)*scale
        jac=np.array([convert('error_1_squared',1/target_error**2),convert('error_2_squared',1/target_error**2),convert('E_gap',10)])
        c=np.array([(m['error_1']/target_error)**2-1,(m['error_2']/target_error)**2-1,(m['E_gap']-target_gap)*10])
        h=d+w.sum(axis=1);l1=np.abs(w).sum(axis=1)+np.abs(h)
        weights=pack(np.broadcast_to(.5*l1[:,None,:],shape),.5*l1)/300
        return m['Lambda']/300,convert('Lambda',1/300),c,jac,m,weights
    def retract(y,steps=10):
        y=y.copy();active=y!=0
        for k in range(steps):
            info=evalpoint(y);f,g,c,jac,m,weights=info
            if np.max(np.abs(c))<2e-10:return y,info
            j=jac[:,active];norms=np.linalg.norm(j,axis=1);u=j/norms[:,None]
            y[active]-=u.T@np.linalg.solve(u@u.T,c/norms)
        return None,None
    step=args.initial_step;status='iteration_limit';total_zeroed=total_reactivated=0;recent_lambda=[]
    try:
        x,info=retract(x)
        if x is None:raise RuntimeError('Initial constraint retraction failed')
        for iteration in range(args.iterations):
            f,g,c,jac,m,weights=info
            if m['lambda_eff']<best_metrics['lambda_eff']:best=x.copy();best_metrics=m.copy()
            accepted_here=False
            for backtrack in range(24):
                y,prox=tangent_prox(x,g,weights,jac,step)
                if y is None:step*=.5;continue
                d=y-x;smooth=g-weights*np.sign(x)
                slope=float(smooth@d+weights@(np.abs(y)-np.abs(x)))
                if slope>=0:step*=.5;continue
                trial,trial_info=retract(y)
                if trial is not None and trial_info[0]<=f+1e-4*slope and trial_info[0]<f-1e-14:
                    accepted_here=True;break
                step*=.5
            if not accepted_here:status='line_search_stalled';break
            zeroed=int(np.count_nonzero((x!=0)&(trial==0)))
            reactivated=int(np.count_nonzero((x==0)&(trial!=0)))
            total_zeroed+=zeroed;total_reactivated+=reactivated
            row=dict(iteration=iteration,calls=calls,step=step,backtracks=backtrack,metrics=trial_info[4],
                     proximal=prox,zeroed=zeroed,reactivated=reactivated,zeros=int(np.count_nonzero(trial==0)),
                     elapsed_seconds=time.monotonic()-start)
            trace.write(json.dumps(row)+'\n');trace.flush()
            if iteration%10==0:
                print(json.dumps(row),flush=True);bw,bd=unpack(best);np.savez(screen/'best.npz',w=bw,d=bd)
            displacement=trial-x
            newg=trial_info[1]-trial_info[5]*np.sign(trial)
            curvature=float(displacement@(newg-smooth))
            if curvature>0:step=float(np.clip((displacement@displacement)/curvature,1e-8,min(10,step*args.step_growth)))
            else:step=min(10,step*1.5)
            x,info=trial,trial_info;accepted+=1
            recent_lambda.append(info[4]['Lambda'])
            if len(recent_lambda)>args.stall_window:
                recent_lambda=recent_lambda[-args.stall_window-1:]
                if recent_lambda[0]-recent_lambda[-1]<args.minimum_lambda_progress:
                    status='numerical_progress_stalled';break
        m=info[4]
        if m['lambda_eff']<best_metrics['lambda_eff']:best=x.copy();best_metrics=m.copy()
    except Deadline:status='bounded_deadline'
    finally:trace.close()
    w,d=unpack(best);arrays['W']=w;arrays['H2_I']=d+w.sum(axis=1)
    if 'offset_W' in arrays:arrays['offset_W']=d
    with output_workspace(args.output_dir) as (output,stage):
        np.savez(stage/'submission.npz',**arrays)
        for f in args.parent_output.glob('angle_k_*.kmb'):shutil.copy2(f,stage/f.name)
    final_inputs=replace(inputs,params=arrays,w=w,W=d,factorization_file=output/'submission.npz')
    metrics=evaluate_words(final_inputs,arrays['angle_words'],arrays['tree_edges'],int(arrays['brot']))
    assert all(abs(metrics[k]-best_metrics[k])<2e-8 for k in best_metrics),(metrics,best_metrics)
    circuits=load_circuits(output);stats=circuit_costs(circuits)
    resources=resource_costs(final_inputs,circuits,int(arrays['brot']),2*sum(s['max_magic'] for s in stats))
    code=output.parent/'code';code.mkdir(exist_ok=True)
    for f in [Path(__file__),Path(__file__).with_name('dfthcsos_fixed_words.py')]:shutil.copy2(f,code/f.name)
    report=dict(kind='fixed_word_constrained_proximal_refit',official_validation=False,status=status,
        source_npz=str(source.resolve()),source_sha256=sha256(source),generator_sha256=sha256(Path(__file__)),
        model_sha256=sha256(Path(__file__).with_name('dfthcsos_fixed_words.py')),argv=sys.argv,
        python_executable=sys.executable,python_prefix=sys.prefix,initial_metrics=initial_metrics,metrics=metrics,
        predicted_metrics=best_metrics,resources=resources,passes_numerical_gates=passes_accuracy(metrics),
        conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'],accepted_steps=accepted,calls=calls,
        zeroed_events=total_zeroed,reactivated_events=total_reactivated,elapsed_seconds=time.monotonic()-start,
        artifacts=[dict(path=f.name,sha256=sha256(f)) for f in sorted(output.iterdir())],input_cache_sha256=sha256(args.cache),initial_sha256=sha256(args.initial) if args.initial else None)
    (output.parent/'generation.json').write_text(json.dumps(report,indent=2)+'\n');print('FINAL '+json.dumps(report),flush=True)


if __name__=='__main__':main()
