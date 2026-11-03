import itertools
import unittest
from invsqrt_clean_lifetimes import Algebra, ONE
from invsqrt_cache_spill import erase_lines, restore_lines, recipe_solver, transform, select_disjoint


class CacheSpillTests(unittest.TestCase):
    def test_quadratic_erasure_preserves_all_basis_states_and_measurement_branches(self):
        # q22 = 1 XOR q0 XOR q1*q2. The HMR phase and every correction matter.
        terms = [[], [0], [1, 2]]
        erase, measured = erase_lines(22, terms, 7)
        self.assertTrue(measured)
        for a, b, c, measurement in itertools.product(range(2), repeat=4):
            state = {0:a, 1:b, 2:c, 22:1 ^ a ^ (b & c)}
            initial = dict(state)
            phase = 0
            for line in erase + restore_lines(22, terms):
                f = line.split()
                if 'if' in f and not measurement:
                    continue
                q = [int(x[1:]) for x in f[1:] if x.startswith('q')]
                op = f[0]
                if op == 'HMR':
                    phase ^= measurement & state[q[0]]
                    state[q[0]] = 0
                elif op in ('NEG', 'Z', 'CZ'):
                    value = 1
                    for wire in q:
                        value &= state[wire]
                    phase ^= value
                elif op in ('X', 'CX', 'CCX'):
                    value = 1
                    for wire in q[:-1]:
                        value &= state[wire]
                    state[q[-1]] ^= value
                else:
                    self.fail(line)
            self.assertEqual(state, initial)
            self.assertEqual(phase, 0)

    def test_solver_never_uses_spilled_wire(self):
        alg = Algebra()
        a, b, c = [alg.fresh() for _ in range(3)]
        value = alg.xor(alg.mul(a, b), c)
        state = {0:a, 1:b, 2:c, 22:value}
        solve = recipe_solver(alg)
        self.assertIsNone(solve(value, state, 22, quadratic=False))
        terms = solve(value, state, 22)
        self.assertEqual({tuple(t) for t in terms}, {(2,), (0,1)})

    def test_transform_reproves_cached_recipe(self):
        text = 'CCX q0 q1 q22\nCX q2 q22\nX q3\nX q3\nCX q22 q4\n'
        plan = [dict(q=22, lo=2, hi=4, erase=[[2],[0,1]], restore=[[2],[0,1]])]
        out, measurements = transform(text, plan)
        self.assertEqual(measurements, 1)
        self.assertIn('HMR q22 b0', out)
        bad = [{**plan[0], 'restore': [[0,1]]}]
        with self.assertRaisesRegex(ValueError, 'both boundary'):
            transform(text, bad)

    def test_guarded_boundary_rejected(self):
        text = 'CX q0 q22\nPUSH_CONDITION b0\nX q3\nX q3\nCX q22 q4\nPOP_CONDITION\n'
        with self.assertRaisesRegex(ValueError, 'context'):
            transform(text, [dict(q=22,lo=2,hi=4,erase=[[0]],restore=[[0]])])

    def test_overlapping_plans_rejected(self):
        with self.assertRaisesRegex(ValueError, 'overlap'):
            transform('', [dict(lo=1,hi=4),dict(lo=3,hi=5)])

    def test_interval_selection_accounts_for_shared_peak_coverage(self):
        def item(lo, hi, coverage, cost):
            return dict(q=22,lo=lo,hi=hi,peak_coverage=coverage,extra_toffoli=cost,erase=[[0]],restore=[[0]])
        a,b,c = item(0,3,3,0),item(4,7,3,0),item(0,7,5,0)
        self.assertEqual(select_disjoint([c,b,a]), [a,b])


if __name__ == '__main__':
    unittest.main()
