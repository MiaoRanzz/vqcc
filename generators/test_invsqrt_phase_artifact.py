import unittest
from fractions import Fraction
from invsqrt_phase_artifact import apply_fit,decimal_angle


class PhaseArtifactTests(unittest.TestCase):
    def test_dyadic_roundtrip(self):
        for x in [Fraction(-13,1<<63),Fraction(7,16),Fraction(1,1<<80)]:
            self.assertEqual(Fraction(decimal_angle(x)),x)

    def test_only_pinned_angle_changes(self):
        lines=['APPEND_TO_REGISTER q0 r0','REGISTER r0 "x"','CX q0 q1','Z_POW q1 0.125','HMR q1 b0','Z q0 if b0']
        rows=[dict(index=3,instruction=lines[3])]
        text,_=apply_fit(lines,rows,[1])
        result=text.splitlines();self.assertEqual(Fraction(result[3].split()[2]),Fraction(1,8)+Fraction(1,1<<63))
        self.assertEqual(result[:3]+result[4:],lines[:3]+lines[4:])

    def test_drop_and_insert_before_first_value_operation(self):
        lines=['REGISTER r0 "x"','X q22','Z_POW q22 0.125']
        text,_=apply_fit(lines,[dict(index=2,instruction=lines[2])],[-(1<<60),5],[0],0)
        self.assertEqual(text.splitlines()[1],'Z_POW q0 '+decimal_angle(Fraction(5,1<<63)))
        self.assertNotIn('Z_POW q22',text)

    def test_pinned_internal_feature_and_phase_units(self):
        lines=['X q1','CX q0 q1','Z_POW q1 0.125']
        feature=dict(before_index=1,before_instruction=lines[1],qubit=1)
        text,_=apply_fit(lines,[dict(index=2,instruction=lines[2])],[0,3],extra_feature=feature)
        self.assertEqual(text.splitlines()[1],'Z_POW q1 '+decimal_angle(Fraction(3,1<<63)))
        with self.assertRaises(ValueError):apply_fit(lines,[dict(index=2,instruction=lines[2])],[0.5])
        feature['before_index']=-1
        with self.assertRaises(ValueError):apply_fit(lines,[dict(index=2,instruction=lines[2])],[0,3],extra_feature=feature)

    def test_changed_source_and_condition_rejected(self):
        with self.assertRaises(ValueError):apply_fit(['Z_POW q0 0.125'],[dict(index=0,instruction='Z_POW q0 0.25')],[0])
        with self.assertRaises(ValueError):apply_fit(['Z_POW q0 0.125 if b0'],[dict(index=0,instruction='Z_POW q0 0.125 if b0')],[0])


if __name__=='__main__':unittest.main()
