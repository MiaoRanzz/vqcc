# SPDX-License-Identifier: Apache-2.0
"""Bounded rank-feasibility diagnostic with one-body/gap/cost constraints removed.

Failure to reach 20 mHa is a local numerical rejection, not an infeasibility
certificate. A successful two-body fit still needs all official constraints.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time
import numpy as np
from scipy.optimize import minimize
from generate import sha256
from dfthcsos_fixed_words import from_inputs
from dfthcsos.verify import load_inputs


def two_body_value_gradient(model, w):
    r, _, c = w.shape
    x = (w.swapaxes(1, 2)@model.ar).reshape(r*c, -1)
    residual = x.T@x-model.projected
    value = float(np.sum(residual**2)+model.outside_squared)
    gx = (4*x@residual).reshape(r, c, -1)
    return value, model.ar@gx.swapaxes(1, 2)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-npz', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--cache-parent-output', type=Path, required=True)
    p.add_argument('--candidate-dir', type=Path, required=True)
    p.add_argument('--max-seconds', type=float, default=120)
    p.add_argument('--method', choices=['lbfgs', 'trust-ncg'], default='lbfgs')
    p.add_argument('--coordinates', choices=['weights', 'orthonormal'], default='weights')
    p.add_argument('--stop-by', required=True)
    args=p.parse_args();start=time.monotonic();stop=datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None or not 0 < args.max_seconds <= 600:
        p.error('Require timezone and 0..600 second budget')
    if (stop-datetime.now(timezone.utc)).total_seconds()<args.max_seconds+30:
        p.error('Insufficient time to finish and checkpoint')
    arrays=dict(np.load(args.source_npz,allow_pickle=False))
    with np.load(args.cache_parent_output/'submission.npz',allow_pickle=False) as other:
        if not all(np.array_equal(arrays[k],other[k]) for k in ('angle_words','tree_edges')):
            raise ValueError('Cache words/tree mismatch')
    inputs=load_inputs(args.source_npz)
    model=from_inputs(inputs,arrays,dict(np.load(args.cache,allow_pickle=False)))
    initial=model.evaluate(inputs.w,inputs.W)
    from dfthcsos_residual_hessian import ResidualCurvature, directional_check, OrthonormalCoordinates
    fit_model, fit_w, coordinates = model, inputs.w, None
    if args.coordinates == 'orthonormal':
        coordinates = OrthonormalCoordinates(model.ar)
        fit_model = copy.copy(model)
        fit_model.ar = coordinates.basis
        fit_w = coordinates.encode(inputs.w)
        np.testing.assert_allclose(fit_w.swapaxes(1,2)@fit_model.ar,
                                   inputs.w.swapaxes(1,2)@model.ar, rtol=1e-11, atol=1e-13)
    value,g=two_body_value_gradient(fit_model,fit_w)
    if not np.isclose(value,initial['error_2']**2,rtol=1e-12,atol=1e-16):
        raise ValueError('Independent two-body residual mismatch')
    # A fixed diagonal Gauss-Newton metric, including every w coordinate.
    x=(fit_w.swapaxes(1,2)@fit_model.ar)
    aa=np.sum(fit_model.ar**2,axis=-1)
    ax=fit_model.ar@x.swapaxes(1,2)
    diag=4*(aa[:,:,None]*np.sum(x*x,axis=-1)[:,None,:]+ax*ax)
    median=float(np.median(diag[diag>0]));scale=np.sqrt(median/(diag+1e-3*median))
    initial_w=fit_w.copy();normalizer=value;best=(value,initial_w.copy());calls=0
    derivative_check = directional_check(fit_model, initial_w, two_body_value_gradient) if args.method == 'trust-ncg' or coordinates is not None else None
    hessian_calls = 0
    first_trial_model = None
    curvature_point = curvature = None
    screen=args.candidate_dir/'screen';screen.mkdir(exist_ok=True)
    trace=(screen/'two-body-trace.jsonl').open('w')
    class Budget(Exception):pass
    class Success(Exception):pass
    optimization_start = time.monotonic()
    def check_budget():
        if datetime.now(timezone.utc)>=stop or time.monotonic()-optimization_start>=args.max_seconds:raise Budget()
    def objective(z):
        nonlocal best,calls,first_trial_model
        check_budget()
        w=initial_w+z.reshape(initial_w.shape)*scale
        val,gradient=two_body_value_gradient(fit_model,w);calls+=1
        if args.method == 'trust-ncg' and first_trial_model is None and np.any(z):
            step = w-initial_w
            hs = ResidualCurvature(fit_model, initial_w).apply(step)
            predicted = -float(np.sum(g*step)+.5*np.sum(step*hs))
            actual = value-val
            first_trial_model = dict(predicted_decrease=predicted, actual_decrease=actual,
                ratio=actual/predicted if predicted else None, step_norm=float(np.linalg.norm(step)))
        if val<best[0]:best=val,w.copy()
        trace.write(json.dumps(dict(call=calls,error_2=float(np.sqrt(val)),elapsed_seconds=time.monotonic()-start))+'\n')
        if calls%20==0:trace.flush()
        if val<.0199998**2:raise Success()
        return val/normalizer,(gradient*scale/normalizer).ravel()
    def hessian_product(z, direction):
        nonlocal hessian_calls, curvature_point, curvature
        check_budget()
        if curvature_point is None or not np.array_equal(curvature_point, z):
            curvature_point = z.copy()
            curvature = ResidualCurvature(fit_model, initial_w+z.reshape(initial_w.shape)*scale)
        hessian_calls += 1
        hv = curvature.apply(direction.reshape(initial_w.shape)*scale)
        return (hv*scale/normalizer).ravel()
    status='unknown'
    try:
        if args.method == 'lbfgs':
            result=minimize(objective,np.zeros(inputs.w.size),jac=True,method='L-BFGS-B',
                            options=dict(maxiter=20000,maxcor=20,maxls=30,ftol=1e-15,gtol=1e-12))
        else:
            result=minimize(objective,np.zeros(inputs.w.size),jac=True,method='trust-ncg',
                            hessp=hessian_product, options=dict(maxiter=20000, gtol=1e-12,
                                initial_trust_radius=.01, max_trust_radius=1.))
        status=str(result.message)
    except Budget:status='bounded_deadline'
    except Success:status='two_body_target_reached'
    finally:trace.close()
    optimization_seconds = time.monotonic()-optimization_start
    # Retain native d from the rank seed; this file is a diagnostic checkpoint,
    # never placed in candidate output or treated as a feasible candidate.
    best_w = coordinates.decode(best[1]) if coordinates is not None else best[1]
    arrays['W']=best_w;arrays['H2_I']=inputs.W+best_w.sum(axis=1)
    if 'offset_W' in arrays:arrays['offset_W']=inputs.W
    np.savez(screen/'best-two-body.npz',**arrays)
    final=model.evaluate(best_w,inputs.W)
    if not np.isclose(final['error_2']**2,best[0],rtol=1e-10,atol=1e-14):
        raise ValueError('Coordinate round trip changed the residual')
    report=dict(kind='rank_two_body_only_feasibility_screen',official_validation=False,
                source_npz=str(args.source_npz.resolve()),source_sha256=sha256(args.source_npz),
                cache_sha256=sha256(args.cache),generator_sha256=sha256(Path(__file__)),
                model_sha256=sha256(Path(__file__).with_name('dfthcsos_fixed_words.py')),
                argv=sys.argv,python_executable=sys.executable,python_prefix=sys.prefix,
                initial_metrics=initial,metrics=final,status=status,calls=calls,
                coordinates=args.coordinates,coordinate_conditions=coordinates.conditions.tolist() if coordinates is not None else None,
                method=args.method,hessian_calls=hessian_calls,derivative_check=derivative_check,
                optimization_seconds=optimization_seconds,first_trial_model=first_trial_model,
                hessian_source_sha256=sha256(Path(__file__).with_name('dfthcsos_residual_hessian.py')),
                all_w_variables_free=True,other_constraints_enforced=False,
                two_body_target_reached=bool(best[0]<.0199998**2),
                checkpoint=str(screen/'best-two-body.npz'),checkpoint_sha256=sha256(screen/'best-two-body.npz'),
                elapsed_seconds=time.monotonic()-start)
    (args.candidate_dir/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    for name in ('screen_dfthcsos_rank_residual.py','dfthcsos_fixed_words.py','dfthcsos_residual_hessian.py'):
        shutil.copy2(Path(__file__).with_name(name),args.candidate_dir/'code'/name)
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
