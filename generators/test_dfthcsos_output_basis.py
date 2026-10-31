"""Algebra checks for inverse product fanout, including noncommuting shears."""
import unittest
import numpy as np
from dfthcsos_output_basis import VARIANTS, shears, transform_tensor, inverse_mask

class OutputBasisTests(unittest.TestCase):
    def test_inverse_on_all_unit_vectors_and_random_tensors(self):
        rng=np.random.default_rng(62)
        for variant in VARIANTS:
            ops=shears(variant)
            original=rng.integers(0,2,(4,8,35),dtype=np.uint8)
            transformed=transform_tensor(original,ops)
            np.testing.assert_array_equal(transform_tensor(transformed,list(reversed(ops))),original)
            decoded=np.zeros_like(original)
            for i in range(35):
                mask=inverse_mask(1<<i,ops)
                for j in range(35):
                    if mask>>j&1:decoded[...,j]^=transformed[...,i]
            np.testing.assert_array_equal(decoded,original)
            for j in range(5):np.testing.assert_array_equal(transformed[...,7*j],original[...,7*j])

if __name__=='__main__':unittest.main()
