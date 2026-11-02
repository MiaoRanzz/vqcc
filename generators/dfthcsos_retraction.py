# SPDX-License-Identifier: Apache-2.0
"""Monotone damped normal retraction for infeasible numerical seeds.

This is a bounded search heuristic. It does not establish official feasibility.
The caller chooses and scales constraints, and enforces wall-clock deadlines.
"""
from __future__ import annotations
import numpy as np
from dfthcsos_block_metric import apply_metric


def damped_retract(x, evaluate, metric, *, record=lambda row: None,
                   max_steps=200, max_backtracks=24, tolerance=2e-10,
                   relative_radius=.1):
    """Return (point, evaluation, status), retaining all attempted residuals.

    ``evaluate`` returns (objective, gradient, constraints, Jacobian, metrics).
    A least-squares solve handles dependent constraint rows without discarding
    their residuals. Every accepted step strictly decreases squared residual.
    """
    if max_steps < 0 or max_backtracks < 1 or relative_radius <= 0:
        raise ValueError('Invalid bounded retraction parameters')
    x = np.array(x, dtype=float, copy=True)
    info = evaluate(x)
    def row(iteration, kind, info, **extra):
        c = info[2]
        record(dict(iteration=iteration, kind=kind,
                    constraints=c.tolist(), merit=float(c@c/2),
                    metrics=info[4], **extra))
    row(0, 'initial', info)
    for iteration in range(max_steps+1):
        c, jac = info[2:4]
        if np.max(np.abs(c)) < tolerance:
            return x, info, 'converged'
        if iteration == max_steps:
            return None, info, 'step_limit'
        norms = np.maximum(np.linalg.norm(jac, axis=1), 1e-30)
        u = jac/norms[:, None]
        du = apply_metric(metric, u)
        delta = -du.T@np.linalg.lstsq(u@du.T, c/norms, rcond=1e-12)[0]
        length = float(np.linalg.norm(delta))
        radius = relative_radius*max(1., float(np.linalg.norm(x)))
        if length > radius:
            delta *= radius/length
        slope = float(c@(jac@delta))
        if not np.all(np.isfinite(delta)) or slope >= 0:
            return None, info, 'no_descent_direction'
        merit = float(c@c/2)
        for backtrack in range(max_backtracks):
            alpha = 2.**(-backtrack)
            trial = x+alpha*delta
            candidate = evaluate(trial)
            cc = candidate[2]
            trial_merit = float(cc@cc/2)
            accepted = bool(np.isfinite(trial_merit) and trial_merit < merit
                            and trial_merit <= merit+1e-4*alpha*slope)
            row(iteration, 'trial', candidate, alpha=alpha, accepted=accepted,
                step_norm=float(np.linalg.norm(alpha*delta)))
            if accepted:
                x, info = trial, candidate
                break
        else:
            return None, info, 'line_search_stalled'
    raise AssertionError('Unreachable')


def lbfgs_retract(x, evaluate, metric, *, record=lambda row: None,
                  max_steps=1000, tolerance=2e-10):
    """Minimize scaled constraint residuals in fixed metric coordinates.

    Unlike the normal-only method, L-BFGS retains curvature across accepted
    steps. The original point is the affine origin, so the initial optimizer
    variable is zero. All evaluations and accepted iterates are retained.
    """
    from scipy.optimize import minimize
    from dfthcsos_block_metric import BlockMetric
    x = np.array(x, dtype=float, copy=True)
    if isinstance(metric, BlockMetric):
        factors = [(ids, np.linalg.cholesky(inv)) for ids, inv in metric.blocks]
        def transform(z, transpose=False):
            out = np.empty_like(z)
            for ids, factor in factors:
                out[ids] = (factor.T if transpose else factor)@z[ids]
            return out
    else:
        scale = np.sqrt(metric)
        def transform(z, transpose=False):
            return z*scale
    best = None
    calls = 0
    class Converged(Exception):
        pass
    def objective(z):
        nonlocal best, calls
        point = x+transform(z)
        info = evaluate(point)
        c, jac = info[2:4]
        merit = float(c@c/2)
        calls += 1
        record(dict(kind='evaluation', calls=calls, merit=merit,
                    constraints=c.tolist(), metrics=info[4]))
        if best is None or merit < best[0]:
            best = merit, point.copy(), info
        if np.max(np.abs(c)) < tolerance:
            raise Converged()
        return merit, transform(jac.T@c, transpose=True)
    try:
        result = minimize(objective, np.zeros_like(x), jac=True, method='L-BFGS-B',
                          options=dict(maxiter=max_steps, maxls=30, maxcor=20,
                                       ftol=1e-15, gtol=1e-12))
    except Converged:
        return best[1], best[2], 'converged'
    status = 'residual_minimization_stalled' if result.success else str(result.message)
    return None, best[2], status
