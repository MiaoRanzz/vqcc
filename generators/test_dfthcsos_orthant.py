import unittest
import numpy as np
from dfthcsos_orthant import tangent_pseudogradient, face_project, orthant_trial


class OrthantTests(unittest.TestCase):
    def test_smooth_face_is_tangent_projection(self):
        rng = np.random.default_rng(16)
        x = rng.normal(size=30); g = rng.normal(size=30); j = rng.normal(size=(3,30))
        pg, active, _ = tangent_pseudogradient(x,g,np.ones(30),j)
        np.testing.assert_allclose(pg,g-j.T@np.linalg.solve(j@j.T,j@g),atol=1e-10)
        self.assertTrue(active.all())

    def test_zero_subgradient_kkt_and_tangent(self):
        rng = np.random.default_rng(20261101)
        held = released = 0
        for constraints in (2,3):
            for _ in range(20):
                x = rng.normal(size=40); x[:20] = 0
                g = rng.normal(size=40); weights = rng.uniform(.1,2,size=40)
                j = rng.normal(size=(constraints,40))
                pg, active, info = tangent_pseudogradient(x,g,weights,j)
                np.testing.assert_allclose(j@pg,0,atol=1e-8)
                u = j/np.linalg.norm(j,axis=1)[:,None]
                raw = g+u.T@np.array(info['dual'])
                zero = x==0
                np.testing.assert_allclose(pg[~zero],raw[~zero],atol=1e-10)
                np.testing.assert_allclose(pg[zero],np.sign(raw[zero])*np.maximum(np.abs(raw[zero])-weights[zero],0),atol=1e-10)
                d = face_project(rng.normal(size=40),j,active)
                np.testing.assert_allclose(j@d,0,atol=1e-8)
                self.assertTrue(np.all(d[~active]==0))
                held += np.count_nonzero(zero & ~active)
                released += np.count_nonzero(zero & active)
        self.assertGreater(held,0); self.assertGreater(released,0)

    def test_orthant_reaches_zero_and_releases(self):
        result=orthant_trial(np.array([1.,-1.,0.,0.]),np.array([-2.,2.,3.,-4.]),1.,np.array([1.,-1.,-1.,1.]))
        np.testing.assert_array_equal(result,[0.,0.,3.,-4.])


if __name__=='__main__': unittest.main()
