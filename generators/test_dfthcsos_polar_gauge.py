"""Check KKT optimality and physical invariants independently of ADMM progress."""
import unittest
import numpy as np
from dfthcsos_polar_gauge import prox_squared_l1, optimize_gauge, objective


class PolarGaugeTests(unittest.TestCase):
    def test_prox_kkt_signed_ties_and_zeros(self):
        rng=np.random.default_rng(20261030)
        v=rng.normal(size=(2,17,4));v[:,:,0]=0;v[:,0:3,1]=2
        for rho in (0.01,1,100):
            x=prox_squared_l1(v,rho)
            threshold=np.sum(abs(x),axis=-2,keepdims=True)/2
            residual=rho*(v-x)
            active=abs(x)>1e-13
            np.testing.assert_allclose(residual[active],np.broadcast_to(threshold*np.sign(x),x.shape)[active],atol=1e-12)
            self.assertTrue(np.all(abs(residual[~active])<=np.broadcast_to(threshold,x.shape)[~active]+1e-12))

    def test_prox_scalar_closed_form(self):
        v=np.array([[-3.,0.,7.]])
        np.testing.assert_allclose(prox_squared_l1(v,2),v*4/5)

    def test_joint_gauge_lowers_dense_rotated_sparse_example(self):
        angle=.31
        q=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        a=(np.diag([2.,1.]) @ q)[None,:,:]
        best,rotation,report=optimize_gauge(a,[.1,1,10],100)
        np.testing.assert_allclose(best,a @ rotation,atol=1e-12)
        np.testing.assert_allclose(best @ best.swapaxes(-1,-2),a @ a.swapaxes(-1,-2),atol=1e-12)
        self.assertLess(float(objective(best).sum()),float(objective(a).sum())*.85)
        self.assertLess(report['gram_max_abs_drift'],1e-12)

    def test_rank_deficient_factors_remain_finite(self):
        a=np.array([[[1.,0.,0.],[0.,0.,0.],[2.,0.,0.],[0.,0.,0.]]])
        best,_,report=optimize_gauge(a,[.1,10],5)
        self.assertTrue(np.isfinite(best).all())
        self.assertLessEqual(report['lambda_h2_after'],report['lambda_h2_before'])

    def test_invalid_penalty_rejected(self):
        for rho in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):prox_squared_l1(np.ones((3,2)),rho)


if __name__=='__main__':unittest.main()
