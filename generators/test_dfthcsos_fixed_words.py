import unittest
import numpy as np
from dfthcsos_fixed_words import FixedWordModel, near_identity_rank_drop, pack_symmetric

class FixedWordTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(80271);self.rng=rng
        u=rng.normal(size=(2,3,4));z=rng.normal(size=(4,4));h0=(z+z.T)/2
        f=rng.normal(size=(5,4,4));f=(f+f.swapaxes(-1,-2))/2
        t=np.einsum('apq,ast->pqst',f,f)
        self.m=FixedWordModel(u,t,h0,10.)
        _,q=np.linalg.eigh(h0);self.m.one_body_vectors=q.T
        self.w=rng.normal(size=(2,3,2))*.2;self.d=rng.normal(size=(2,2))*.1
        self.target=t
    def test_isometry_and_direct_residual(self):
        x=np.einsum('rbc,rbpq->rcpq',self.w,self.m.a)
        direct=np.einsum('rcpq,rcst->pqst',x,x)-self.target
        m=self.m.evaluate(self.w,self.d)
        self.assertAlmostEqual(m['error_2'],np.linalg.norm(direct),places=11)
        a=self.rng.normal(size=(4,4));a=(a+a.T)/2
        self.assertAlmostEqual(np.linalg.norm(a),np.linalg.norm(pack_symmetric(a)),places=13)
    def test_gradients(self):
        metrics,grads=self.m.evaluate(self.w,self.d,True)
        dw=self.rng.normal(size=self.w.shape);dd=self.rng.normal(size=self.d.shape)
        eps=1e-6
        lo=self.m.evaluate(self.w-eps*dw,self.d-eps*dd)
        hi=self.m.evaluate(self.w+eps*dw,self.d+eps*dd)
        for key,(gw,gd) in grads.items():
            name=key.replace('_squared','');power=2 if key.endswith('_squared') else 1
            numerical=(hi[name]**power-lo[name]**power)/(2*eps)
            analytic=np.sum(gw*dw)+np.sum(gd*dd)
            self.assertAlmostEqual(numerical,analytic,delta=1e-6*max(1,abs(analytic)),msg=key)
    def test_rank_projection(self):
        w,d,records,q=near_identity_rank_drop(self.w,self.d,self.m.ar)
        for r in range(2):
            np.testing.assert_allclose(q[r].T@q[r],np.eye(1),atol=1e-12)
            x=self.w[r].T@self.m.ar[r]
            left,_,_=np.linalg.svd(x,full_matrices=False)
            np.testing.assert_allclose(q[r]@q[r].T,left[:,:1]@left[:,:1].T,atol=1e-12)
            self.assertAlmostEqual(records[r]['lambda_h2'],min(v['lambda_h2'] for v in records[r]['choices']))
    def test_cache(self):
        # Reusing the exact-input cache preserves the numerical model.
        old=self.m.evaluate(self.w,self.d)
        m=FixedWordModel(np.ones((2,3,4)),self.target,self.m.h0,10.,cache=self.m.cache())
        m.a=self.m.a;m.one_body_vectors=self.m.one_body_vectors
        np.testing.assert_allclose(list(old.values()),list(m.evaluate(self.w,self.d).values()),equal_nan=True)


class StoredCoordinateTests(unittest.TestCase):
    setUp = FixedWordTests.setUp
    def test_stored_weight_and_full_objective_gradients(self):
        # NPZ uses h=d+sum(w); changing w at fixed h also changes native d.
        w,d=self.w,self.d;h=d+w.sum(axis=1)
        dw=self.rng.normal(size=w.shape);dh=self.rng.normal(size=h.shape)
        m,g=self.m.evaluate(w,d,True)
        eps=1e-6
        lo=self.m.evaluate(w-eps*dw,(h-eps*dh)-(w-eps*dw).sum(axis=1))
        hi=self.m.evaluate(w+eps*dw,(h+eps*dh)-(w+eps*dw).sum(axis=1))
        for key in ['Lambda','E_gap']:
            gw,gd=g[key]
            numerical=(hi[key]-lo[key])/(2*eps)
            analytical=np.sum((gw-gd[:,None,:])*dw)+np.sum(gd*dh)
            self.assertAlmostEqual(numerical,analytical,delta=1e-6*max(1,abs(analytical)))
        def radicand(a):return a['E_gap']*(2*a['Lambda']-a['E_gap'])
        lw,ld=g['Lambda'];ew,ed=g['E_gap']
        gw=2*m['E_gap']*lw+2*(m['Lambda']-m['E_gap'])*ew
        gd=2*m['E_gap']*ld+2*(m['Lambda']-m['E_gap'])*ed
        analytical=np.sum((gw-gd[:,None,:])*dw)+np.sum(gd*dh)
        numerical=(radicand(hi)-radicand(lo))/(2*eps)
        self.assertAlmostEqual(numerical,analytical,delta=1e-6*max(1,abs(analytical)))


if __name__ == "__main__":
    unittest.main()
