"""Differentiable fixed-word DFTHC model for numerical screening, not acceptance.

Independent implementation of the unchanged verifier's formulas. A Frobenius-
isometric symmetric packing and QR projection reduce the two-body residual to
its attainable subspace, retaining the orthogonal residual as a constant.
Native variables are w and d=H2_I-sum_b(w); fixed shifts come from load_inputs.
"""
from __future__ import annotations
import numpy as np
from scipy.linalg import qr
from scipy.optimize import linear_sum_assignment


def pack_symmetric(a):
    n = a.shape[-1]
    i, j = np.tril_indices(n)
    return a[..., i, j] * np.where(i == j, 1., np.sqrt(2.))


class FixedWordModel:
    def __init__(self, vectors, target, h0, energy_constant, *, cache=None):
        # vectors are [R,B,N], target is the shifted two-body Gram tensor.
        u = np.asarray(vectors, dtype=np.float64)
        u = u / np.linalg.norm(u, axis=-1, keepdims=True)
        self.a = u[..., :, None] * u[..., None, :]
        self.r, self.b, self.n = u.shape
        a = pack_symmetric(self.a).reshape(self.r*self.b, -1)
        self.h0 = np.asarray(h0, dtype=np.float64)
        self.energy_constant = float(energy_constant)
        if cache is None:
            i, j = np.tril_indices(self.n)
            scales = np.where(i == j, 1., np.sqrt(2.))
            t = target[i[:, None], j[:, None], i[None, :], j[None, :]]
            t = t * scales[:, None] * scales[None, :]
            q, upper = qr(a.T, mode='economic')
            projected = q.T @ t @ q
            # Direct difference avoids cancellation between two large norms.
            outside = t - q @ projected @ q.T
            self.outside_squared = float(np.sum(outside**2))
            self.projected = (projected + projected.T) / 2
            self.ar = upper.T.reshape(self.r, self.b, -1)
        else:
            self.ar = cache['ar']
            self.projected = cache['projected']
            self.outside_squared = float(cache['outside_squared'])
        self.one_body_vectors = None

    def cache(self):
        return dict(ar=self.ar, projected=self.projected,
                    outside_squared=self.outside_squared)

    def evaluate(self, w, d, gradients=False):
        w, d = np.asarray(w), np.asarray(d)
        c = w.shape[-1]
        x = (w.swapaxes(1, 2) @ self.ar).reshape(self.r*c, -1)
        delta = x.T @ x - self.projected
        error2sq = float(np.sum(delta**2) + self.outside_squared)
        wd = np.sum(w * d[:, None, :], axis=2)
        h = self.h0 - np.einsum('rb,rbpq->pq', wd, self.a)
        ev, z = np.linalg.eigh(h)
        rows, cols = linear_sum_assignment(-np.abs(self.one_body_vectors @ z))
        eigen_by_row = np.empty(self.n)
        eigen_by_row[rows] = ev[cols]
        v = self.one_body_vectors
        reconstructed = (v.T * eigen_by_row) @ v
        delta1 = reconstructed - h
        error1sq = float(np.sum(delta1**2))
        lh1 = float(np.abs(ev).sum())
        h2i = d + np.sum(w, axis=1)
        l1 = np.sum(np.abs(w), axis=1) + np.abs(h2i)
        lam = lh1 + float(np.sum(l1**2)/4)
        gap = self.energy_constant + lh1 - float(ev.sum()) + float(np.sum(d*d)/2)
        result = dict(error_1=np.sqrt(error1sq), error_2=np.sqrt(error2sq),
                      Lambda=lam, E_gap=gap,
                      lambda_eff=float(np.sqrt(gap*(2*lam-gap))) if 0 < gap < 2*lam else float('nan'))
        if not gradients:
            return result
        x_grad = (4*x @ delta).reshape(self.r,c,-1)
        g2w = self.ar @ x_grad.swapaxes(1,2)
        g2d = np.zeros_like(d)
        coeff_by_row = np.einsum('ip,pq,iq->i', v, delta1, v)
        coeff = np.empty(self.n); coeff[cols] = coeff_by_row[rows]
        g1h = 2*((z*coeff) @ z.T-delta1)
        signh = (z*np.sign(ev)) @ z.T
        def pullback(gh):
            ga = np.einsum('pq,rbpq->rb',gh,self.a)
            return -ga[:,:,None]*d[:,None,:], -np.sum(ga[:,:,None]*w,axis=1)
        g1w,g1d=pullback(g1h)
        glw,gld=pullback(signh)
        glw += .5*l1[:,None,:]*(np.sign(w)+np.sign(h2i)[:,None,:])
        gld += .5*l1*np.sign(h2i)
        ggw,ggd=pullback(signh-np.eye(self.n));ggd+=d
        grads=dict(error_1_squared=(g1w,g1d), error_2_squared=(g2w,g2d),
                   Lambda=(glw,gld), E_gap=(ggw,ggd))
        return result,grads


def from_inputs(inputs, arrays, cache=None):
    from dfthcsos.scoreinfra.dfthc_math import reconstruct_u_vectors
    brot=int(arrays['brot']);n=inputs.num_orbitals;r,b,_=inputs.w.shape
    vectors=reconstruct_u_vectors(arrays['angle_words']/2**(brot-1),arrays['tree_edges'])
    vectors/=np.linalg.norm(vectors,axis=1,keepdims=True)
    target=np.array(inputs.ref['tei'],dtype=np.float64)
    diagonal=np.arange(n)
    target[:,:,diagonal,diagonal]+=.5*inputs.S[:,:,None]
    target[diagonal,diagonal,:,:]+=.5*inputs.S[None,:,:]
    h0=inputs.ref['h1_thc']-.5*inputs.ref['electrons']*inputs.S+inputs.beta_1*np.eye(n)
    constant=inputs.energy_upper-inputs.ref['ecore']+inputs.ref['electrons']*inputs.beta_1
    model=FixedWordModel(vectors[n:].reshape(r,b,n),target,h0,constant,cache=cache)
    model.one_body_vectors=vectors[:n]
    return model


def near_identity_rank_drop(w,d,ar):
    """Drop the weakest physical singular direction with a sparse-gauge start.

    Among C Householder bases of that identical rank-(C-1) subspace, choose the
    least exact L1 normalization independently per group. This is deterministic
    gauge optimization, independent of verifier randomness.
    """
    ws,ds,records,projections=[],[],[],[]
    for wr,dr,ar_r in zip(w,d,ar):
        x=wr.T@ar_r
        left,singular,_=np.linalg.svd(x,full_matrices=False)
        v=left[:,-1];c=len(v);choices=[]
        for j in range(c):
            e=np.zeros(c);e[j]=1 if v[j]>=0 else -1
            direction=v-e
            if np.linalg.norm(direction)<1e-14:hh=np.eye(c)
            else:hh=np.eye(c)-2*np.outer(direction,direction)/np.dot(direction,direction)
            q=np.delete(hh,j,axis=1)
            neww=wr@q;newd=dr@q
            l1=np.abs(neww).sum(axis=0)+np.abs(newd+neww.sum(axis=0))
            choices.append((float(l1@l1/4),j,neww,newd,q))
        value,j,neww,newd,q=min(choices,key=lambda z:z[0])
        ws.append(neww);ds.append(newd);projections.append(q)
        records.append(dict(dropped_coordinate=j,smallest_singular_value=float(singular[-1]),
                            lambda_h2=value,choices=[dict(coordinate=a[1],lambda_h2=a[0]) for a in choices]))
    return np.array(ws),np.array(ds),records,np.array(projections)
