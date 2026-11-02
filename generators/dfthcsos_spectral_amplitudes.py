# SPDX-License-Identifier: Apache-2.0
"""Bounded public spectral-amplitude adaptation on an explicit fixed-word parent.

Uses the pinned Apache-2.0 avazaku/Sigmaborov column model and SciPy cutting-plane
solver. Positive column scales preserve the represented one-body matrix. The
exact quadratic two-body residual and unchanged native formulas gate numerical
steps; only pipeline validation establishes official acceptance.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
import numpy as np
from generate import sha256, output_workspace
from dfthcsos import verify as chem
from dfthcsos.scoreinfra import reference, dfthc_math as maths
from dfthcsos.scoreinfra.circuits import load_circuits, circuit_costs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--helper', type=Path, required=True)
    p.add_argument('--helper-sha256', required=True)
    p.add_argument('--license-file', type=Path, required=True)
    p.add_argument('--max-seconds', type=float, default=120)
    p.add_argument('--stop-by', required=True)
    p.add_argument('--radius', type=float, default=.002)
    p.add_argument('--brot', type=int, default=8)
    args = p.parse_args(); started = time.monotonic()
    stop = datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None: p.error('stop-by requires a timezone')
    if not 0 < args.radius <= .01 or args.max_seconds <= 0: p.error('Invalid budget or radius')
    if sha256(args.helper) != args.helper_sha256: raise ValueError('Reviewed helper differs')
    spec = importlib.util.spec_from_file_location('pinned_spectral', args.helper)
    upstream = importlib.util.module_from_spec(spec); spec.loader.exec_module(upstream)
    # Retain the incumbent numerical search margins to compare algorithmic progress.
    upstream.CAP = .0199999000001
    upstream.FLOOR = 3.9148989999
    source = args.parent_output/'submission.npz'
    arrays = dict(np.load(source, allow_pickle=False)); inputs = chem.load_inputs(source)
    w, h = arrays['W'], arrays['H2_I']
    if 'brot' in arrays and int(arrays['brot']) != args.brot: raise ValueError('Precision mismatch')
    base = chem.evaluate_words(inputs, arrays['angle_words'], arrays['tree_edges'], args.brot)
    if not chem.passes_accuracy(base): raise ValueError('Parent is numerically infeasible')
    n = int(inputs.ref['orbitals'])
    vectors = maths.reconstruct_u_vectors(arrays['angle_words']/2**(args.brot-1), arrays['tree_edges'])
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    body = vectors[n:].reshape(w.shape[0], w.shape[1], n)
    x = maths.reconstruct_x(body, w)
    x = np.tril(x)+np.swapaxes(np.tril(x, k=-1), -1, -2)
    def native(ww, hh):
        return maths.evaluate_dfthc_angle_words(arrays['angle_words'], ww, hh-ww.sum(axis=1), inputs.S,
            inputs.beta_1, inputs.ref, brot=args.brot, tree_edges=arrays['tree_edges'], energy_upper=reference.UPPER_ENERGY)
    model = upstream.ColumnAmplitudeModel(w, h, x, base, inputs.ref, inputs.S, maths)
    screen = args.output_dir.parent/'screen'; screen.mkdir(exist_ok=True)
    fixtures = upstream.test_column_model(model, native)
    (screen/'fixtures.json').write_text(json.dumps(fixtures, indent=2)+'\n')
    eigen, vec = np.linalg.eigh(model.A)
    eigen_floor = max(float(eigen.max())*1e-7, 1e-18)
    B = vec/np.sqrt(np.maximum(eigen, eigen_floor))[None, :]
    B /= np.max(np.abs(B).sum(axis=1))
    u = np.ones(model.dim); current = model.evaluate(u); best = u.copy()
    radius = args.radius; history = []; status = 'iteration_limit'
    deadline = min(started+args.max_seconds, time.monotonic()+(stop-datetime.now(timezone.utc)).total_seconds())
    for iteration in range(500):
        if time.monotonic() >= deadline: status = 'bounded_deadline'; break
        fit, offset, diagnostics = upstream.metric_step(model, u, current, radius, B, deadline)
        if fit is None or not fit.success:
            status = 'bounded_or_solver_stopped'; break
        if fit.fun-offset >= -1e-11: status = 'no_predicted_descent'; break
        step = B@fit.x[:model.dim]
        aa = float(step@model.A@step); bb = float(current['gradient_error2_sq']@step)
        cc = current['error_2_sq']-upstream.CAP**2
        alpha = 1.
        if aa > 0: alpha = min(1., max(0., .999*(-bb+np.sqrt(max(bb*bb-4*aa*cc, 0)))/(2*aa)))
        accepted = False
        for _ in range(35):
            trial = u+alpha*step
            if np.any(trial <= 0): alpha *= .5; continue
            got = model.evaluate(trial)
            if got['error_2'] <= upstream.CAP and got['E_gap'] >= upstream.FLOOR and got['lambda_eff'] < current['lambda_eff']-1e-11:
                u, current = trial, got; best = u.copy(); accepted = True; break
            alpha *= .5
        row = dict(iteration=iteration, accepted=accepted, alpha=alpha, radius=radius,
                   seconds=time.monotonic()-started, lambda_eff=current['lambda_eff'], **diagnostics)
        history.append(row); print(json.dumps(row), flush=True)
        if accepted and alpha > .95: radius = min(.01, radius*1.1)
        elif not accepted: radius *= .25
        if radius < 1e-11: status = 'radius_exhausted'; break
    ww, hh = model.factor(best); measured = native(ww, hh)
    accepted = chem.passes_accuracy(measured) and measured['lambda_eff'] < base['lambda_eff']
    result = dict(arrays)
    if accepted:
        result.update(W=ww, H2_I=hh)
        if 'offset_W' in result: result['offset_W'] = hh-ww.sum(axis=1)
    with output_workspace(args.output_dir) as (output, stage):
        for f in args.parent_output.glob('angle_k_*.kmb'): shutil.copy2(f, stage/f.name)
        np.savez(stage/'submission.npz', **result)
        final = chem.evaluate_words(chem.load_inputs(stage/'submission.npz'), result['angle_words'], result['tree_edges'], args.brot)
        if not chem.passes_accuracy(final): raise ValueError('Materialized candidate violates native accuracy')
        circuits = load_circuits(stage)
        resources = chem.resource_costs(chem.load_inputs(stage/'submission.npz'), circuits, args.brot, 2*sum(s['max_magic'] for s in circuit_costs(circuits)))
    code = output.parent/'code'; code.mkdir(exist_ok=True)
    for f in [Path(__file__), args.helper, args.license_file]: shutil.copy2(f, code/f.name)
    report = dict(kind='public_spectral_amplitude_cutting_planes', official_validation=False,
        status=status, accepted=bool(accepted), parent_output=str(args.parent_output.resolve()),
        source_sha256=sha256(source), helper_sha256=args.helper_sha256,
        generator_sha256=sha256(Path(__file__)), argv=sys.argv, python=sys.executable, prefix=sys.prefix,
        source_url='https://www.kaggle.com/code/sigmaborov/22-85569-lb-exact-gauge-search', notebook_version=14,
        source_attribution='avazaku spectral model; Sigmaborov standalone release; local bounded wrapper',
        max_seconds=args.max_seconds, search_error2_cap=upstream.CAP, search_gap_floor=upstream.FLOOR,
        before=base, after=final, resources=resources, conditional_cost=final['lambda_eff']*resources['toffoli']*resources['qubits'],
        dimensions=model.dim, eigenvalue_floor=eigen_floor, history=history,
        elapsed_seconds=time.monotonic()-started, artifacts=[dict(path=f.name,sha256=sha256(f)) for f in sorted(output.iterdir())])
    (output.parent/'generation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['status','accepted','conditional_cost','elapsed_seconds']}), flush=True)


if __name__ == '__main__': main()
