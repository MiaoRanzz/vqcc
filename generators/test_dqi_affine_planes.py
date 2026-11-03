"""Exact six-basis/constant algebra and measurement-phase regression tests."""
import itertools
import unittest
import numpy as np
import kickmix as km
from dqi_interval_cache import linear_basis_gates, product_correction, rewrite_intervals
from test_dqi_interval_cache import IntervalCacheTests

BASES=list(itertools.permutations((1,2,3),2))


def basis_text(m,n,c,d,inverse=False):
    gates=linear_basis_gates(m,n)
    flips='X q0\n'*c+'X q1\n'*d
    linear=''.join(f'CX q{x} q{y}\n' for x,y in (reversed(gates) if inverse else gates))
    return flips+linear if inverse else linear+flips


class AffinePlaneTests(IntervalCacheTests):
    def test_all_affine_product_identities(self):
        for (m,n),c,d,a,b in itertools.product(BASES,range(2),range(2),range(2),range(2)):
            la,lb,k=product_correction(m,n,c,d)
            u=((m&1)*a)^(((m>>1)&1)*b)^c
            v=((n&1)*a)^(((n>>1)&1)*b)^d
            self.assertEqual(u*v ^ la*a ^ lb*b ^ k,a*b)
            values=[a,b]
            for x,y in linear_basis_gates(m,n):values[y]^=values[x]
            self.assertEqual(values,[u^c,v^d])
            for x,y in reversed(linear_basis_gates(m,n)):values[y]^=values[x]
            self.assertEqual(values,[a,b])
        with self.assertRaises(ValueError):linear_basis_gates(1,1)

    def test_every_pair_of_affine_bases_phase_and_dirty_targets(self):
        # All 24 x 24 affine presentations, all basis inputs, random HMR branches.
        for (m,n),(mm,nn),c,d,cc,dd in itertools.product(BASES,BASES,range(2),range(2),range(2),range(2)):
            body=('R q5\nCX q2 q3\nCX q2 q4\n'+basis_text(m,n,c,d)+
                  'CCX q0 q1 q3\n'+basis_text(m,n,c,d,True)+
                  'Z q3\nCZ q0 q4\n'+basis_text(mm,nn,cc,dd)+
                  'CCX q0 q1 q4\n'+basis_text(mm,nn,cc,dd,True)+'X q5\n')
            src,proofs=self.screen(body,mode=4)
            self.assertEqual(len(proofs),1)
            dst=self.root/'affine.kmb';rewrite_intervals(src,dst,proofs)
            circuits=[km.Circuit.from_file(f) for f in (src,dst)]
            self.assertEqual(circuits[1].operation_statistics().num_toffoli_like,
                             circuits[0].operation_statistics().num_toffoli_like-1)
            for seed in (1,7):
                sims=[km.Simulator(batch_size=256,seed=seed) for _ in circuits]
                for sim,circuit in zip(sims,circuits):
                    for q in range(3):sim.write_across_shots(km.q(q),np.array([(x>>q)&1 for x in range(256)],dtype=bool))
                    sim.do(circuit)
                for q in range(6):np.testing.assert_array_equal(sims[0].read_across_shots(km.q(q)),sims[1].read_across_shots(km.q(q)))
                np.testing.assert_array_equal(sims[0].read_phase_flipped_across_shots(),sims[1].read_phase_flipped_across_shots())

    def test_shear_pair_requires_plane_mode(self):
        body='R q5\nCCX q0 q1 q3\nCX q0 q1\nCCX q0 q1 q4\nX q5\n'
        self.assertEqual(self.screen(body,mode=3)[1],[])
        self.assertEqual(len(self.screen(body,mode=4)[1]),1)

    def test_unrelated_control_plane_does_not_match(self):
        body='R q5\nCCX q0 q1 q3\nCX q2 q1\nCCX q0 q1 q4\nX q5\n'
        self.assertEqual(self.screen(body,mode=4)[1],[])


if __name__=='__main__':unittest.main()
