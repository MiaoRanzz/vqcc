"""Boundary tests for independently derived tree encoding (not scientific gates)."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'verifiers'), str(ROOT/'generators')]
import numpy as np
from dfthcsos_quantization import encode_vectors
from dfthcsos.scoreinfra.dfthc_math import reconstruct_u_vectors


class EncodingTests(unittest.TestCase):
    def test_signed_axes_and_wrap(self):
        edges = np.array([[0,1], [0,2], [2,3]])
        vectors = np.concatenate([np.eye(4), -np.eye(4)])
        for brot in (2, 11, 12):
            words = encode_vectors(vectors, edges, brot)
            actual = reconstruct_u_vectors(words / (1 << (brot - 1)), edges)
            np.testing.assert_allclose(actual, vectors, atol=1e-14)
            self.assertTrue(((words >= 0) & (words < 1 << brot)).all())

    def test_general_tree_and_rounding_bound(self):
        rng = np.random.default_rng(20261030)
        for edges in (np.array([[0,1],[1,2],[2,3]]), np.array([[0,1],[0,2],[2,3]])):
            vectors = rng.normal(size=(100,4))
            vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
            for brot in (11,12,24):
                words = encode_vectors(vectors, edges, brot)
                actual = reconstruct_u_vectors(words / (1 << (brot - 1)), edges)
                self.assertLess(np.max(np.linalg.norm(actual-vectors, axis=1)), 3*np.pi/(1 << brot))

    def test_invalid_tree_and_zero_vectors(self):
        for edges in (np.array([[1,2],[0,1]]), np.array([[0,1],[0,1]])):
            with self.assertRaises(ValueError):
                encode_vectors(np.ones((2,3)), edges, 12)
        with self.assertRaises(ValueError):
            encode_vectors(np.zeros((1,2)), np.array([[0,1]]), 12)


if __name__ == '__main__':
    unittest.main()
