# SPDX-License-Identifier: Apache-2.0
"""Independent exhaustive phase and arbitrary-old-target checks for the census."""
import unittest
from invsqrt_deferred_products import census, factor_one, affine_product

FIXTURE = ['CX q4 q2','CCX q0 q2 q5','CX q4 q2','CX q0 q2','CX q3 q2',
           'CCX q1 q2 q5','CX q3 q2','CX q1 q2','HMR q0 b0',
           'CZ q3 q4 if b0','CX q4 q3','CCX q1 q3 q0','CX q4 q0','CX q4 q3']


def replacement(lines, row):
    first, second, third = row['positions']
    out=[]; acc=row['accumulator']; target=row['reset_target']
    for i,line in enumerate(lines):
        if i==first: continue
        if i==second: out.extend(row['replacement_product'])
        elif i==third:
            out += [f'CX q{target} q{acc}',line,f'CX q{target} q{acc}']
        else: out.append(line)
    return out


def run(lines, value, measurement):
    # All six incoming wires, including the accumulator and reset target, vary.
    state=[(value>>i)&1 for i in range(6)]; phase=0
    for line in lines:
        f=line.split();op=f[0];qs=[int(t[1:]) for t in f if t.startswith('q')]
        if 'if' in f and not measurement: continue
        if op=='CX': state[qs[1]] ^= state[qs[0]]
        elif op=='CCX': state[qs[2]] ^= state[qs[0]] & state[qs[1]]
        elif op=='X': state[qs[0]] ^= 1
        elif op=='CZ': phase ^= state[qs[0]] & state[qs[1]]
        elif op=='HMR': phase ^= measurement & state[qs[0]];state[qs[0]]=0
        else: raise ValueError(op)
    return state,phase


class DeferredTests(unittest.TestCase):
    def test_known_identity_all_values_and_measurement_branches(self):
        result=census(FIXTURE,6);row=result['windows'][0]
        self.assertEqual(row['saved_ccx'],1)
        changed=replacement(FIXTURE,row)
        self.assertEqual(sum(x.startswith('CCX ') for x in changed),2)
        for x in range(64):
            for m in range(2): self.assertEqual(run(FIXTURE,x,m),run(changed,x,m))

    def test_arbitrary_unreset_target(self):
        lines=[l for l in FIXTURE if not l.startswith(('HMR ','CZ '))]
        self.assertEqual(census(lines,6)['decisions'],{'no_target_reset':1})
        row=census(lines,6,require_reset=False)['windows'][0]
        changed=replacement(lines,row)
        for x in range(64): self.assertEqual(run(lines,x,0),run(changed,x,0))

    def test_accumulator_phase_read_rejected(self):
        lines=FIXTURE[:9]+['CZ q5 q3 if b0']+FIXTURE[9:]
        self.assertEqual(census(lines,6)['windows'][0]['decision'],'accumulator_read_or_reset')

    def test_accumulator_value_read_rejected(self):
        lines=FIXTURE[:9]+['CX q5 q3']+FIXTURE[9:]
        self.assertEqual(census(lines,6)['windows'][0]['decision'],'accumulator_read_or_reset')

    def test_conditional_reset_and_flow_rejected(self):
        for op in ('HMR q0 b0 if b1','PUSH_CONDITION b1'):
            lines=FIXTURE.copy();lines[8]=op
            self.assertIn(census(lines,6)['windows'][0]['decision'],('conditional_value_operation','control_flow_boundary'))

    def test_factor_with_constants_and_rank_four(self):
        p=affine_product(1^4^8,2^4^8,3)
        f=factor_one(p,3)
        self.assertEqual(f['rank'],2)
        self.assertEqual(factor_one({3,12},4)['rank'],4)

if __name__=='__main__':unittest.main()
