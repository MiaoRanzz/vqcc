# SPDX-License-Identifier: Apache-2.0
"""Exact and Gauss-Newton Hessian products for fixed-word two-body fitting.

For X = stack_r(w_r.T @ A_r), F = ||X.T X - T||_F^2 + constant.
The exact Hessian includes the residual term, which can be indefinite.
No dense Hessian over coefficient variables is formed.
"""
from __future__ import annotations
import numpy as np


class ResidualCurvature:
    def __init__(self, model, w):
        self.ar = model.ar
        self.shape = w.shape
        self.x = (w.swapaxes(1, 2) @ self.ar).reshape(-1, self.ar.shape[-1])
        self.residual = self.x.T @ self.x - model.projected

    def apply(self, direction, *, gauss_newton=False):
        dx = (direction.swapaxes(1, 2) @ self.ar).reshape(self.x.shape)
        differential = dx.T @ self.x + self.x.T @ dx
        hx = 4 * (self.x @ differential)
        if not gauss_newton:
            hx += 4 * (dx @ self.residual)
        r, _, c = self.shape
        return self.ar @ hx.reshape(r, c, -1).swapaxes(1, 2)


def directional_check(model, w, value_gradient, seed=80271):
    """Fixed direction, selected before outcomes; this is a derivative check."""
    rng = np.random.default_rng(seed)
    direction = rng.normal(size=w.shape)
    direction /= np.linalg.norm(direction)
    exact = ResidualCurvature(model, w).apply(direction)
    epsilon = 1e-5
    _, plus = value_gradient(model, w + epsilon * direction)
    _, minus = value_gradient(model, w - epsilon * direction)
    measured = (plus - minus) / (2 * epsilon)
    relative_error = float(np.linalg.norm(exact - measured) / max(np.linalg.norm(exact), 1e-30))
    if not np.isfinite(relative_error) or relative_error > 2e-6:
        raise ValueError(f'Hessian directional check failed: {relative_error}')
    return dict(seed=seed, epsilon=epsilon, relative_error=relative_error,
                curvature=float(np.sum(direction * exact)))


class OrthonormalCoordinates:
    """Invertible within-group QR map; retain every direction, without truncation.

    A_r = R_r.T Q_r.T and y_r = R_r w_r imply w_r.T A_r = y_r.T Q_r.T.
    This removes the conditioning of A_r from the residual optimizer only.
    Returned checkpoints are always converted back to the original w variables.
    """
    def __init__(self, ar):
        q, self.upper = np.linalg.qr(ar.swapaxes(-1, -2), mode='reduced')
        self.basis = q.swapaxes(-1, -2)
        singular = np.linalg.svd(self.upper, compute_uv=False)
        self.conditions = singular[:, 0] / singular[:, -1]
        if not np.all(np.isfinite(self.conditions)) or np.max(self.conditions) > 1e8:
            raise ValueError('QR coordinate inverse too ill-conditioned; no directions discarded')

    def encode(self, w):
        return self.upper @ w

    def decode(self, y):
        return np.linalg.solve(self.upper, y)
