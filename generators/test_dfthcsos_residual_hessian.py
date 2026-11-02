# SPDX-License-Identifier: Apache-2.0
import unittest
import numpy as np
import test_dfthcsos_fixed_words as fixtures
from dfthcsos_residual_hessian import ResidualCurvature, directional_check, OrthonormalCoordinates
from screen_dfthcsos_rank_residual import two_body_value_gradient


class CurvatureTests(unittest.TestCase):
    setUp = fixtures.FixedWordTests.setUp

    def test_exact_product_matches_directional_gradient(self):
        report = directional_check(self.m, self.w, two_body_value_gradient)
        self.assertLess(report['relative_error'], 1e-8)

    def test_symmetry_and_gauss_newton_positive_semidefinite(self):
        curvature = ResidualCurvature(self.m, self.w)
        a, b = self.rng.normal(size=(2, *self.w.shape))
        for gn in [False, True]:
            ha = curvature.apply(a, gauss_newton=gn)
            hb = curvature.apply(b, gauss_newton=gn)
            np.testing.assert_allclose(np.sum(a*hb), np.sum(b*ha), rtol=1e-12, atol=1e-12)
            if gn:
                dx = (a.swapaxes(1, 2) @ self.m.ar).reshape(curvature.x.shape)
                dr = dx.T @ curvature.x + curvature.x.T @ dx
                np.testing.assert_allclose(np.sum(a*ha), 2*np.sum(dr*dr), rtol=1e-12)
                self.assertGreaterEqual(np.sum(a*ha), 0.)

    def test_qr_coordinates_preserve_residual_and_pullback(self):
        import copy
        coords = OrthonormalCoordinates(self.m.ar)
        physical = copy.copy(self.m)
        physical.ar = coords.basis
        y = coords.encode(self.w)
        np.testing.assert_allclose(coords.decode(y), self.w, rtol=1e-12, atol=1e-12)
        f, g = two_body_value_gradient(self.m, self.w)
        transformed, gy = two_body_value_gradient(physical, y)
        self.assertAlmostEqual(f, transformed, places=10)
        np.testing.assert_allclose(coords.upper.swapaxes(1,2)@gy, g, rtol=1e-12, atol=1e-12)
        self.assertLess(directional_check(physical, y, two_body_value_gradient)['relative_error'], 1e-8)

    def test_exact_and_gn_agree_at_zero_residual(self):
        curvature = ResidualCurvature(self.m, self.w)
        curvature.residual[:] = 0
        v = self.rng.normal(size=self.w.shape)
        np.testing.assert_allclose(curvature.apply(v), curvature.apply(v, gauss_newton=True))


if __name__ == '__main__':
    unittest.main()
