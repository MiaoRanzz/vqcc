"""Current-state proof invalidation and exhaustive small-circuit equivalence."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
import kickmix as km
from dqi_boolean_reduce import compile_scanner, read_proofs, rewrite

HEADER = ''.join(f'APPEND_TO_REGISTER q{i} r0\n' for i in range(3))+'REGISTER r0 "x"\n'


class LiveCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.root = Path(cls.tmp.name)
        cls.scanner = cls.root/'scanner'; compile_scanner(cls.scanner)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def screen(self, body):
        source = self.root/'source.kmb'
        km.Circuit(HEADER+body).to_file(source, format='kmb')
        proof, summary = self.root/'proof.tsv', self.root/'summary.json'
        subprocess.run([str(self.scanner), str(source), str(proof), str(summary), '512', '0', '0', '0', '1'], check=True, capture_output=True)
        return source, read_proofs(proof)

    def test_reuse_preserves_every_basis_state_and_phase(self):
        source, proofs = self.screen('CCX q0 q1 q3\nCX q2 q4\nCCX q1 q0 q4\nZ q4\nCCX q0 q1 q4\n')
        self.assertEqual([p['cache'] for p in proofs], [3,3])
        dest = self.root/'result.kmb'; rewrite(source, dest, proofs)
        circuits = [km.Circuit.from_file(f) for f in (source,dest)]
        sims = [km.Simulator(batch_size=8, seed=7) for _ in circuits]
        for sim, circuit in zip(sims,circuits):
            for q in range(3):
                sim.write_across_shots(km.q(q), np.array([(x>>q)&1 for x in range(8)], dtype=bool))
            sim.do(circuit)
        for q in range(5):
            np.testing.assert_array_equal(sims[0].read_across_shots(km.q(q)), sims[1].read_across_shots(km.q(q)))
        np.testing.assert_array_equal(sims[0].read_phase_flipped_across_shots(), sims[1].read_phase_flipped_across_shots())
        self.assertEqual(circuits[0].num_bits, circuits[1].num_bits)

    def test_reset_measurement_and_conditional_write_invalidate(self):
        for middle in ['R q3\n', 'HMR q3 b0\n', 'X q3 if b0\n', 'PUSH_CONDITION if b0\nX q3\nPOP_CONDITION\n', 'CX q2 q3\n']:
            with self.subTest(middle=middle):
                _, proofs = self.screen('CCX q0 q1 q3\n'+middle+'CCX q0 q1 q4\n')
                self.assertEqual(proofs, [])

    def test_restored_value_and_swapped_wire_are_reindexed(self):
        _, proofs = self.screen('CCX q0 q1 q3\nCX q2 q3\nCX q2 q3\nSWAP q3 q4\nCCX q0 q1 q5\n')
        self.assertEqual([p['cache'] for p in proofs], [4])

    def test_changed_controls_or_conditional_operation_do_not_qualify(self):
        for tail in ['CX q2 q0\nCCX q0 q1 q4\n', 'CCX q0 q1 q4 if b0\n', 'PUSH_CONDITION if b0\nCCX q0 q1 q4\nPOP_CONDITION\n']:
            _, proofs = self.screen('CCX q0 q1 q3\n'+tail)
            self.assertEqual(proofs, [])

    def test_cache_alias_or_out_of_range_rejected(self):
        source, proofs = self.screen('CCX q0 q1 q3\nCCX q0 q1 q4\n')
        for cached in [0,1,4,5,-1]:
            with self.subTest(cached=cached), self.assertRaises(ValueError):
                rewrite(source, self.root/'invalid.kmb', [{**proofs[0], 'cache':cached}])


if __name__ == '__main__':
    unittest.main()
