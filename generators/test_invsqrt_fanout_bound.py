import unittest
from invsqrt_fanout_bound import analyze


class FanoutBoundTests(unittest.TestCase):
    def test_sequential_fanout_matches_all_inputs(self):
        lines = ['CCX q0 q1 q2', 'CSWAP q3 q2 q4', 'CX q4 q1', 'CCX q1 q2 q5', 'X q0', 'SWAP q0 q3']
        r = analyze(lines)
        for x in range(64):
            bits = [(x >> i) & 1 for i in range(6)]
            bits[2] ^= bits[0]&bits[1]
            if bits[3]: bits[2], bits[4] = bits[4], bits[2]
            bits[1] ^= bits[4]; bits[5] ^= bits[1]&bits[2]
            bits[0] ^= 1; bits[0], bits[3] = bits[3], bits[0]
            for q, poly in r['outgoing_anf'].items():
                self.assertEqual(sum((x&m)==m for m in poly)%2, bits[int(q)])

    def test_bound_detects_independent_products_and_cancellation(self):
        r = analyze(['CCX q0 q1 q2', 'CCX q3 q4 q5', 'CSWAP q6 q7 q8'])
        self.assertEqual(r['nonlinear_span_bound'], 3)
        r = analyze(['CCX q0 q1 q2', 'CCX q0 q1 q2'])
        self.assertEqual(r['nonlinear_span_bound'], 0)

    def test_tight_span_cannot_hide_two_product_accumulator(self):
        r = analyze(['CCX q0 q1 q4', 'CCX q2 q3 q4', 'CSWAP q5 q4 q6', 'CSWAP q7 q4 q8', 'CCX q9 q10 q11'])
        self.assertEqual(r['nonlinear_span_bound'], 4)
        self.assertEqual(r['refined_lower_bound'], 5)
        self.assertEqual(r['maximum_saving'], 0)

    def test_product_chain_is_not_excluded(self):
        r = analyze(['CCX q0 q1 q2', 'CCX q2 q3 q4', 'CCX q5 q6 q7', 'CCX q5 q6 q7'])
        self.assertEqual(r['tight_span_obstruction']['status'], 'not_excluded')

    def test_certified_zero_is_used_in_polynomial_model(self):
        r = analyze(['CCX q0 q1 q2'], zero_inputs=[0])
        self.assertEqual(r['nonlinear_span_bound'], 0)
        self.assertEqual(r['outgoing_anf']['0'], [])

    def test_rejects_measurement_phase_and_conditions(self):
        for line in ['HMR q0 b1', 'Z q0', 'CX q0 q1 if b0', 'CCX q0 q0 q2']:
            with self.assertRaises(ValueError): analyze([line])


if __name__ == '__main__': unittest.main()
