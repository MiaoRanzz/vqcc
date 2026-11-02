# SPDX-License-Identifier: Apache-2.0
import unittest
import numpy as np
import test_dfthcsos_fixed_words as fixtures
from screen_dfthcsos_rank_residual import two_body_value_gradient


class ResidualTests(unittest.TestCase):
    setUp=fixtures.FixedWordTests.setUp

    def test_two_body_value_and_gradient_agree_with_full_model(self):
        val,g=two_body_value_gradient(self.m,self.w)
        metrics,gradients=self.m.evaluate(self.w,self.d,True)
        self.assertAlmostEqual(val,metrics['error_2']**2,places=10)
        np.testing.assert_allclose(g,gradients['error_2_squared'][0],atol=1e-12)
        dw=self.rng.normal(size=self.w.shape);eps=1e-6
        fp,_=two_body_value_gradient(self.m,self.w+eps*dw)
        fm,_=two_body_value_gradient(self.m,self.w-eps*dw)
        self.assertAlmostEqual((fp-fm)/(2*eps),float((g*dw).sum()),delta=1e-5)


if __name__=='__main__':unittest.main()
