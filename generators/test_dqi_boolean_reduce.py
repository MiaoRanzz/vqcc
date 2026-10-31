"""Proof boundary and exact basis/phase parity tests for the DQI rewrite."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
from dqi_boolean_reduce import compile_scanner, read_proofs, rewrite, read_binary
import kickmix as km

HEADER=''.join(f'APPEND_TO_REGISTER q{i} r0\n' for i in range(3))+'REGISTER r0 "x"\n'


class BooleanReduceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.scanner=cls.root/'scanner';compile_scanner(cls.scanner)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def screen(self,body,cap=128,cache=0):
        source=self.root/'source.kmb';km.Circuit(HEADER+body).to_file(source,format='kmb')
        proof=self.root/'proof.tsv';summary=self.root/'summary.json'
        subprocess.run([str(self.scanner),str(source),str(proof),str(summary),str(cap),str(cache)],check=True,capture_output=True)
        return source,read_proofs(proof),json.loads(summary.read_text())

    def parity(self,body):
        source,proofs,_=self.screen(body)
        dest=self.root/'transformed.kmb';rewrite(source,dest,proofs)
        a,b=km.Circuit.from_file(source),km.Circuit.from_file(dest)
        # Every input and many independent measurement outcomes; algebra is the
        # proof, these checks catch operand-order, serialization and phase bugs.
        for seed in (1,7,101):
            sims=[km.Simulator(batch_size=256,seed=seed) for _ in range(2)]
            for sim,circuit in zip(sims,(a,b)):
                for q in range(3):sim.write_across_shots(km.q(q),np.array([(x>>q)&1 for x in range(256)],dtype=np.bool_))
                sim.do(circuit)
            for q in range(max(a.num_qubits,b.num_qubits)):
                np.testing.assert_array_equal(sims[0].read_across_shots(km.q(q)),sims[1].read_across_shots(km.q(q)))
            np.testing.assert_array_equal(sims[0].read_phase_flipped_across_shots(),sims[1].read_phase_flipped_across_shots())
        return proofs

    def test_hmr_phase_repair(self):
        proofs=self.parity('CCX q0 q1 q3\nZ q3\nCCX q1 q0 q3\n')
        self.assertEqual([p['kind'] for p in proofs],['hmr'])

    def test_complement_and_equal_controls(self):
        proofs=self.parity('CX q0 q3\nX q3\nCCX q0 q3 q4\nX q3\nCCX q0 q3 q4\n')
        self.assertEqual([p['kind'] for p in proofs],['zero','cx_a'])

    def test_original_bits_and_tags_retained(self):
        source,proofs,_=self.screen('BIT_STORE0 b12\nCCX q0 q1 q3\nCCX q0 q1 q3\n')
        dest=self.root/'transformed.kmb';rewrite(source,dest,proofs)
        a,b=read_binary(source),read_binary(dest)
        self.assertEqual(b['nb'],a['nb']+1)
        self.assertEqual(a['registers'],b['registers'])
        self.assertEqual(bytes(a['packets']['tags']),bytes(b['packets']['tags']))
        self.assertEqual(bytes(a['packets']['angles']),bytes(b['packets']['angles']))
        self.assertIn('b13',str(km.Circuit.from_file(dest)))

    def test_conditional_write_is_unknown(self):
        for middle in ['X q3 if b0\n','PUSH_CONDITION if b0\nX q3\nPOP_CONDITION\n','R q3 if b0\n']:
            _,proofs,_=self.screen('CCX q0 q1 q3\n'+middle+'CCX q0 q1 q3\n')
            self.assertEqual(proofs,[])

    def test_conditional_ccx_not_rewritten(self):
        _,proofs,_=self.screen('CCX q0 q1 q3\nCCX q0 q1 q3 if b0\n')
        self.assertEqual(proofs,[])

    def test_changed_control_not_same_product(self):
        _,proofs,_=self.screen('CCX q0 q1 q3\nCX q2 q0\nCCX q0 q1 q3\n')
        self.assertEqual(proofs,[])

    def test_linear_control_restore_recovers_product(self):
        proofs=self.parity('CCX q0 q1 q3\nCX q2 q0\nCX q2 q0\nCCX q0 q1 q3\n')
        self.assertEqual([p['kind'] for p in proofs],['hmr'])

    def test_overflow_is_unknown(self):
        _,proofs,summary=self.screen('CX q0 q3\nCX q1 q3\nCCX q3 q2 q4\nCX q0 q3\nCX q1 q3\nCCX q3 q2 q4\n',cap=1)
        self.assertGreater(summary['expression_overflows'],0)
        self.assertEqual(proofs,[])

    def test_compressed_xor_inverse_recovers_exact_value(self):
        body='CX q0 q3\nCX q1 q3\nCX q1 q3\nCCX q0 q3 q4\n'
        _,proofs,summary=self.screen(body,cap=1,cache=16)
        self.assertEqual([p['kind'] for p in proofs],['cx_a'])
        self.assertEqual(summary['xor_recoveries'],1)
        _,proofs,_=self.screen(body,cap=1,cache=0)
        self.assertEqual(proofs,[])

    def test_operand_mismatch_rejected(self):
        source,proofs,_=self.screen('CCX q0 q1 q3\nCCX q0 q1 q3\n')
        proofs[0]['a']=2
        with self.assertRaises(ValueError):rewrite(source,self.root/'invalid.kmb',proofs)


if __name__=='__main__':unittest.main()
