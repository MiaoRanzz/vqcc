"""Gate/phase parity and conservative rejection boundaries for borrowed ANDs."""
import json,subprocess,tempfile,unittest
from pathlib import Path
import numpy as np
from dqi_boolean_reduce import compile_scanner,read_proofs,read_binary
from dqi_borrowed_uncompute import rewrite
import kickmix as km

HEADER='REGISTER r0 "inputs"\n'+''.join(f'APPEND_TO_REGISTER q{i} r0\n' for i in range(4))
BLOCK='CCX q0 q1 q3\nCCX q3 q2 q4\nCCX q0 q1 q3\nCCX q3 q2 q4\n'

class BorrowedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.scanner=cls.root/'scanner';compile_scanner(cls.scanner)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def screen(self,body,header=HEADER):
        source=self.root/'source.kmb';km.Circuit(header+body).to_file(source,format='kmb')
        proof=self.root/'proof.tsv';summary=self.root/'summary.json'
        subprocess.run([str(self.scanner),str(source),str(proof),str(summary),'512','0','0','1'],check=True,capture_output=True)
        return source,read_proofs(proof),json.loads(summary.read_text())
    def test_all_values_dirty_borrow_and_phase(self):
        source,proofs,summary=self.screen(BLOCK+'Z q4\nBIT_STORE0 b12\n'+BLOCK)
        self.assertEqual(len(proofs),1);self.assertEqual(summary['borrowed_uncomputes'],1)
        target=self.root/'target.kmb';change=rewrite(source,target,proofs)
        self.assertEqual(change['expected_mean_toffoli_reduction'],3.5)
        before,after=read_binary(source),read_binary(target)
        self.assertEqual(before['registers'],after['registers']);self.assertEqual(after['nb'],before['nb']+1)
        for name in ['tags','angles']:np.testing.assert_array_equal(before['packets'][name],after['packets'][name])
        circuits=[km.Circuit.from_file(f) for f in [source,target]]
        for seed in [3,11,71]:
            sims=[km.Simulator(batch_size=256,seed=seed) for _ in range(2)]
            for sim,circuit in zip(sims,circuits):
                for q in range(4):sim.write_across_shots(km.q(q),np.array([(x>>q)&1 for x in range(256)],dtype=bool))
                sim.do(circuit)
            for q in range(5):np.testing.assert_array_equal(sims[0].read_across_shots(km.q(q)),sims[1].read_across_shots(km.q(q)))
            np.testing.assert_array_equal(sims[0].read_phase_flipped_across_shots(),sims[1].read_phase_flipped_across_shots())
    def test_unknown_or_nonzero_target_not_replaced(self):
        for body,header in [(BLOCK,HEADER),(BLOCK+BLOCK,HEADER+'APPEND_TO_REGISTER q4 r0\n'),('X q4\n'+BLOCK+BLOCK,HEADER)]:
            self.assertEqual(self.screen(body,header)[1],[])
    def test_control_change_and_guards_not_replaced(self):
        for tail in ['X q0\n'+BLOCK,'PUSH_CONDITION if b0\n'+BLOCK+'POP_CONDITION\n',BLOCK.replace('CCX q3 q2 q4\n','CCX q3 q2 q4 if b0\n')]:
            self.assertEqual(self.screen(BLOCK+tail)[1],[])
    def test_noncontiguous_and_mismatched_proof_rejected(self):
        self.assertEqual(self.screen(BLOCK+BLOCK.replace('CCX q0 q1 q3\n','CCX q0 q1 q3\nZ q3\n'))[1],[])
        source,proofs,_=self.screen(BLOCK+BLOCK);proofs[0]['target']=3
        with self.assertRaises(ValueError):rewrite(source,self.root/'bad.kmb',proofs)

if __name__=='__main__':unittest.main()
