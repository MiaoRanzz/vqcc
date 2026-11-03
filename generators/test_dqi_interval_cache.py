"""All small basis inputs, measurement phase repair and interval rejection."""
from pathlib import Path
import subprocess,tempfile,unittest
import numpy as np
import kickmix as km
from dqi_boolean_reduce import compile_scanner,read_proofs
from dqi_interval_cache import rewrite_intervals
HEADER=''.join(f'APPEND_TO_REGISTER q{i} r0\n' for i in range(3))+'REGISTER r0 "x"\n'


class IntervalCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.scanner=cls.root/'scanner';compile_scanner(cls.scanner)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def screen(self,body,cap=512,cache=0,mode=2):
        src=self.root/'source.kmb';km.Circuit(HEADER+body).to_file(src,format='kmb')
        proofs=self.root/'proofs.tsv';summary=self.root/'summary.json'
        subprocess.run([str(self.scanner),str(src),str(proofs),str(summary),str(cap),str(cache),'0','0',str(mode)],check=True,capture_output=True)
        return src,read_proofs(proofs)
    def test_dirty_targets_measurement_phase_and_spare_restoration(self):
        body='R q5\nCX q2 q3\nCCX q0 q1 q3\nCX q2 q4\nZ q3\nCCX q0 q1 q4\nX q5\n'
        src,proofs=self.screen(body);self.assertEqual(len(proofs),1)
        dst=self.root/'result.kmb';rewrite_intervals(src,dst,proofs)
        circuits=[km.Circuit.from_file(f) for f in (src,dst)]
        self.assertEqual(circuits[1].operation_statistics().num_toffoli_like,circuits[0].operation_statistics().num_toffoli_like-1)
        for seed in (1,7,101):
            sims=[km.Simulator(batch_size=256,seed=seed) for _ in circuits]
            for sim,circuit in zip(sims,circuits):
                for q in range(3):sim.write_across_shots(km.q(q),np.array([(x>>q)&1 for x in range(256)],dtype=bool))
                sim.do(circuit)
            for q in range(6):np.testing.assert_array_equal(sims[0].read_across_shots(km.q(q)),sims[1].read_across_shots(km.q(q)))
            np.testing.assert_array_equal(sims[0].read_phase_flipped_across_shots(),sims[1].read_phase_flipped_across_shots())
    def test_complemented_pairs_all_factor_choices_and_measurements(self):
        for first_bits in range(4):
            for last_bits in range(4):
                flip=lambda mask: ''.join(f'X q{q}\n' for q in (0,1) if mask>>q&1)
                body='R q5\nCX q2 q3\nCX q2 q4\n'+flip(first_bits)+'CCX q0 q1 q3\n'+flip(first_bits^last_bits)+'CCX q0 q1 q4\n'+flip(last_bits)+'X q5\n'
                src,proofs=self.screen(body,mode=3)
                self.assertEqual(len(proofs),1,(first_bits,last_bits))
                dst=self.root/'complement.kmb';rewrite_intervals(src,dst,proofs)
                circuits=[km.Circuit.from_file(f) for f in (src,dst)]
                for seed in (1,7):
                    sims=[km.Simulator(batch_size=256,seed=seed) for _ in circuits]
                    for sim,circuit in zip(sims,circuits):
                        for q in range(3):sim.write_across_shots(km.q(q),np.array([(x>>q)&1 for x in range(256)],dtype=bool))
                        sim.do(circuit)
                    for q in range(6):np.testing.assert_array_equal(sims[0].read_across_shots(km.q(q)),sims[1].read_across_shots(km.q(q)))
                    np.testing.assert_array_equal(sims[0].read_phase_flipped_across_shots(),sims[1].read_phase_flipped_across_shots())

    def test_compressed_xor_recovery_enables_exact_pair(self):
        body='R q5\nCCX q0 q2 q3\nCX q0 q4\nCX q1 q4\nCX q1 q4\nCCX q4 q2 q6\nX q5\n'
        _,without=self.screen(body,cap=1,cache=0)
        _,with_cache=self.screen(body,cap=1,cache=16)
        self.assertEqual(without,[])
        self.assertEqual(len(with_cache),1)

    def test_first_operation_can_start_an_interval(self):
        _,proofs=self.screen('CCX q0 q1 q3\nCCX q0 q1 q4\nX q5\n')
        self.assertEqual(len(proofs),1)
        self.assertEqual(proofs[0]['op'],0)

    def test_spare_is_not_clean(self):
        _,proofs=self.screen('X q5\nCX q2 q4\nCCX q0 q1 q3\nCCX q0 q1 q4\n')
        self.assertEqual(proofs,[])
    def test_every_original_spare_access_blocks_interval(self):
        for middle in ['Z q5\n','R q5\n','HMR q5 b0\n','CX q5 q2\n']:
            _,proofs=self.screen('R q5\nCX q2 q4\nCCX q0 q1 q3\n'+middle+'CCX q0 q1 q4\n')
            self.assertEqual(proofs,[])
    def test_changed_product_is_not_equal(self):
        _,proofs=self.screen('R q5\nCCX q0 q1 q3\nCX q2 q0\nCCX q0 q1 q4\n')
        self.assertEqual(proofs,[])
    def test_changed_then_restored_controls_qualify(self):
        _,proofs=self.screen('R q5\nCCX q0 q1 q3\nCX q2 q0\nCX q2 q0\nCCX q0 q1 q4\n')
        self.assertEqual(len(proofs),1)
    def test_proof_spare_access_and_overlap_rechecked(self):
        src,proofs=self.screen('R q5\nCCX q0 q1 q3\nCX q2 q4\nCCX q0 q1 q4\n')
        self.assertEqual(len(proofs),1)
        with self.assertRaises(ValueError):rewrite_intervals(src,self.root/'bad.kmb',proofs+proofs)
        with self.assertRaises(ValueError):rewrite_intervals(src,self.root/'bad.kmb',[{**proofs[0],'spare':2}])


if __name__=='__main__':unittest.main()
