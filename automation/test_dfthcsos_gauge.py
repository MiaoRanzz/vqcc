"""Algebraic invariants of the independent coefficient column gauge."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'generators'))
import numpy as np
from dfthcsos_gauge import column_gauge


class GaugeTests(unittest.TestCase):
    def test_gram_native_offset_and_monotonicity(self):
        rng=np.random.default_rng(20261030)
        for columns in (1,3,8,12):
            w=rng.normal(size=(2,7,columns));h=rng.normal(size=(2,columns))
            v,k,report=column_gauge(w,h,4)
            a=np.concatenate((w,h[:,None,:]),axis=1)
            b=np.concatenate((v,k[:,None,:]),axis=1)
            np.testing.assert_allclose(a@a.swapaxes(-1,-2),b@b.swapaxes(-1,-2),atol=1e-12)
            old=h-w.sum(axis=1);new=k-v.sum(axis=1)
            np.testing.assert_allclose(np.einsum('rbc,rc->rb',w,old),np.einsum('rbc,rc->rb',v,new),atol=1e-12)
            np.testing.assert_allclose(np.sum(old**2,axis=1),np.sum(new**2,axis=1),atol=1e-12)
            self.assertLessEqual(report['lambda_h2_after'],report['lambda_h2_before']+1e-12)
            np.testing.assert_array_equal(w,a[:,:-1,:])

    def test_reproducible_and_input_errors(self):
        w=np.arange(24).reshape(1,4,6)-12;h=np.arange(6).reshape(1,6)
        a,b,r=column_gauge(w,h,2);c,d,s=column_gauge(w,h,2)
        np.testing.assert_array_equal(a,c);np.testing.assert_array_equal(b,d);self.assertEqual(r,s)
        with self.assertRaises(ValueError):column_gauge(w,h,0)
        with self.assertRaises(ValueError):column_gauge(w,h[:,:3],1)


if __name__=='__main__':unittest.main()
