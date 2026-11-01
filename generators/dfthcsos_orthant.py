"""Orthant-aware tangent directions for the fixed-word chemistry experiment.

The minimum-norm constrained L1 subgradient is solved in the small constraint
dual. Zero coordinates with a vanishing pseudo-gradient remain on their face;
nonzero coordinates may reach zero but cannot jump across it in one trial.
This is a numerical search method, not a scientific acceptance test.
"""
from __future__ import annotations

import numpy as np


def tangent_pseudogradient(x, gradient, weights, jac, tolerance=1e-10):
    """Find the minimum-norm tangent L1 subgradient, including exact zeros.

    Minimize 1/2 ||soft(g_smooth + J.T*dual, weights)||^2 on zero
    coordinates and the ordinary quadratic on nonzero coordinates. The dual
    gradient J*pg vanishes at a solution. Jacobian rows are normalized first.
    """
    norms = np.linalg.norm(jac, axis=1)
    if np.any(norms == 0):
        raise ValueError('Degenerate constraint Jacobian')
    u = jac / norms[:, None]
    zero = x == 0

    def evaluate(dual):
        raw = gradient + u.T @ dual
        pg = raw.copy()
        pg[zero] = np.sign(raw[zero]) * np.maximum(np.abs(raw[zero])-weights[zero], 0)
        active = (~zero) | (pg != 0)
        return pg, u @ pg, active

    dual = -np.linalg.lstsq(u @ u.T, u @ gradient, rcond=1e-12)[0]
    for iteration in range(80):
        pg, residual, active = evaluate(dual)
        norm = float(np.linalg.norm(residual))
        if norm <= tolerance:
            return pg, active, dict(iterations=iteration, residual=norm, dual=dual.tolist())
        v = u[:, active]
        delta = np.linalg.lstsq(v @ v.T, residual, rcond=1e-12)[0]
        for backtrack in range(30):
            trial = dual - 2.**(-backtrack)*delta
            if np.linalg.norm(evaluate(trial)[1]) < norm:
                dual = trial
                break
        else:
            raise RuntimeError('Pseudo-gradient dual stalled')
    raise RuntimeError('Pseudo-gradient dual iteration limit')


def face_project(v, jac, active):
    """Project onto J*d=0 while leaving inactive coordinates exactly zero."""
    result = np.zeros_like(v)
    j = jac[:, active]
    norms = np.linalg.norm(j, axis=1)
    if np.any(norms == 0):
        raise ValueError('Degenerate active face')
    u = j / norms[:, None]
    result[active] = v[active] - u.T @ np.linalg.lstsq(u @ u.T, u @ v[active], rcond=1e-12)[0]
    return result


def orthant_trial(x, direction, step, pseudo_gradient):
    orthant = np.where(x != 0, np.sign(x), np.sign(-pseudo_gradient))
    trial = x + step*direction
    trial[trial*orthant <= 0] = 0
    return trial
