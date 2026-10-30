"""Proof-boundary tests; sample traces are intentionally not the proof method."""
import unittest
from invsqrt_clean_lifetimes import Algebra, ZERO, ONE, pack_proven
from test_invsqrt_reset_lifetimes import HEADER


class CleanLifetimeTests(unittest.TestCase):
    def test_uncompute_releases_before_reset(self):
        text, r = pack_proven(HEADER+'CCX q0 q1 q22\nZ q22\nCCX q1 q0 q22\nCX q2 q23\nHMR q23 b0\n')
        self.assertEqual(r['packed_qubits'], 23)
        self.assertIn('CX q2 q22', text)
        self.assertTrue(r['algebraic_zero_proofs'])

    def test_conditional_uncompute_cannot_release(self):
        for middle in ['CX q0 q22 if b0\n','PUSH_CONDITION if b0\nCX q0 q22\nPOP_CONDITION\n']:
            _, r = pack_proven(HEADER+'CX q0 q22\n'+middle+'CX q1 q23\nHMR q23 b1\nHMR q22 b2\n')
            self.assertEqual(r['packed_qubits'], 24)

    def test_conditional_reset_of_dirty_wire_cannot_release(self):
        _, r = pack_proven(HEADER+'CX q0 q22\nHMR q22 b0 if b1\nCX q1 q23\nHMR q23 b2\n')
        self.assertEqual(r['packed_qubits'],24)

    def test_complement_product_is_zero(self):
        text,r = pack_proven(HEADER+'CX q0 q22\nX q22\nCCX q0 q22 q23\nCX q1 q24\nHMR q24 b0\nHMR q22 b1\n')
        self.assertEqual(r['packed_qubits'],24)
        self.assertIn('CX q1 q23',text)

    def test_hmr_measurement_record_preserved(self):
        text,r=pack_proven(HEADER+'R q22\nHMR q22 b0\nX q23 if b0\nHMR q23 b1\n')
        self.assertEqual(r['omitted_zero_resets'],[23])
        self.assertIn('HMR q22 b0',text)
        self.assertIn('X q22 if b0',text)

    def test_no_alias_in_shared_operation(self):
        _,r=pack_proven(HEADER+'CX q0 q22\nCX q22 q23\nCX q0 q22\nHMR q23 b0\n')
        self.assertEqual(r['packed_qubits'],24)

    def test_overflow_is_unknown_not_zero(self):
        a=Algebra(term_limit=1);x,y=a.fresh(),a.fresh();s=a.xor(x,y)
        self.assertNotEqual(s,ZERO);self.assertEqual(a.overflows,1)
        self.assertEqual(a.xor(s,s),ZERO)

    def test_boolean_identities(self):
        a=Algebra();x,y=a.fresh(),a.fresh()
        self.assertEqual(a.mul(x,x),x)
        self.assertEqual(a.mul(x,a.xor(x,ONE)),ZERO)
        self.assertEqual(a.mul(x,y),a.mul(y,x))
        self.assertEqual(a.xor(a.mul(x,y),a.mul(y,x)),ZERO)

    def test_unknown_opcode_fails_closed(self):
        with self.assertRaises(ValueError):pack_proven(HEADER+'H q22\n')


if __name__=='__main__':unittest.main()
