"""Screen exact pair-coordinate gauges at every L1 sign-change breakpoint.

Independent implementation: the sum of two squared column L1 norms is smooth
between zero crossings. On each interval it is A*cos(t)^2+B*sin(t)^2 +
2*D*sin(t)*cos(t), so its minimum is at an endpoint or a stationary point.
Orthogonal rotation of [W; H2_I] preserves every group Gram matrix and hence
the represented Hamiltonian. Numerical drift is checked explicitly.
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
from dfthcsos.verify import load_inputs, evaluate_words, passes_accuracy


def best_pair_rotation(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.ndim != 1 or x.shape != y.shape or not np.isfinite([x, y]).all():
        raise ValueError('Two finite equal-sized columns required')
    # The objective is pi/2-periodic (a signed column swap).
    nonzero = (x != 0) | (y != 0)
    edges = np.unique(np.r_[0.0, np.mod(np.arctan2(-x[nonzero], y[nonzero]), np.pi/2), np.pi/2])
    mid = (edges[:-1] + edges[1:]) / 2
    co, si = np.cos(mid)[:, None], np.sin(mid)[:, None]
    signs_u = np.sign(co*x + si*y)
    signs_v = np.sign(-si*x + co*y)
    a, b = signs_u@x, signs_u@y
    c, d = signs_v@y, -(signs_v@x)
    A, B, D = a*a+c*c, b*b+d*d, a*b+c*d
    root = np.mod(np.arctan2(-2*D, B-A), np.pi) / 2
    roots = np.r_[root[(root > edges[:-1]) & (root < edges[1:])],
                  (root+np.pi/2)[(root+np.pi/2 > edges[:-1]) & (root+np.pi/2 < edges[1:])]]
    angles = np.r_[edges, roots]
    co, si = np.cos(angles)[:, None], np.sin(angles)[:, None]
    costs = np.sum(np.abs(co*x+si*y), axis=1)**2 + np.sum(np.abs(-si*x+co*y), axis=1)**2
    k = int(np.argmin(costs))
    old = float(np.sum(abs(x))**2+np.sum(abs(y))**2)
    if costs[k] >= old - 1e-12*max(1.0, old):
        return 0.0, old
    return float(angles[k]), float(costs[k])


def exact_sweep(weights, offsets, stop_by=None):
    w, h = np.asarray(weights, dtype=float), np.asarray(offsets, dtype=float)
    if w.ndim != 3 or h.shape != (w.shape[0], w.shape[2]):
        raise ValueError('Weight and offset shapes disagree')
    a = np.concatenate((w, h[:, None, :]), axis=1)
    gram = a @ a.swapaxes(-1, -2)
    before = float(np.sum(np.sum(abs(a), axis=1)**2)/4)
    accepted, tried, complete = [], 0, True
    for r in range(len(a)):
        for i in range(a.shape[2]):
            for j in range(i+1, a.shape[2]):
                if stop_by and datetime.now(timezone.utc) >= stop_by:
                    complete = False
                    break
                x, y = a[r, :, i].copy(), a[r, :, j].copy()
                theta, value = best_pair_rotation(x, y)
                tried += 1
                if theta:
                    co, si = np.cos(theta), np.sin(theta)
                    a[r, :, i], a[r, :, j] = co*x+si*y, -si*x+co*y
                    accepted.append(dict(group=r, i=i, j=j, theta=theta, pair_objective=value))
            if not complete: break
        if not complete: break
    drift = float(np.max(abs(gram - a@a.swapaxes(-1, -2))))
    if drift > 1e-10*max(1., float(np.max(abs(gram)))):
        raise ValueError('Orthogonal gauge accumulated excessive Gram drift')
    after = float(np.sum(np.sum(abs(a), axis=1)**2)/4)
    return a[:, :-1, :], a[:, -1, :], dict(complete=complete, tried_pairs=tried,
        accepted=accepted, gram_max_abs_drift=drift, lambda_h2_before=before, lambda_h2_after=after)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--stop-by', type=datetime.fromisoformat, required=True)
    args = p.parse_args(); start = time.monotonic()
    source = args.parent_output / 'submission.npz'
    with np.load(source, allow_pickle=False) as data:
        arrays = {k: np.array(data[k]) for k in data.files}
    arrays['W'], arrays['H2_I'], gauge = exact_sweep(arrays['W'], arrays['H2_I'], args.stop_by)
    if 'offset_W' in arrays:
        arrays['offset_W'] = arrays['H2_I'] - arrays['W'].sum(axis=1)
    with output_workspace(args.output_dir) as (output, stage):
        np.savez(stage/'submission.npz', **arrays)
        for f in sorted(args.parent_output.glob('angle_k_*.kmb')):
            shutil.copy2(f, stage/f.name)
    metrics = evaluate_words(load_inputs(output/'submission.npz'), arrays['angle_words'], arrays['tree_edges'], 8)
    report = dict(kind='exact_pair_gauge_screen', official_validation=False,
        source_npz=str(source.resolve()), source_sha256=sha256(source),
        generator_sha256=sha256(Path(__file__)), python_executable=sys.executable, python_prefix=sys.prefix,
        created_at=datetime.now(timezone.utc).isoformat(), gauge=gauge, metrics=metrics,
        passes_numerical_gates=passes_accuracy(metrics), elapsed_seconds=time.monotonic()-start,
        artifacts=[dict(path=f.name, sha256=sha256(f)) for f in sorted(output.iterdir())])
    (output.parent/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
