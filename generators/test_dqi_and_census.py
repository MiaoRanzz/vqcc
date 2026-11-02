# SPDX-License-Identifier: Apache-2.0
"""Exact AND recognition and sound clean-wire observations at reset boundaries."""
import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import kickmix as km
from dqi_and_census import classify, census
from dqi_boolean_reduce import compile_scanner

BORROWED=[(0,1,3),(3,2,4),(0,1,3),(3,2,4)]
HEADER='REGISTER r0 "input"\n'+''.join(f'APPEND_TO_REGISTER q{i} r0\n' for i in range(4))

class CensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.scanner=cls.root/'scanner';compile_scanner(cls.scanner)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_dirty_borrow_and_old_target(self):
        r=classify(BORROWED)
        self.assertEqual((r['decision'],r['controls'],r['borrowed'],r['target']),('exact_and',[0,1,2],[3],4))
        for value in range(32):
            state=[(value>>q)&1 for q in range(5)];old=state.copy()
            for a,b,t in BORROWED:state[t]^=state[a]&state[b]
            self.assertEqual(state[:4],old[:4])
            self.assertEqual(state[4],old[4]^(old[0]&old[1]&old[2]))

    def test_not_all_ccx_runs_are_and(self):
        self.assertEqual(classify(BORROWED[:-1])['decision'],'not_monomial')
        self.assertEqual(classify(BORROWED*2)['decision'],'not_single_target')

    def test_enclosing_conditions_excluded(self):
        text=HEADER+'BIT_STORE0 b0\nPUSH_CONDITION if b0\n'+''.join(f'CCX q{a} q{b} q{t}\n' for a,b,t in BORROWED)+'POP_CONDITION\n'
        path=self.root/'guarded.kmb';km.Circuit(text).to_file(path,format="kmb")
        r=census(path);self.assertEqual(r['sites'],[]);self.assertEqual(r['guarded_runs'],1)

    def test_zero_observation_resets_and_unknown_input(self):
        source=self.root/'observe.kmb'
        km.Circuit(HEADER+'X q4\nHMR q4 b0\nX q4 if b0\nR q4\nX q5\n').to_file(source,format="kmb")
        queries=self.root/'query';queries.write_text('0\n1\n2\n3\n4\n')
        out=self.root/'zeros.tsv'
        args=[str(self.scanner),str(source),str(self.root/'proofs'),str(self.root/'summary'),'512','0','0','1',str(queries),str(out)]
        subprocess.run(args,check=True,capture_output=True)
        with out.open() as stream:
            rows=list(csv.DictReader(stream,delimiter='\t'))
        actual=[set(map(int,r['zero_wires'].split(','))) for r in rows]
        self.assertEqual(actual,[{4,5},{5},{4,5},{5},{4,5}])
        queries.write_text('100\n')
        self.assertNotEqual(subprocess.run(args,capture_output=True).returncode,0)

if __name__=='__main__':unittest.main()
