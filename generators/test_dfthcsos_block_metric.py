# SPDX-License-Identifier: Apache-2.0
"""Analytic block curvature, masking, and constrained inverse checks."""
import unittest
import numpy as np
from dfthcsos_block_metric import column_blocks, BlockMetric, tangent, correction
from dfthcsos_curvature import residual_diagonal
import test_dfthcsos_fixed_words as fixtures


class BlockMetricTests(unittest.TestCase):
    setUp = fixtures.FixedWordTests.setUp

    def test_blocks_match_full_residual_jacobian(self):
        w, d = self.w, self.d
        h = d+w.sum(axis=1)
        x = np.r_[w.ravel(), h.ravel()]
        def residual(z):
            wz = z[:w.size].reshape(w.shape)
            dz = z[w.size:].reshape(h.shape)-wz.sum(axis=1)
            xx = (wz.swapaxes(1, 2)@self.m.ar).reshape(-1, self.m.ar.shape[-1])
            hh = self.m.h0-np.einsum('rb,rbpq->pq', np.sum(wz*dz[:, None, :], axis=2), self.m.a)
            return np.r_[(xx.T@xx).ravel(), hh.ravel()]
        jac = []
        for i in range(len(x)):
            e = np.zeros_like(x); e[i] = 1e-6
            jac.append((residual(x+e)-residual(x-e))/(2e-6))
        gram = 2*np.array(jac)@np.array(jac).T
        diagonal = residual_diagonal(self.m, w, d)
        all_indices = []
        for indices, block in column_blocks(self.m, w, d):
            np.testing.assert_allclose(block, gram[np.ix_(indices, indices)], rtol=2e-8, atol=2e-8)
            np.testing.assert_allclose(np.diag(block), diagonal[indices], rtol=2e-12, atol=2e-12)
            all_indices.extend(indices)
        self.assertEqual(sorted(all_indices), list(range(len(x))))

    def test_diagonal_interface_matches_existing_metric(self):
        from dfthcsos_curvature import tangent_project, normal_correction
        j = self.rng.normal(size=(3, 20))
        g = self.rng.normal(size=20)
        metric = np.exp(self.rng.normal(size=20))
        c = np.array([.1, -.2, .3])
        np.testing.assert_array_equal(tangent(g, j, metric), tangent_project(g, j, metric))
        np.testing.assert_array_equal(correction(c, j, metric), normal_correction(c, j, metric))

    def test_masked_spd_inverse_and_tangent(self):
        mask = self.rng.random(self.w.size+self.d.size) > .3
        metric = BlockMetric(self.m, self.w, self.d, mask)
        dense = metric.apply(np.eye(mask.sum()))
        np.testing.assert_allclose(dense, dense.T, atol=1e-12)
        self.assertGreater(np.linalg.eigvalsh(dense).min(), 0)
        j = self.rng.normal(size=(3, int(mask.sum())))
        g = self.rng.normal(size=int(mask.sum()))
        v = -tangent(metric.apply(g), j, metric)
        np.testing.assert_allclose(j@v, 0, atol=1e-11)
        self.assertLess(g@v, 0)
        c = np.array([.1, -.2, .3])
        np.testing.assert_allclose(j@correction(c, j, metric), c, atol=1e-12)


if __name__ == '__main__':
    unittest.main()
