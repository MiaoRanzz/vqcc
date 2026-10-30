"""Deterministic orthogonal column gauge for DFTHC weights.

Rotate each pair of columns of [w; w_B] by the same real orthogonal matrix.
Then X rotates, native W = w_B - sum_b(w) rotates, and both sum_c X_c X_c
and sum_c W_c X_c are invariant. The column L1 normalization can decrease.
Independent implementation; no external optimization code copied.
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import minimize_scalar


def column_gauge(weights, identity_offsets, sweeps=4):
    w = np.array(weights, dtype=np.float64, copy=True)
    h = np.array(identity_offsets, dtype=np.float64, copy=True)
    if w.ndim != 3 or h.shape != (w.shape[0], w.shape[2]):
        raise ValueError('weight/identity shapes disagree')
    if not np.isfinite(w).all() or not np.isfinite(h).all() or type(sweeps) is not int or not 1 <= sweeps <= 8:
        raise ValueError('invalid weights or sweep count')
    a = np.concatenate((w, h[:, None, :]), axis=1)
    before = float(np.sum(np.sum(np.abs(a), axis=1)**2)/4)
    accepted = []
    grid = np.linspace(-np.pi/4, np.pi/4, 17)
    for sweep in range(sweeps):
        stride = 1 << sweep
        for rho in range(len(a)):
            for block in range(0, a.shape[2], 2*stride):
                for i in range(block, min(block+stride, a.shape[2])):
                    j=i+stride
                    if j>=a.shape[2]:continue
                    x,y=a[rho,:,i].copy(),a[rho,:,j].copy()
                    def objective(theta):
                        c,s=np.cos(theta),np.sin(theta)
                        return float(np.sum(np.abs(c*x+s*y))**2+np.sum(np.abs(-s*x+c*y))**2)
                    old=objective(0.0)
                    values=[objective(t) for t in grid]
                    k=int(np.argmin(values))
                    fit=minimize_scalar(objective,method='bounded',bounds=(grid[max(0,k-1)],grid[min(len(grid)-1,k+1)]),options={'xatol':1e-10,'maxiter':80})
                    choices=[(old,0.0),(values[k],float(grid[k])),(float(fit.fun),float(fit.x))]
                    new,theta=min(choices,key=lambda p:p[0])
                    if new < old - 1e-12*max(1.0,old):
                        c,s=np.cos(theta),np.sin(theta)
                        a[rho,:,i],a[rho,:,j]=c*x+s*y,-s*x+c*y
                        accepted.append(dict(sweep=sweep,rho=rho,i=i,j=j,theta=theta,reduction=(old-new)/4))
    after=float(np.sum(np.sum(np.abs(a),axis=1)**2)/4)
    return a[:,:-1,:],a[:,-1,:],dict(sweeps=sweeps,lambda_h2_before=before,lambda_h2_after=after,accepted_rotations=accepted)
