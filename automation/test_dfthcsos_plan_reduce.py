"""Exercise Boolean dependence, including the linear correction a*a = a."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'generators'))
from dfthcsos_plan_reduce import evaluate, reduce_plan, truth_tables


class PlanReductionTest(unittest.TestCase):
    def test_duplicate_products_merge_fanout(self):
        term = {'a': {'low': 2, 'high': 0}, 'b': {'low': 0, 'high': 2}}
        plan = {'pure': {}, 'products': [{**term, 'fanout': 3}, {**term, 'fanout': 5}]}
        reduced, report = reduce_plan(plan, 64)
        self.assertEqual(report['remaining_products'], 1)
        self.assertEqual(reduced['products'][0]['fanout'], 6)
        self.assertEqual(evaluate(reduced, truth_tables(64), 64),
                         [6 if (a & 17) == 17 else 0 for a in range(64)])

    def test_square_reduces_to_linear(self):
        form = {'low': 2, 'high': 2}
        plan = {'pure': {}, 'products': [{'a': form, 'b': form, 'fanout': 9}]}
        reduced, report = reduce_plan(plan, 64)
        self.assertEqual(report['remaining_products'], 0)
        self.assertEqual(evaluate(reduced, truth_tables(64), 64),
                         [9 if bool(a & 1) != bool(a & 16) else 0 for a in range(64)])

    def test_relation_with_linear_correction_and_truncated_domain(self):
        a = {'low': 2, 'high': 0}
        b = {'low': 0, 'high': 2}
        ab = {'low': 2, 'high': 2}
        plan = {'pure': {'1': 7}, 'products': [
            {'a': a, 'b': b, 'fanout': 7}, {'a': a, 'b': ab, 'fanout': 7}]}
        reduced, _ = reduce_plan(plan, 49)
        self.assertEqual(evaluate(reduced, truth_tables(49), 49), [0] * 49)
        self.assertEqual(reduced['products'], [])


if __name__ == '__main__':
    unittest.main()
