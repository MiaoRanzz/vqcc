# SPDX-License-Identifier: Apache-2.0
"""Column-block Gauss-Newton metric in stored (w, H2_I) coordinates.

Each block contains one (r,c) column of w plus H2_I[r,c]. Cross-column
curvature is omitted. The one-body term is the same pre-eigenvalue surrogate
as dfthcsos_curvature; this is a search heuristic, never an accuracy gate.
"""
from __future__ import annotations

import numpy as np


def column_blocks(model, w, d):
    """Yield full-coordinate indices and 2*J.T@J for each column."""
    r, b, c = w.shape
    x = w.swapaxes(1, 2) @ model.ar
    for group in range(r):
        aa = model.ar[group] @ model.ar[group].T
        for col in range(c):
            xx = float(x[group, col] @ x[group, col])
            ax = model.ar[group] @ x[group, col]
            dc = d[group, col]
            block = np.empty((b + 1, b + 1))
            block[:b, :b] = 4*(xx*aa + np.outer(ax, ax))
            block[:b, :b] += 2*(xx-dc*(ax[:, None]+ax[None, :])+dc*dc*aa)
            block[:b, b] = block[b, :b] = 2*(-xx+dc*ax)
            block[b, b] = 2*xx
            indices = np.r_[(group*b+np.arange(b))*c+col, w.size+group*c+col]
            yield indices, block


class BlockMetric:
    """Fixed symmetric positive definite inverse with a relative ridge.

    Ridge is added before inversion, including to the scalar diagonal control
    when used in matched experiments. The shared scale is the median of the
    active positive diagonals. No eigenspace is selected by experiment outcome.
    """
    def __init__(self, model, w, d, mask, relative_floor=1e-3):
        if not 0 < relative_floor <= 1:
            raise ValueError('Relative floor must be in (0,1]')
        mask = np.asarray(mask, dtype=bool)
        if mask.shape != (w.size+d.size,):
            raise ValueError('Mask must use full stored coordinates')
        self.size = int(mask.sum())
        active_index = np.full(len(mask), -1, dtype=int)
        active_index[mask] = np.arange(self.size)
        blocks = []
        diagonal = np.empty(self.size)
        for indices, matrix in column_blocks(model, w, d):
            local = np.flatnonzero(mask[indices])
            if not len(local):
                continue
            ids = active_index[indices[local]]
            block = matrix[np.ix_(local, local)]
            diagonal[ids] = np.diag(block)
            blocks.append((ids, block))
        if not np.all(np.isfinite(diagonal)) or np.any(diagonal < -1e-12):
            raise ValueError('Nonfinite or negative residual diagonal')
        positive = diagonal[diagonal > 0]
        self.scale = float(np.median(positive)) if len(positive) else 1.
        self.ridge = relative_floor*self.scale
        self.blocks = []
        inverse_diagonal = np.empty(self.size)
        for ids, block in blocks:
            regularized = (block+block.T)/2 + self.ridge*np.eye(len(ids))
            factor = np.linalg.cholesky(regularized)
            inv_l = np.linalg.solve(factor, np.eye(len(ids)))
            inverse = self.scale*(inv_l.T@inv_l)
            self.blocks.append((ids, inverse))
            inverse_diagonal[ids] = np.diag(inverse)
        self.diagonal_control = self.scale/(diagonal+self.ridge)
        self.summary = dict(blocks=len(self.blocks), variables=self.size,
            max_block_size=max((len(ids) for ids, _ in self.blocks), default=0),
            relative_floor=relative_floor, scale=self.scale, ridge=self.ridge,
            inverse_diagonal_range=[float(inverse_diagonal.min()), float(inverse_diagonal.max())])

    def apply(self, vectors):
        vectors = np.asarray(vectors)
        if vectors.shape[-1] != self.size:
            raise ValueError('Metric input dimension mismatch')
        result = np.empty_like(vectors, dtype=float)
        for ids, inverse in self.blocks:
            result[..., ids] = vectors[..., ids] @ inverse
        return result


def apply_metric(metric, vectors):
    return metric.apply(vectors) if isinstance(metric, BlockMetric) else vectors*metric


def tangent(v, jacobian, metric):
    norms = np.linalg.norm(jacobian, axis=1)
    u = jacobian/norms[:, None]
    du = apply_metric(metric, u)
    return v-du.T@np.linalg.solve(du@u.T, u@v)


def correction(constraints, jacobian, metric):
    norms = np.linalg.norm(jacobian, axis=1)
    u = jacobian/norms[:, None]
    du = apply_metric(metric, u)
    return du.T@np.linalg.solve(du@u.T, constraints/norms)
