"""Table routing and normalized-boundary checks before official full verification."""
import dataclasses
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'kickmix'),str(ROOT/'verifiers'),str(ROOT/'generators')]
import numpy as np
from invsqrt.nr_reference_circuit import Precision, fixed_point_model, build_nr_circuit
from invsqrt_coefficients import TablePrecision, initial_guess, segment_endpoints


class TableTests(unittest.TestCase):
    def test_default_table_exact_reference(self):
        reference=Precision(delta_bits=12,coef_bits=16)
        custom=TablePrecision(coefficient_table=reference.coefficient_table(),**dataclasses.asdict(reference))
        xs=np.array([1,2,3,4,7,8,15,16,1048575,1048576,1572863,1572864,2097151,2097152,3133452])
        np.testing.assert_array_equal(fixed_point_model(10,reference,xs),fixed_point_model(10,custom,xs))
        self.assertEqual(str(build_nr_circuit(10,prec=reference)),str(build_nr_circuit(10,prec=custom)))
        self.assertEqual(len(dataclasses.astuple(custom)),5)

    def test_table_is_validated_and_copied(self):
        source=Precision().coefficient_table()
        custom=TablePrecision(coefficient_table=source)
        source[0][0]=0
        output=custom.coefficient_table()
        output[0][0]=0
        self.assertNotEqual(custom.coefficient_table()[0][0],0)
        for invalid in ([[1]*4]*3, [[1]*4]*3+[[2**17]*4], [[1]*4]*3+[[1.0]*4]):
            with self.assertRaises(ValueError):
                TablePrecision(coefficient_table=invalid)

    def test_all_horner_cells_have_constant_endpoints(self):
        for delta in (11,12,13,14):
            prec=Precision(delta_bits=delta,coef_bits=16)
            for case in range(4):
                xs=segment_endpoints(delta,case)
                values=initial_guess(prec,case,xs)
                np.testing.assert_array_equal(values[::2],values[1::2])
                # Independent direct evaluation of each scalar polynomial,
                # truncating each selected shift separately (not the total product).
                for index in (0,1,len(xs)//2,len(xs)-2,len(xs)-1):
                    x=int(xs[index]); m=x/2**20
                    base=(1,1.5,2,3)[case]
                    bits=int((m-base)*2**delta)
                    c0,c1,c2,c3=prec.coefficient_table()[case]
                    value=c3
                    for acc in (c2,c1,c0):
                        value=acc-sum(value>>k for k in range(1,delta+1) if bits & (1<<(delta-k)))
                    self.assertEqual(int(values[index]),value)


if __name__=='__main__':
    unittest.main()
