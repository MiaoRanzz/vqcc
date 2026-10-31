"""Joint-output equality and the conditions needed for no-ancilla synthesis."""
import unittest
from invsqrt_joint_outputs import extract_windows,solve_window,replacement,select_nonoverlapping,evaluate,normalized_representation
from invsqrt_lookup_resynth import INPUTS,ALL


def toy_lines(body):
    return ['']*240+['R q22','R q23']+body+['HMR q24 b12600']


class JointOutputsTests(unittest.TestCase):
    def test_shared_product_saves_one_with_dirty_target_conjugation(self):
        lines=toy_lines(['CX q18 q22','CX q19 q23','CCX q14 q15 q22','CCX q14 q15 q23','CCX q16 q17 q23'])
        windows,structure=extract_windows(lines)
        self.assertEqual(structure['eligible_windows'],1)
        row=solve_window((windows[0],2,1))
        self.assertEqual((row['status'],row['products']),('improved',2))
        # replacement verifies all 256 rows, including nonzero target offsets.
        gates=replacement(lines,windows[0],row)
        self.assertEqual(sum(x.startswith('CCX ') for x in gates),2)

    def test_target_dependency_rejected(self):
        lines=toy_lines(['CCX q14 q15 q22','CCX q22 q16 q23'])
        windows,structure=extract_windows(lines)
        self.assertEqual(windows,[])
        self.assertEqual(structure['rejected'][0]['reason'],'original controls unavailable without targets')

    def test_escaped_nonlinear_value_rejected(self):
        lines=toy_lines(['R q24','CCX q14 q15 q22','CX q22 q24','CCX q16 q17 q23'])
        windows,structure=extract_windows(lines)
        self.assertEqual(windows,[])
        self.assertIn('escape',structure['rejected'][0]['reason'])

    def test_affine_tail_is_completed_before_escape_test(self):
        lines=toy_lines(['CCX q14 q15 q22','CX q22 q20','CCX q16 q17 q23','CX q22 q20'])
        windows,structure=extract_windows(lines)
        self.assertEqual(windows,[])
        windows,structure=extract_windows(lines,complete_affine_tail=True)
        self.assertEqual(len(windows),1)
        self.assertEqual(windows[0]['end'],len(lines)-1)

    def test_affine_constants_are_preserved(self):
        basis=[(14,INPUTS[14]),(15,INPUTS[15])]
        rep=normalized_representation(1<<3,[(1|4,2|4)],2)
        self.assertEqual(evaluate(rep,basis),(INPUTS[14]^ALL)&(INPUTS[15]^ALL))

    def test_disjoint_selection_maximizes_saved_gates(self):
        def row(lo,hi,saving):return dict(start=lo,end=hi,original_count=saving+1,products=1,status='improved')
        results=[row(0,4,2),row(0,2,1),row(2,5,3)]
        chosen=select_nonoverlapping(results)
        self.assertEqual([(r['start'],r['end']) for r in chosen],[(0,2),(2,5)])


if __name__=='__main__':unittest.main()
