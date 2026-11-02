# SPDX-License-Identifier: Apache-2.0
import unittest
from invsqrt_quadratic_span import quadratic_bound, relations


def tables(bits):
    return [sum(1 << x for x in range(1 << bits) if x >> j & 1) for j in range(bits)]


class QuadraticSpanTests(unittest.TestCase):
    def test_two_independent_products_require_two_ands(self):
        a,b,c,d=tables(4)
        result=quadratic_bound([a,b,c,d],(a&b)^(c&d),one=(1<<16)-1)
        self.assertEqual(result['kernel_dimension'],0)
        self.assertEqual(result['minimum_and_lower_bound'],2)

    def test_retained_nonlinear_value_is_a_free_affine_control(self):
        a,b,c=tables(3); retained=a&b
        result=quadratic_bound([a,b,c,retained],(a&b)^(retained&c),one=255)
        self.assertGreater(result['kernel_dimension'],0)
        self.assertEqual(result['minimum_and_lower_bound'],1)
        result=quadratic_bound([a,b,c,retained],a&b,one=255)
        self.assertEqual(result['minimum_and_lower_bound'],0)

    def test_dependent_columns_kernel_is_exact(self):
        columns=[3,5,6,0]
        kernel=relations(columns)
        self.assertEqual(len(kernel),2)
        for mask in kernel:
            value=0
            for i,column in enumerate(columns):
                if mask>>i&1:value^=column
            self.assertEqual(value,0)

    def test_unrepresentable_target_and_budget_are_not_impossibility(self):
        a,b,c=tables(3)
        self.assertEqual(quadratic_bound([a,b,c],a&b&c,one=255)['status'],'outside_quadratic_span')
        self.assertEqual(quadratic_bound([a,b,c,a&b],a&b,one=255,max_kernel=0)['status'],'kernel_budget_exceeded')


if __name__=='__main__':unittest.main()
