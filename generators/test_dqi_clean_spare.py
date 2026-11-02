import tempfile,unittest
from pathlib import Path
import numpy as np
from dqi_clean_spare import rewrite
from dqi_boolean_reduce import read_binary
import kickmix as km


class CleanSpareTests(unittest.TestCase):
    def test_all_dirty_inputs_and_phase(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/'a.kmb',Path(td)/'b.kmb'
            km.Circuit('CCX q0 q1 q3\nCCX q3 q2 q4\nCCX q0 q1 q3\nCCX q3 q2 q4\n').to_file(a,format='kmb')
            change=rewrite(a,b,[dict(start=0,end=4,target=4,controls=[0,1,2])])
            self.assertEqual(change['new_qubits'],6)
            self.assertEqual(read_binary(b)['nb'],1)
            original,changed=km.Circuit.from_file(a),km.Circuit.from_file(b)
            for seed in [3,11]:
                sims=[km.Simulator(batch_size=256,seed=seed) for _ in range(2)]
                for sim,circuit in zip(sims,[original,changed]):
                    for q in range(5):sim.write_across_shots(km.q(q),np.array([(x>>q)&1 for x in range(256)],dtype=bool))
                    sim.do(circuit)
                for q in range(5):np.testing.assert_array_equal(sims[0].read_across_shots(km.q(q)),sims[1].read_across_shots(km.q(q)))
                self.assertFalse(sims[1].read_across_shots(km.q(5)).any())
                np.testing.assert_array_equal(sims[0].read_phase_flipped_across_shots(),sims[1].read_phase_flipped_across_shots())
            # Exact HMR phase cancellation for each possible outcome, not seed evidence.
            for x in range(32):
                a0,b0,c0,dirty,target=[(x>>i)&1 for i in range(5)]
                for measurement in [0,1]:
                    phase=(a0*b0*measurement)^(measurement*a0*b0)
                    self.assertEqual(phase,0)
                    old=target^(dirty*c0)^((dirty^(a0*b0))*c0)
                    self.assertEqual(old,target^(a0*b0*c0))

    def test_mismatched_census_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/'a.kmb',Path(td)/'b.kmb'
            km.Circuit('CCX q0 q1 q3\nCCX q3 q2 q4\nCCX q0 q1 q3\nCCX q3 q2 q4\n').to_file(a,format='kmb')
            with self.assertRaises(ValueError):rewrite(a,b,[dict(start=0,end=4,target=3,controls=[0,1,2])])

if __name__=='__main__':unittest.main()
