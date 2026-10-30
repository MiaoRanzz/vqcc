"""Validate physical-factor truncation without an expensive chemistry verifier."""
import unittest
import numpy as np
from dfthcsos_rank_screen import truncate_factors
from dfthcsos.scoreinfra.dfthc_math import reconstruct_x


class RankScreenTests(unittest.TestCase):
    def test_truncation_residual_matches_singular_value_certificate(self):
        rng=np.random.default_rng(20261030)
        w=rng.normal(size=(2,7,4));h=rng.normal(size=(2,4));u=rng.normal(size=(2,7,3))
        reduced,offset,report,q=truncate_factors(w,h,u,3)
        old=reconstruct_x(u,w).reshape(2,4,-1)
        new=reconstruct_x(u,reduced).reshape(2,3,-1)
        np.testing.assert_allclose(new,q.swapaxes(-1,-2)@old,atol=2e-14)
        np.testing.assert_allclose(offset,(h[:,None,:]@q)[:,0,:],atol=1e-14)
        delta=old.swapaxes(-1,-2)@old-new.swapaxes(-1,-2)@new
        np.testing.assert_allclose(np.linalg.norm(delta,axis=(-2,-1)),report['per_group_two_body_truncation_frobenius'],atol=2e-13)
        self.assertGreaterEqual(float(np.linalg.eigvalsh(delta).min()),-1e-13)

    def test_invalid_rank_is_rejected(self):
        for rank in (0,3,4):
            with self.assertRaises(ValueError):truncate_factors(np.ones((1,4,3)),np.ones((1,3)),np.ones((1,4,2)),rank)


if __name__=='__main__':unittest.main()
