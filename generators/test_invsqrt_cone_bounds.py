# SPDX-License-Identifier: Apache-2.0
"""Check bounds with sequential dependencies and old target values."""
import unittest
from invsqrt_cone_bounds import lower_bound, rank
from invsqrt_lookup_resynth import INPUTS, ALL


class ConeBoundTests(unittest.TestCase):
    def test_sequential_dependency_needs_two_products(self):
        a, b, c = [INPUTS[i] for i in (14, 15, 16)]
        before = {0: a, 1: b, 2: c, 3: 0, 4: 0}
        after = before.copy()
        after[3] = a & b; after[4] = a & b & c
        self.assertEqual(lower_bound(before, after), 2)

    def test_dirty_target_is_an_incoming_value(self):
        a, b, old = [INPUTS[i] for i in (14, 15, 16)]
        before = {0: a, 1: b, 2: old}
        self.assertEqual(lower_bound(before, {0: a, 1: b, 2: old ^ (a & b)}), 1)
        self.assertEqual(lower_bound(before, {0: a, 1: b, 2: old ^ a ^ ALL}), 0)

    def test_shared_product_bound_is_not_sum_of_outputs(self):
        a, b = INPUTS[14], INPUTS[15]
        before = {0: a, 1: b, 2: 0, 3: 0}
        self.assertEqual(lower_bound(before, {0: a, 1: b, 2: a & b, 3: (a & b)^a}), 1)
        self.assertEqual(rank([a, b, a^b, 0]), 2)


if __name__ == '__main__':
    unittest.main()
