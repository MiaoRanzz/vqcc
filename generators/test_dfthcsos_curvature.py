import unittest

import numpy as np

from dfthcsos_curvature import residual_diagonal, inverse_metric, tangent_project, normal_correction
from test_dfthcsos_fixed_words import FixedWordTests


class CurvatureTests(unittest.TestCase):
    setUp = FixedWordTests.setUp

    def test_diagonal_matches_finite_difference_residual_jacobian(self):
        w,d=self.w,self.d
        h=d+w.sum(axis=1)
        x=np.r_[w.ravel(),h.ravel()]
        def residual(z):
            wz=z[:w.size].reshape(w.shape)
            dz=z[w.size:].reshape(h.shape)-wz.sum(axis=1)
            xx=(wz.swapaxes(1,2)@self.m.ar).reshape(-1,self.m.ar.shape[-1])
            hh=self.m.h0-np.einsum('rb,rbpq->pq',np.sum(wz*dz[:,None,:],axis=2),self.m.a)
            return np.r_[(xx.T@xx).ravel(),hh.ravel()]
        diag=[]
        for i in range(len(x)):
            e=np.zeros_like(x);e[i]=1e-6
            derivative=(residual(x+e)-residual(x-e))/(2e-6)
            diag.append(2*derivative@derivative)
        np.testing.assert_allclose(residual_diagonal(self.m,w,d),diag,rtol=2e-8,atol=2e-9)

    def test_tangency_descent_and_normal_constraint_repair(self):
        j=self.rng.normal(size=(3,20));g=self.rng.normal(size=20)
        metric=inverse_metric(np.exp(self.rng.normal(size=20)))
        v=-tangent_project(metric*g,j,metric)
        np.testing.assert_allclose(j@v,0,atol=1e-12)
        self.assertLess(g@v,0)
        c=np.array([.1,-.2,.3])
        np.testing.assert_allclose(j@normal_correction(c,j,metric),c,atol=1e-12)


if __name__=='__main__':unittest.main()
