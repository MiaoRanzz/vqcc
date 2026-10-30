"""Numerical tests of the piecewise gauge minimum and Hamiltonian invariants."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'generators'))
import numpy as np
from dfthcsos_gauge_breakpoints import best_pair_rotation, exact_sweep


class BreakpointTests(unittest.TestCase):
    def test_pair_beats_dense_grid_including_sparse_and_degenerate_columns(self):
        rng = np.random.default_rng(2026103015)
        for size in (1, 3, 12):
            for sparse in (False, True):
                x,y = rng.normal(size=(2,size))
                if sparse:x[::2]=0;y[1::2]=0
                theta,score=best_pair_rotation(x,y)
                t=np.linspace(0,np.pi/2,10001)[:,None]
                grid=(abs(np.cos(t)*x+np.sin(t)*y).sum(axis=1)**2
                      +abs(-np.sin(t)*x+np.cos(t)*y).sum(axis=1)**2)
                self.assertLessEqual(score,grid.min()+1e-9)
                self.assertAlmostEqual(score,abs(np.cos(theta)*x+np.sin(theta)*y).sum()**2
                                       +abs(-np.sin(theta)*x+np.cos(theta)*y).sum()**2)
        self.assertEqual(best_pair_rotation(np.zeros(3),np.zeros(3)),(0.0,0.0))

    def test_sweep_preserves_gram_and_native_offset(self):
        rng=np.random.default_rng(2026103016);w=rng.normal(size=(2,7,5));h=rng.normal(size=(2,5))
        v,k,r=exact_sweep(w,h)
        a=np.concatenate((w,h[:,None,:]),axis=1);b=np.concatenate((v,k[:,None,:]),axis=1)
        np.testing.assert_allclose(a@a.swapaxes(-1,-2),b@b.swapaxes(-1,-2),atol=1e-12)
        np.testing.assert_allclose(np.einsum('rbc,rc->rb',w,h-w.sum(axis=1)),
                                   np.einsum('rbc,rc->rb',v,k-v.sum(axis=1)),atol=1e-12)
        self.assertLessEqual(r['lambda_h2_after'],r['lambda_h2_before']);self.assertTrue(r['complete'])
        self.assertEqual(r['tried_pairs'],20)


if __name__=='__main__':unittest.main()
