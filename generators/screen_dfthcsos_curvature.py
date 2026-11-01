"""Compare Euclidean and residual-metric tangents before an expensive refit.

Explicit matching words/tree are required when reusing a QR-model cache.
Reported constraint defects are numerical predictions, not official acceptance.
"""
from __future__ import annotations
import argparse,json,sys,time
from pathlib import Path
import numpy as np
from generate import sha256
from dfthcsos.verify import load_inputs,evaluate_words
from dfthcsos_fixed_words import from_inputs
from dfthcsos_curvature import residual_diagonal,inverse_metric,tangent_project


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--cache-parent-output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--brot',type=int,required=True)
    p.add_argument('--freeze-below',type=float,default=1e-5)
    args=p.parse_args();started=time.monotonic()
    if args.report.exists():p.error('Use a new report path')
    source=args.parent_output/'submission.npz';arrays=dict(np.load(source,allow_pickle=False))
    cache_source=args.cache_parent_output/'submission.npz'
    with np.load(cache_source,allow_pickle=False) as other:
        for name in ['angle_words','tree_edges']:
            if not np.array_equal(arrays[name],other[name]):raise ValueError('Cache input words/tree mismatch')
    if 'brot' in arrays and int(arrays['brot'])!=args.brot:raise ValueError('Precision mismatch')
    arrays['brot']=np.array(args.brot);inputs=load_inputs(source)
    model=from_inputs(inputs,arrays,dict(np.load(args.cache,allow_pickle=False)))
    w,d=inputs.w,inputs.W;size=w.size;shape=w.shape
    def pack(w,h):return np.r_[w.ravel(),h.ravel()]
    fixed=pack(w,arrays['H2_I']);mask=np.abs(fixed)>args.freeze_below;x=fixed[mask]
    def point(x):
        full=fixed.copy();full[mask]=x
        ww=full[:size].reshape(shape);hh=full[size:].reshape(shape[0],shape[2])
        return ww,hh-ww.sum(axis=1)
    metrics,grads=model.evaluate(w,d,True)
    direct=evaluate_words(inputs,arrays['angle_words'],arrays['tree_edges'],args.brot)
    for key in metrics:
        if abs(metrics[key]-direct[key])>2e-8:raise ValueError(f'Model disagrees on {key}')
    def convert(key,scale):
        gw,gd=grads[key];return pack(gw-gd[:,None,:],gd)[mask]*scale
    tol=.0199999
    keys=['error_2_squared','E_gap'];scales=[1/tol**2,10.]
    if metrics['error_1']>=tol*(1-1e-4):keys.insert(0,'error_1_squared');scales.insert(0,1/tol**2)
    jac=np.array([convert(key,scale) for key,scale in zip(keys,scales)])
    g=convert('Lambda',1/300)
    def constraints(m):
        return np.array([m[k.replace('_squared','')]**(2 if k.endswith('_squared') else 1)*s for k,s in zip(keys,scales)])
    base=constraints(metrics);rows=[]
    diagonal=residual_diagonal(model,w,d)[mask]
    for name,metric in [('euclidean',np.ones_like(x)),('residual',inverse_metric(diagonal))]:
        direction=-tangent_project(metric*g,jac,metric);direction/=np.linalg.norm(direction)
        for length in [1e-4,1e-3,1e-2]:
            delta=length*direction;ww,dd=point(x+delta);actual=model.evaluate(ww,dd)
            predicted=jac@delta;change=constraints(actual)-base
            rows.append(dict(method=name,length=length,predicted_constraint_change=predicted.tolist(),actual_constraint_change=change.tolist(),nonlinear_defect_norm=float(np.linalg.norm(change-predicted)),predicted_lambda_change=float(300*g@delta),actual_lambda_change=actual['Lambda']-metrics['Lambda'],metrics=actual))
    report=dict(kind='fixed_point_tangent_curvature_screen',official_validation=False,parent_output=str(args.parent_output.resolve()),source_sha256=sha256(source),cache_sha256=sha256(args.cache),cache_parent_npz_sha256=sha256(cache_source),words_tree_match=True,model_matches_direct=True,python=sys.executable,prefix=sys.prefix,argv=sys.argv,active_variables=int(mask.sum()),constraint_keys=keys,initial_metrics=metrics,metric_range=[float(inverse_metric(diagonal).min()),float(inverse_metric(diagonal).max())],trials=rows,elapsed_seconds=time.monotonic()-started)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
