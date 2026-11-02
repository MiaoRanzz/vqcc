# SPDX-License-Identifier: Apache-2.0
import unittest
import numpy as np
from dfthcsos_retraction import damped_retract, lbfgs_retract


class RetractionTests(unittest.TestCase):
    def test_backtracking_recovers_large_nonlinear_violation(self):
        def evaluate(x):
            c = np.array([x[0]**2-1])
            return 0., np.zeros(1), c, np.array([[2*x[0]]]), {'x': float(x[0])}
        rows = []
        x, info, status = damped_retract([.01], evaluate, np.ones(1),
                                         relative_radius=100, record=rows.append)
        self.assertEqual(status, 'converged')
        self.assertAlmostEqual(x[0], 1.)
        self.assertTrue(any(r.get('accepted') is False for r in rows))
        accepted = [r['merit'] for r in rows if r['kind']=='initial' or r.get('accepted')]
        self.assertTrue(all(a>b for a,b in zip(accepted, accepted[1:])))

    def test_dependent_constraints_retain_both_residuals(self):
        def evaluate(x):
            return 0., np.zeros(2), np.array([x.sum()-1, 2*x.sum()-2]), np.array([[1.,1.],[2.,2.]]), {}
        x, info, status = damped_retract([0.,0.], evaluate, np.array([1.,2.]))
        self.assertEqual(status, 'converged')
        np.testing.assert_allclose(x, [1/3,2/3], atol=1e-12)
        np.testing.assert_allclose(info[2], 0, atol=1e-12)

    def test_lbfgs_scaled_coordinates(self):
        def evaluate(x):
            c=np.array([x[0]**2-1, x[1]-2])
            return 0., np.zeros(2), c, np.array([[2*x[0],0.],[0.,1.]]), {}
        rows=[]
        x,info,status=lbfgs_retract([.2,0.],evaluate,np.array([4.,.1]),record=rows.append)
        self.assertEqual(status,'converged')
        np.testing.assert_allclose(x,[1.,2.],atol=1e-8)
        self.assertGreater(len(rows),1)

    def test_lbfgs_column_block_transform(self):
        from dfthcsos_block_metric import BlockMetric
        import test_dfthcsos_fixed_words as fixtures
        fixture=fixtures.FixedWordTests();fixture.setUp()
        count=fixture.w.size+fixture.d.size
        metric=BlockMetric(fixture.m,fixture.w,fixture.d,np.ones(count,dtype=bool))
        jac=fixture.rng.normal(size=(3,count));target=np.array([.1,-.2,.3])
        def evaluate(x):
            return 0.,np.zeros(count),jac@x-target,jac,{}
        x,info,status=lbfgs_retract(np.zeros(count),evaluate,metric)
        self.assertEqual(status,'converged')
        np.testing.assert_allclose(jac@x,target,atol=1e-9)

    def test_step_budget_and_inconsistent_constraints_fail_explicitly(self):
        def evaluate(x):
            return 0., np.zeros(1), np.array([x[0]-1, x[0]+1]), np.ones((2,1)), {}
        x, _, status = damped_retract([0.], evaluate, np.ones(1))
        self.assertIsNone(x)
        self.assertEqual(status, 'no_descent_direction')
        x, _, status = damped_retract([0.], evaluate, np.ones(1), max_steps=0)
        self.assertIsNone(x)
        self.assertEqual(status, 'step_limit')


if __name__ == '__main__':
    unittest.main()
