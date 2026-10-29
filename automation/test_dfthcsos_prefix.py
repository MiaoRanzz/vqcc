"""Check prefix boundaries, arbitrary XOR targets and measurement cleanup."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "kickmix"), str(ROOT / "verifiers"), str(ROOT / "generators")]

import kickmix as km
import numpy as np
from dfthcsos_prefix import build_prefix_circuit, build_prefix_family, workspace_bits
from dfthcsos.scoreinfra.circuits import recover_words_from_circuits, register_layout


class PrefixTests(unittest.TestCase):
    def test_every_address_prefix_boundary_and_padding(self):
        rng = np.random.default_rng(20261029)
        for rows in (3, 4, 7, 8, 9, 31, 32, 33, 64, 65):
            words = rng.integers(0, 16, (rows, 5))
            for prefix in range(2, min((rows - 1).bit_length(), 5) + 1):
                with self.subTest(rows=rows, prefix=prefix):
                    family = build_prefix_family(words, 4, 2, prefix)
                    recovered, _, _ = recover_words_from_circuits(
                        family, num_vectors=rows, num_angles=5,
                        shots_per_address=8, seed=20261029)
                    np.testing.assert_array_equal(recovered, words)

    def test_arbitrary_nonzero_targets_and_constant_subtrees(self):
        rows, brot = 33, 4
        table = np.tile([3, 10], (rows, 1))
        table[16:32] = [6, 2]
        circuit = build_prefix_circuit(table, brot, 3)
        layout = register_layout((circuit,))
        addresses = np.tile(np.arange(rows), 8)
        target = np.arange(len(addresses) * 2).reshape(-1, 2) % 16
        sim = km.Simulator(batch_size=len(addresses), seed=20261029)
        sim.use_same_registers_as(circuit)

        def bits(values, width):
            return ((values[None, :] >> np.arange(width)[:, None]) & 1).astype(bool)

        sim.write_across_shots(layout.selection, bits(addresses, len(layout.selection)))
        for j, word in enumerate(layout.words):
            sim.write_across_shots(word, bits(target[:, j], brot))
        for expected in (target ^ table[addresses], target):
            sim.do(circuit)
            np.testing.assert_array_equal(sim.read_across_shots(layout.selection),
                                          bits(addresses, len(layout.selection)))
            for j, word in enumerate(layout.words):
                np.testing.assert_array_equal(sim.read_across_shots(word), bits(expected[:, j], brot))
            scratch = km.array([km.q(i) for i in range(circuit.num_qubits)
                                if i not in layout.public_qubits])
            self.assertFalse(sim.read_across_shots(scratch).any())
            self.assertTrue(all(sim.read_shot_phase(i) % 2 == 0 for i in range(len(addresses))))

    def test_cap_for_nine_twelve_bit_words(self):
        self.assertEqual(12 + 9 * 12 + workspace_bits(12, 5), 128)
        with self.assertRaises(ValueError):
            workspace_bits(12, 1)


if __name__ == "__main__":
    unittest.main()
