"""Focused semantic checks for scratch reuse and conditional-reset barriers."""
import unittest
from invsqrt_reset_lifetimes import pack

HEADER = ''.join(f'APPEND_TO_REGISTER q{i} r0\n' for i in range(22)) + 'REGISTER r0 "x"\n'


class LifetimeTests(unittest.TestCase):
    def test_unconditional_reset_releases(self):
        text, report = pack(HEADER + 'CX q0 q22\nHMR q22 b0\nZ q0 if b0\nCX q1 q23\nHMR q23 b1\nZ q1 if b1\n')
        self.assertEqual(report['packed_qubits'], 23)
        self.assertIn('CX q1 q22', text)
        self.assertEqual(report['scratch_interval_peak'], 1)

    def test_conditional_reset_does_not_release(self):
        for reset in ['R q22 if b0\n', 'PUSH_CONDITION b0\nR q22\nPOP_CONDITION\n']:
            _, report = pack(HEADER + 'CX q0 q22\n' + reset + 'CX q1 q23\nHMR q23 b1\nHMR q22 b2\n')
            self.assertEqual(report['packed_qubits'], 24)
            self.assertEqual(report['conditional_resets_not_released'], 1)

    def test_dirty_end_remains_reserved(self):
        _, report = pack(HEADER + 'CX q0 q22\nCX q1 q23\nHMR q23 b1\n')
        self.assertEqual(report['packed_qubits'], 24)
        self.assertEqual(report['unterminated_intervals'], 1)

    def test_no_overlap_at_shared_operation(self):
        text, report = pack(HEADER + 'CX q0 q22\nCX q22 q23\nHMR q22 b0\nHMR q23 b1\n')
        self.assertEqual(report['packed_qubits'], 24)
        self.assertIn('CX q22 q23', text)

    def test_reject_quantum_condition(self):
        with self.assertRaises(ValueError):
            pack(HEADER + 'PUSH_CONDITION q0\nR q22\nPOP_CONDITION\n')


if __name__ == '__main__':
    unittest.main()
