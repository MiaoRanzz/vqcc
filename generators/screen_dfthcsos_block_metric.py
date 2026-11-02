# SPDX-License-Identifier: Apache-2.0
"""Equal predicted-Lambda-drop comparison including actual Newton retraction.

All methods start from the same pinned weights and exact active constraints.
The block metric is fixed for this screen. No circuit acceptance is claimed.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np
from generate import sha256
from dfthcsos.verify import load_inputs, evaluate_words
from dfthcsos_fixed_words import from_inputs
from dfthcsos_curvature import residual_diagonal, inverse_metric
from dfthcsos_block_metric import BlockMetric, apply_metric, tangent, correction


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--cache-parent-output', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--brot', type=int, required=True)
    p.add_argument('--freeze-below', type=float, default=1e-5)
    p.add_argument('--block-relative-floors', type=float, nargs='+', help='Compare only these column-block ridges at the same point')
    p.add_argument('--predicted-drops', type=float, nargs='+', default=[1e-4, 1e-3, 3e-3])
    args = p.parse_args()
    if any(not 0 < x <= 1 for x in (args.block_relative_floors or [])):
        p.error('Block relative floors must be in (0,1]')
    if any(not np.isfinite(x) or x <= 0 for x in args.predicted_drops):
        p.error('Predicted drops must be positive and finite')
    if args.report.exists():
        p.error('Use a distinct report path')
    started = time.monotonic()
    source = args.parent_output/'submission.npz'
    arrays = dict(np.load(source, allow_pickle=False))
    cache_source = args.cache_parent_output/'submission.npz'
    with np.load(cache_source, allow_pickle=False) as other:
        for key in ('angle_words', 'tree_edges'):
            if not np.array_equal(arrays[key], other[key]):
                raise ValueError('Cache words/tree mismatch')
    if 'brot' in arrays and int(arrays['brot']) != args.brot:
        raise ValueError('Precision mismatch')
    arrays['brot'] = np.array(args.brot)
    inputs = load_inputs(source)
    model = from_inputs(inputs, arrays, dict(np.load(args.cache, allow_pickle=False)))
    shape = inputs.w.shape
    size = inputs.w.size
    def pack(w, h):
        return np.r_[w.ravel(), h.ravel()]
    fixed = pack(inputs.w, arrays['H2_I'])
    mask = np.abs(fixed) > args.freeze_below
    initial = fixed[mask]
    target_error, target_gap = .0199999, 3.914899
    calls = 0
    def evaluate(x):
        nonlocal calls
        calls += 1
        full = fixed.copy(); full[mask] = x
        w = full[:size].reshape(shape)
        d = full[size:].reshape(shape[0], shape[2])-w.sum(axis=1)
        m, grads = model.evaluate(w, d, True)
        def grad(key, scale):
            gw, gd = grads[key]
            return pack(gw-gd[:, None, :], gd)[mask]*scale
        j = np.array([grad('error_1_squared', 1/target_error**2),
                      grad('error_2_squared', 1/target_error**2), grad('E_gap', 10.)])
        c = np.array([(m['error_1']/target_error)**2-1,
                      (m['error_2']/target_error)**2-1, (m['E_gap']-target_gap)*10])
        return m, grad('Lambda', 1.), j, c
    metrics, g, j, c = evaluate(initial)
    direct = evaluate_words(inputs, arrays['angle_words'], arrays['tree_edges'], args.brot)
    if any(abs(metrics[key]-direct[key]) > 2e-8 for key in metrics):
        raise ValueError('Model disagrees with official numerical formulas')
    if max(abs(c)) > 2e-8:
        raise ValueError('This experiment requires the pinned active-constraint point')
    build_start = time.monotonic()
    blocks = {}
    if args.block_relative_floors:
        methods = []
        for floor in args.block_relative_floors:
            name = f'column_block_ridge_{floor:g}'
            metric = BlockMetric(model, inputs.w, inputs.W, mask, relative_floor=floor)
            blocks[name] = metric.summary
            methods.append((name, metric))
    else:
        block = BlockMetric(model, inputs.w, inputs.W, mask)
        blocks['column_block'] = block.summary
        diagonal = inverse_metric(residual_diagonal(model, inputs.w, inputs.W)[mask])
        methods = [('diagonal', diagonal), ('ridge_diagonal', block.diagonal_control), ('column_block', block)]
    build_seconds = time.monotonic()-build_start
    rows = []
    for name, metric in methods:
        direction = -tangent(apply_metric(metric, g), j, metric)
        slope = float(g@direction)
        if slope >= 0:
            raise ValueError('Expected descent tangent')
        for predicted_drop in args.predicted_drops:
            begin = time.monotonic(); before = calls
            delta = direction*(predicted_drop/-slope)
            point = initial+delta
            info = evaluate(point)
            unretracted = info[0].copy(); defect = float(np.linalg.norm(info[3]-c-j@delta))
            success = False
            for iteration in range(10):
                m, _, jac, constraints = info
                if max(abs(constraints)) < 2e-10:
                    success = True; break
                point -= correction(constraints, jac, metric)
                info = evaluate(point)
            row = dict(method=name, predicted_lambda_drop=predicted_drop,
                displacement=float(np.linalg.norm(delta)), tangent_residual=float(np.linalg.norm(j@delta)),
                trial_sign_crossings=int(np.count_nonzero(initial*(initial+delta)<0)),
                nonlinear_defect_norm=defect, unretracted_metrics=unretracted,
                retracted_metrics=info[0], retraction_success=success,
                actual_lambda_drop=metrics['Lambda']-info[0]['Lambda'],
                constraint_max_abs=float(max(abs(info[3]))), evaluation_calls=calls-before,
                elapsed_seconds=time.monotonic()-begin)
            rows.append(row); print(json.dumps(row), flush=True)
    report = dict(kind='equal_prediction_column_block_curvature_screen', official_validation=False,
        parent_output=str(args.parent_output.resolve()), source_sha256=sha256(source),
        cache_sha256=sha256(args.cache), cache_parent_npz_sha256=sha256(cache_source),
        words_tree_match=True, model_matches_direct=True, initial_metrics=metrics,
        active_variables=int(mask.sum()), block_metric=blocks.get("column_block"), block_metrics=blocks,
        block_build_seconds=build_seconds, trials=rows, argv=sys.argv,
        generator_sha256=sha256(Path(__file__)),
        metric_sha256=sha256(Path(__file__).with_name('dfthcsos_block_metric.py')),
        python=sys.executable, prefix=sys.prefix, elapsed_seconds=time.monotonic()-started)
    args.report.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
