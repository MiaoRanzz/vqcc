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
    p.add_argument('--orthantwise',action='store_true',help='Use an L1 pseudo-gradient and preserve zero faces during retraction')
    p.add_argument('--warm-line-search',action='store_true',help='Start the next L-BFGS line search at twice the last accepted step, capped at one')
    p.add_argument('--warm-radius',action='store_true',help='Warm-start using the last displacement norm instead of an unscaled step')
    p.add_argument('--max-seconds',type=float,help='Bound optimizer time for equal-wall-time comparisons')
    p.add_argument('--iterations',type=int,default=1000)
    p.add_argument('--stop-by',required=True)
    args=p.parse_args();start=time.monotonic();stop=datetime.fromisoformat(args.stop_by)
    if args.warm_line_search and args.warm_radius:p.error('Choose only one line-search warm start')
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
    from dfthcsos_orthant import tangent_pseudogradient,face_project,orthant_trial
    diagnostics=dict(retraction_calls=0,retraction_failed=0,backtracks=0,
        error1_rejections=0,armijo_rejections=0,trial_sign_crossings=0,
        retraction_sign_crossings=0,zeroed=0,reactivated=0,dual_iterations=0)
    recent_lambda=[]
    trace=(screen/'trace.jsonl').open('w');history=[];best=None;best_metrics=None
    class Deadline(Exception):pass
    def expand(x):
        full=fixed.copy();full[mask]=x;return full
    def evalpoint(x):
        nonlocal calls
        if datetime.now(timezone.utc)>=stop or (args.max_seconds is not None and time.monotonic()-start>=args.max_seconds):raise Deadline()
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
        diagnostics['retraction_calls']+=1
        if args.orthantwise:y=y.copy()
        for k in range(steps):
            info=evalpoint(y);f,g,c,jac,m=info
            if np.max(np.abs(c))<2e-10:return y,info
            if args.orthantwise:
                active=y!=0;j=jac[:,active];norms=np.linalg.norm(j,axis=1);u=j/norms[:,None]
                correction=u.T@np.linalg.lstsq(u@u.T,c/norms,rcond=1e-12)[0]
                previous=y[active].copy();candidate=previous-correction
                crossed=previous*candidate<=0
                diagnostics['retraction_sign_crossings']+=int(np.count_nonzero(crossed))
                candidate[crossed]=0;y[active]=candidate
            else:
                norms=np.linalg.norm(jac,axis=1);u=jac/norms[:,None]
                y=y-u.T@np.linalg.solve(u@u.T,c/norms)
        diagnostics['retraction_failed']+=1
        return None,None
    def pseudo(x,g,jac):
        if not args.orthantwise:return project(g,jac),np.ones(len(x),dtype=bool)
        w,d=unpack(expand(x));h=d+w.sum(axis=1);l1=np.abs(w).sum(axis=1)+np.abs(h)
        weights=pack(np.broadcast_to(.5*l1[:,None,:],shape),.5*l1)[mask]/300
        pg,active,dual=tangent_pseudogradient(x,g,weights,jac)
        diagnostics['dual_iterations']+=dual['iterations']
        return pg,active
    initial_metrics=model.evaluate(inputs.w,inputs.W)
    if passes_accuracy(dict(initial_metrics,gap_in_domain=0<initial_metrics['E_gap']<2*initial_metrics['Lambda'])):
        best=fixed.copy();best_metrics=initial_metrics
    status='iteration_limit';pairs=[];accepted=0;last_step=None;last_displacement=None;accepted_stepsizes=[]
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
            f,g,c,jac,m=info;pg,active=pseudo(x,g,jac)
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
            direction=-face_project(direction,jac,active) if args.orthantwise else -project(direction,jac)
            if np.dot(direction,pg if args.orthantwise else g)>=0:direction=-pg;pairs=[]
            slope=float(np.dot(direction,pg if args.orthantwise else g));step=1.0 if pairs else .01
            if args.warm_line_search and pairs and last_step is not None:step=min(1.,2*last_step)
            if args.warm_radius and pairs and last_displacement is not None:
                step=min(1.,2*last_displacement/max(float(np.linalg.norm(direction)),1e-30))
            row=dict(iteration=iteration,calls=calls,error1_active=error1_active,metrics=m,projected_gradient_norm=float(np.linalg.norm(pg)),slope=slope,line_search_initial_step=step,last_accepted_step=last_step,diagnostics=diagnostics.copy(),elapsed_seconds=time.monotonic()-start)
            if iteration%10==0:
                trace.write(json.dumps(row)+'\n');trace.flush();print(json.dumps(row),flush=True)
                bw,bd=unpack(best);np.savez(screen/'best.npz',w=bw,d=bd)
            success=False
            for backtrack in range(24):
                diagnostics['backtracks']+=int(backtrack>0)
                proposal=x+step*direction
                diagnostics['trial_sign_crossings']+=int(np.count_nonzero(x*proposal<0))
                if args.orthantwise:proposal=orthant_trial(x,direction,step,pg)
                trial,trial_info=retract(proposal)
                if trial is not None and (not args.error1_inequality or trial_info[4]['error_1']<=target_error+1e-12) and trial_info[0]<=f+1e-4*step*slope and trial_info[0]<f-1e-14:
                    success=True;break
                if trial is not None:
                    diagnostics['error1_rejections']+=int(args.error1_inequality and trial_info[4]['error_1']>target_error+1e-12)
                    diagnostics['armijo_rejections']+=int(trial_info[0]>f+1e-4*step*slope or trial_info[0]>=f-1e-14)
                step*=.5
            if not success:status='line_search_stalled';break
            last_step=step;accepted_stepsizes.append(step)
            diagnostics['zeroed']+=int(np.count_nonzero((x!=0)&(trial==0)))
            diagnostics['reactivated']+=int(np.count_nonzero((x==0)&(trial!=0)))
            s=trial-x;newpg,newactive=pseudo(trial,trial_info[1],trial_info[3])
            last_displacement=float(np.linalg.norm(s))
            y=newpg-(face_project(pg,trial_info[3],newactive) if args.orthantwise else project(pg,trial_info[3]))
            if args.orthantwise and np.any(active!=newactive):pairs=[]
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
    for f in [Path(__file__),Path(__file__).with_name('dfthcsos_fixed_words.py'),Path(__file__).with_name('dfthcsos_orthant.py')]:shutil.copy2(f,code/f.name)
    report=dict(kind='fixed_word_sparse_face_manifold_refit',official_validation=False,status=status,error1_inequality=args.error1_inequality,error1_active_final=error1_active,source_npz=str(source.resolve()),source_sha256=sha256(source),generator_sha256=sha256(Path(__file__)),model_sha256=sha256(Path(__file__).with_name('dfthcsos_fixed_words.py')),argv=sys.argv,python_executable=sys.executable,python_prefix=sys.prefix,initial_metrics=initial_metrics,metrics=metrics,predicted_metrics=best_metrics,resources=resources,passes_numerical_gates=passes_accuracy(metrics),conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'],frozen_variables=int((~mask).sum()),active_variables=int(mask.sum()),accepted_steps=accepted,calls=calls,elapsed_seconds=time.monotonic()-start,artifacts=[dict(path=f.name,sha256=sha256(f)) for f in sorted(output.iterdir())],input_cache_sha256=sha256(args.cache) if args.cache else None)
    report.update(orthantwise=args.orthantwise,max_seconds=args.max_seconds,diagnostics=diagnostics,
                  orthant_sha256=sha256(Path(__file__).with_name('dfthcsos_orthant.py')),
                  warm_line_search=args.warm_line_search,warm_radius=args.warm_radius,accepted_stepsizes=accepted_stepsizes)
    (output.parent/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FINAL '+json.dumps(report),flush=True)

if __name__=='__main__':main()
