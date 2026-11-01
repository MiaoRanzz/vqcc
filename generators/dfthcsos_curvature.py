"""Diagonal residual metric in stored (w, H2_I) coordinates.

This is a numerical search heuristic, not a circuit or acceptance criterion.
The two-body term is the exact Gauss-Newton diagonal of X.T @ X. The one-body
term uses the derivative of the Hamiltonian before eigenvalue reassignment;
it is a surrogate for the fixed-word one-body residual's curvature.
"""
from __future__ import annotations

import numpy as np


def residual_diagonal(model, w, d):
    x = w.swapaxes(1, 2) @ model.ar
    a2 = np.sum(model.ar**2, axis=-1)
    x2 = np.sum(x**2, axis=-1)
    ax = model.ar @ x.swapaxes(1, 2)
    two = 4 * (a2[:, :, None] * x2[:, None, :] + ax**2)
    # At fixed h=d+sum_b(w), dH/dw = X - d*A, dH/dh = -X.
    one_w = x2[:, None, :] + d[:, None, :]**2 * a2[:, :, None] - 2*d[:, None, :]*ax
    one_h = x2
    return np.r_[(two + 2*np.maximum(one_w, 0)).ravel(), (2*one_h).ravel()]


def inverse_metric(diagonal, relative_floor=1e-3):
    diagonal = np.asarray(diagonal, dtype=float)
    if not np.all(np.isfinite(diagonal)) or np.any(diagonal < 0):
        raise ValueError('Residual metric must be finite and nonnegative')
    positive = diagonal[diagonal > 0]
    if not len(positive):
        return np.ones_like(diagonal)
    scale = np.median(positive)
    return scale / np.maximum(diagonal, relative_floor*scale)


def tangent_project(v, jacobian, inverse_diagonal):
    """Project a vector onto Jv=0 with the diagonal metric's normal space."""
    norms = np.linalg.norm(jacobian, axis=1)
    u = jacobian / norms[:, None]
    du = u * inverse_diagonal
    return v - du.T @ np.linalg.solve(du @ u.T, u @ v)


def normal_correction(constraints, jacobian, inverse_diagonal):
    norms = np.linalg.norm(jacobian, axis=1)
    u = jacobian / norms[:, None]
    du = u * inverse_diagonal
    return du.T @ np.linalg.solve(du @ u.T, constraints / norms)
