"""Exact small-domain checks for the reversible affine product emitter."""
import random
import unittest
from invsqrt_lookup_resynth import product_gates, step, linear_basis, ALL, INPUTS


class LookupSynthesisTests(unittest.TestCase):
    def test_affine_controls_all_rows(self):
        rng=random.Random(20261031)
        qs=list(range(14,22))
        for _ in range(300):
            a,b=rng.sample(range(1,256),2)
            # Target starts dirty: the replacement must be an XOR oracle.
            state=dict(INPUTS);state[30]=INPUTS[14]^INPUTS[18]
            before=state.copy();expected=state[30]
            av=bv=0
            for j,q in enumerate(qs):
                if a>>j&1:av^=state[q]
                if b>>j&1:bv^=state[q]
            expected^=av&bv
            for line in product_gates(a,b,qs,30):step(state,line)
            self.assertEqual(state[30],expected)
            self.assertTrue(all(state[q]==before[q] for q in qs))

    def test_basis_excludes_target_and_constant_dependencies(self):
        state={1:INPUTS[14],2:INPUTS[15],3:INPUTS[14]^INPUTS[15],
               4:ALL^INPUTS[14],5:INPUTS[16],6:None,7:0}
        self.assertEqual([q for q,_ in linear_basis(state,5)],[1,2])

    def test_reject_dependent_control_forms(self):
        with self.assertRaises(ValueError):product_gates(3,3,[14,15],30)
        with self.assertRaises(ValueError):product_gates(0,3,[14,15],30)

    def test_reject_phaseful_reset_and_unknown_wire(self):
        with self.assertRaises(ValueError):step({14:INPUTS[14]},'R q14')
        with self.assertRaises(ValueError):step({14:None,15:0},'CX q14 q15')
        with self.assertRaises(ValueError):step({14:0,15:0},'CX q14 q15 if b0')



class FiniteFactorTests(unittest.TestCase):
    def test_finds_distributive_whole_group_reduction(self):
        from invsqrt_lookup_resynth import solve_fixed_factors,apply_solution
        state={14:INPUTS[14],15:INPUTS[15],16:INPUTS[16],30:0}
        delta=(state[14]&state[15])^(state[14]&state[16])
        expected=dict(state);expected[30]=delta
        group=dict(start=0,end=2,target=30,original_count=2,delta=delta,
                   basis=list(state.items())[:3],control_tables=[(state[14],state[15]),(state[14],state[16])],
                   neutral=state,expected=expected)
        result=solve_fixed_factors((group,1,1000,{}))
        self.assertEqual(result['status'],'sat');self.assertEqual(result['products'],1)
        text=apply_solution(['CCX q14 q15 q30','CCX q14 q16 q30'],[group],[result])
        got=dict(state)
        for line in text.splitlines():step(got,line)
        self.assertEqual(got,expected)

    def test_exhausts_infeasible_original_factor_pool(self):
        from invsqrt_lookup_resynth import solve_fixed_factors
        basis=[(q,INPUTS[q]) for q in range(14,18)];a,b,c,d=[v for q,v in basis]
        group=dict(start=0,end=2,target=30,original_count=2,delta=(a&b)^(c&d),basis=basis,
                   control_tables=[(a,b),(c,d)])
        result=solve_fixed_factors((group,1,1000,{}))
        self.assertEqual(result['status'],'unsat');self.assertEqual(result['combinations_tested'],4)

    def test_zero_product_replacement_keeps_affine_operations_once(self):
        from invsqrt_lookup_resynth import solve_fixed_factors,apply_solution
        state={14:INPUTS[14],15:INPUTS[15],16:INPUTS[16],30:0}
        neutral=dict(state);neutral[16]^=neutral[14]
        group=dict(start=0,end=3,target=30,original_count=2,delta=0,
                   basis=[(14,state[14]),(15,state[15]),(16,neutral[16])],
                   control_tables=[(state[14],state[15]),(state[14],state[15])],
                   neutral=neutral,expected=neutral)
        row=solve_fixed_factors((group,1,1000,{}))
        self.assertEqual(row['products'],0)
        text=apply_solution(['CCX q14 q15 q30','CX q14 q16','CCX q14 q15 q30'],[group],[row])
        self.assertEqual(text,'CX q14 q16\n')

    def test_resume_does_not_repeat_proven_prefix(self):
        from invsqrt_lookup_resynth import solve_fixed_factors
        basis=[(q,INPUTS[q]) for q in range(14,18)];a,b,c,d=[v for q,v in basis]
        group=dict(start=0,end=2,target=30,original_count=2,delta=(a&b)^(c&d),basis=basis,
                   control_tables=[(a,b),(c,d)])
        row=solve_fixed_factors((group,1,1000,dict(resume_offset=3)))
        self.assertEqual(row['status'],'unsat');self.assertEqual(row['prior_combinations'],3)
        self.assertEqual(row['combinations_tested'],4)


if __name__=='__main__':unittest.main()
