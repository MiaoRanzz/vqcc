"""Fixed-word sparse-face polishing on the official residual/gap manifold.

Independent projected L-BFGS with Newton retraction of three scalar constraints.
This generator performs numerical screening; only pipeline validation establishes
acceptance. Frozen entries retain their parent values, rather than being zeroed.
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
from generate import sha256,output_workspace
import numpy as np
from dfthcsos_fixed_words import from_inputs
from dfthcsos.verify import load_inputs,evaluate_words,passes_accuracy,resource_costs
from dfthcsos.scoreinfra.circuits import load_circuits,circuit_costs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--cache',type=Path)
    p.add_argument('--brot',type=int,help='Required when the fixed input omits its angle precision')
    p.add_argument('--error1-inequality',action='store_true',help='Keep slack in error1 until its upper bound becomes active')
    p.add_argument('--stall-window',type=int,default=0,help='Zero preserves the original iteration-only stopping rule')
    p.add_argument('--minimum-lambda-progress',type=float,default=1e-8)
    p.add_argument('--freeze-below',type=float,default=1e-8)
    p.add_argument('--iterations',type=int,default=1000)
    p.add_argument('--stop-by',required=True)
    args=p.parse_args();start=time.monotonic();stop=datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None:raise ValueError('Timezone required')
    source=args.parent_output/'submission.npz';arrays=dict(np.load(source,allow_pickle=False));inputs=load_inputs(source)
    if args.brot is not None:
        if 'brot' in arrays and int(arrays['brot'])!=args.brot:raise ValueError('Explicit precision disagrees with input')
        arrays['brot']=np.array(args.brot)
    if 'brot' not in arrays:raise ValueError('Input omits angle precision; pass --brot explicitly')
    model=from_inputs(inputs,arrays,dict(np.load(args.cache)) if args.cache else None)
    shape=inputs.w.shape;size=inputs.w.size
    def pack(w,h):return np.r_[w.ravel(),h.ravel()]
    def unpack(x):
        w=x[:size].reshape(shape);h=x[size:].reshape(shape[0],shape[2]);return w,h-w.sum(axis=1)
    fixed=pack(inputs.w,arrays['H2_I']);mask=np.abs(fixed)>args.freeze_below
    x=fixed[mask].copy();target_error=.01999990;target_gap=3.9148990;calls=0
    screen=args.output_dir.parent/'screen';screen.mkdir(exist_ok=True)
    np.savez(screen/'model-cache.npz',**model.cache())
    error1_active=not args.error1_inequality
    recent_lambda=[]
    trace=(screen/'trace.jsonl').open('w');history=[];best=None;best_metrics=None
    class Deadline(Exception):pass
    def expand(x):
        full=fixed.copy();full[mask]=x;return full
    def evalpoint(x):
        nonlocal calls
        if datetime.now(timezone.utc)>=stop:raise Deadline()
        w,d=unpack(expand(x));m,g=model.evaluate(w,d,True);calls+=1
        def convert(key,scale):
            gw,gd=g[key];return pack(gw-gd[:,None,:],gd)[mask]*scale
        jac=np.array([convert('error_1_squared',1/target_error**2),convert('error_2_squared',1/target_error**2),convert('E_gap',10)])
        c=np.array([(m['error_1']/target_error)**2-1,(m['error_2']/target_error)**2-1,(m['E_gap']-target_gap)*10])
        if not error1_active:c,jac=c[1:],jac[1:]
        return m['Lambda']/300,convert('Lambda',1/300),c,jac,m
    def project(v,g):
        norms=np.linalg.norm(g,axis=1);u=g/norms[:,None]
        return v-u.T@np.linalg.solve(u@u.T,u@v)
    def retract(y,steps=10):
        for k in range(steps):
            info=evalpoint(y);f,g,c,jac,m=info
            if np.max(np.abs(c))<2e-10:return y,info
            norms=np.linalg.norm(jac,axis=1);u=jac/norms[:,None]
            y=y-u.T@np.linalg.solve(u@u.T,c/norms)
        return None,None
    initial_metrics=model.evaluate(inputs.w,inputs.W)
    if passes_accuracy(dict(initial_metrics,gap_in_domain=0<initial_metrics['E_gap']<2*initial_metrics['Lambda'])):
        best=fixed.copy();best_metrics=initial_metrics
    status='iteration_limit';pairs=[];accepted=0
    try:
        initial_x=x.copy()
        x,info=retract(x)
        if args.error1_inequality and x is not None and info[4]['error_1']>target_error:
            error1_active=True;x,info=retract(initial_x)
        if x is None:raise RuntimeError('Initial constraint retraction failed')
        for iteration in range(args.iterations):
            if not error1_active and info[4]['error_1']>=target_error*(1-1e-4):
                error1_active=True
                x,info=retract(x)
                if x is None:raise RuntimeError('Active error1 retraction failed')
                pairs=[]
            f,g,c,jac,m=info;pg=project(g,jac)
            if best_metrics is None or m['lambda_eff']<best_metrics['lambda_eff']:
                best=expand(x);best_metrics=m.copy()
            # Standard inverse-Hessian two-loop, followed by tangent projection.
            direction=pg.copy();alphas=[]
            for s,y,rho in reversed(pairs):
                alpha=rho*np.dot(s,direction);alphas.append(alpha);direction-=alpha*y
            if pairs:
                s,y,_=pairs[-1];direction*=np.dot(s,y)/np.dot(y,y)
            for (s,y,rho),alpha in zip(pairs,reversed(alphas)):
                direction+=s*(alpha-rho*np.dot(y,direction))
            direction=-project(direction,jac)
            if np.dot(direction,g)>=0:direction=-pg;pairs=[]
            slope=float(np.dot(direction,g));step=1.0 if pairs else .01
            row=dict(iteration=iteration,calls=calls,error1_active=error1_active,metrics=m,projected_gradient_norm=float(np.linalg.norm(pg)),slope=slope,elapsed_seconds=time.monotonic()-start)
            if iteration%10==0:
                trace.write(json.dumps(row)+'\n');trace.flush();print(json.dumps(row),flush=True)
                bw,bd=unpack(best);np.savez(screen/'best.npz',w=bw,d=bd)
            success=False
            for backtrack in range(24):
                trial,trial_info=retract(x+step*direction)
                if trial is not None and (not args.error1_inequality or trial_info[4]['error_1']<=target_error+1e-12) and trial_info[0]<=f+1e-4*step*slope and trial_info[0]<f-1e-14:
                    success=True;break
                step*=.5
            if not success:status='line_search_stalled';break
            s=trial-x;newpg=project(trial_info[1],trial_info[3]);y=newpg-project(pg,trial_info[3])
            sy=np.dot(s,y)
            if sy>1e-14*np.linalg.norm(s)*np.linalg.norm(y):
                pairs.append((s,y,1/sy));pairs=pairs[-20:]
            x,info=trial,trial_info;accepted+=1
            recent_lambda.append(info[4]['Lambda'])
            if args.stall_window>0 and len(recent_lambda)>args.stall_window:
                recent_lambda=recent_lambda[-args.stall_window-1:]
                if recent_lambda[0]-recent_lambda[-1]<args.minimum_lambda_progress:
                    status='numerical_progress_stalled';break
        # Include the final accepted point even if the loop exhausted its budget.
        m=info[4]
        if best_metrics is None or m['lambda_eff']<best_metrics['lambda_eff']:best=expand(x);best_metrics=m.copy()
    except Deadline:status='bounded_deadline'
    finally:trace.close()
    if best is None:raise RuntimeError('No feasible output')
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
    report=dict(kind='fixed_word_sparse_face_manifold_refit',official_validation=False,status=status,error1_inequality=args.error1_inequality,error1_active_final=error1_active,source_npz=str(source.resolve()),source_sha256=sha256(source),generator_sha256=sha256(Path(__file__)),model_sha256=sha256(Path(__file__).with_name('dfthcsos_fixed_words.py')),argv=sys.argv,python_executable=sys.executable,python_prefix=sys.prefix,initial_metrics=initial_metrics,metrics=metrics,predicted_metrics=best_metrics,resources=resources,passes_numerical_gates=passes_accuracy(metrics),conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'],frozen_variables=int((~mask).sum()),active_variables=int(mask.sum()),accepted_steps=accepted,calls=calls,elapsed_seconds=time.monotonic()-start,artifacts=[dict(path=f.name,sha256=sha256(f)) for f in sorted(output.iterdir())],input_cache_sha256=sha256(args.cache) if args.cache else None)
    (output.parent/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FINAL '+json.dumps(report),flush=True)

if __name__=='__main__':main()
