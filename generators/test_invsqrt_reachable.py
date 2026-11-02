import unittest
from fractions import Fraction
import numpy as np
from invsqrt_reachable import analyze_prefix, unpack, propagate


class ReachableTests(unittest.TestCase):
    def test_exact_values_match_scalar_all_inputs(self):
        lines=['CX q0 q3','CCX q1 q2 q3','CSWAP q2 q0 q3','X q1','SWAP q0 q2','HMR q3 b0']
        r=analyze_prefix(lines+['Z q0'],width=3,max_x=7,snapshots=[len(lines)])
        for x in range(1,8):
            s={q:(x>>q)&1 for q in range(3)};s[3]=0
            for line in lines:
                f=line.split();qs=[int(q[1:]) for q in f[1:] if q.startswith('q')]
                propagate(f[0],qs,s,1)
            for q,v in s.items():self.assertEqual((r['snapshots'][len(lines)][q]>>(x-1))&1,v)
        self.assertIn(3,r['zero_after'][5])

    def test_stops_before_random_value_control(self):
        for line in ['CX q0 q3 if b0','PUSH_CONDITION if b0','HMR q3 b0 if b1']:
            r=analyze_prefix(['CX q0 q3',line,'R q3'],width=2,max_x=3)
            self.assertEqual(r['prefix_end'],1)
            self.assertNotIn(1,r['zero_after'])

    def test_conditional_diagonal_preserves_value(self):
        r=analyze_prefix(['CX q0 q2','Z q2 if b0','CX q0 q2'],width=2,max_x=3)
        self.assertEqual(r['prefix_end'],3)
        self.assertIn(2,r['zero_after'][2])

    def test_distributive_zero_is_exact_not_sampled(self):
        lines=['CX q0 q3','CX q1 q3','CCX q3 q2 q4','CCX q0 q2 q4','CCX q1 q2 q4']
        r=analyze_prefix(lines,width=3,max_x=7)
        self.assertIn(4,r['zero_after'][4])

    def test_phase_features_and_modular_units(self):
        r=analyze_prefix(['Z_POW q0 0.125','Z q1','Z_POW q0 0.5 if b0'],width=2,max_x=3,phases=True)
        np.testing.assert_array_equal(r['features'],[[1,0,1]])
        self.assertEqual(r['phase'].tolist(),[1<<60,1<<63,(1<<63)+(1<<60)])
        self.assertEqual(r['rotation_rows'][0]['index'],0)

    def test_exact_zero_certificate_enables_distributive_release(self):
        from invsqrt_clean_lifetimes import pack_proven
        from test_invsqrt_reset_lifetimes import HEADER
        text=HEADER+'CX q0 q22\nCX q1 q22\nCCX q22 q2 q23\nCCX q0 q2 q23\nCCX q1 q2 q23\nCX q3 q24\nHMR q24 b0\nHMR q22 b1\n'
        proof=analyze_prefix(text.splitlines())
        _,old=pack_proven(text)
        _,new=pack_proven(text,certified_zero_after=proof['zero_after'])
        self.assertEqual(old['packed_qubits'],25)
        self.assertEqual(new['packed_qubits'],24)
        with self.assertRaises(ValueError):pack_proven(HEADER+'X q22\n',certified_zero_after={len(HEADER.splitlines()):[23]})

    def test_unknown_gate_rejected(self):
        with self.assertRaises(ValueError):analyze_prefix(['H q0'],width=2,max_x=3)


if __name__=='__main__':unittest.main()
