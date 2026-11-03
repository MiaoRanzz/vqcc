"""Top-3 control tests use tiny artificial artifacts, never scientific validators."""
from copy import deepcopy
import math
import unittest
from unittest.mock import patch

from pipeline import PipelineError, read_json, sha256, write_json
from search import Search
import test_pipeline as fixtures


class SearchTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    tearDown = fixtures.PipelineTests.tearDown
    fixture = fixtures.PipelineTests.fixture

    def seed(self):
        ids = [self.fixture('invsqrt', cost) for cost in (70, 80, 90)]
        return Search(self.pipeline), ids

    def child(self, parents, cost=60):
        cid = self.fixture('invsqrt', cost)
        path, data = self.pipeline.candidate(cid)
        data.update(parent=parents[0], parents=parents)
        write_json(path / 'candidate.json', data)
        return cid

    def proof(self, cycle, key, **changes):
        step = next(item for item in cycle['steps'] if item['key'] == key)
        path = self.pipeline.storage / f'{cycle["cycle_id"]}-{key}-proof.json'
        write_json(path, dict(task='invsqrt', cycle_id=cycle['cycle_id'], step=key,
                             parents=step['parents'], conclusion='infeasible',
                             reason='Exact constraint violation in fixture',
                             measurements={'required_qubits': 129, 'cap': 128}, **changes))
        return path

    def test_rank_three_valid_distinct_artifacts_without_running_verifiers(self):
        search, ids = self.seed()
        self.pipeline.create('invsqrt', 'unverified lower estimate', 'fixture', 'test')
        bad = self.fixture('invsqrt', 5)
        path, _ = self.pipeline.candidate(bad)
        (path / 'output/invsqrt.kmb').write_bytes(b'tampered')
        with patch.object(self.pipeline, 'runtime', side_effect=AssertionError('No scientific rerun')):
            plan = search.plan('invsqrt')
        cycle = plan['tasks']['invsqrt']
        self.assertEqual([item['id'] for item in cycle['roots']], ids)
        self.assertEqual([item['cost'] for item in cycle['roots']], [70, 80, 90])
        self.assertIn(bad, [item['id'] for item in cycle['ranking_exclusions']])
        self.assertEqual([item['status'] for item in cycle['steps']], ['pending'] * 3 + ['blocked'])

    def test_identical_artifacts_use_earliest_evidence_not_the_lowest_score(self):
        _, ids = self.seed()
        duplicate = self.fixture('invsqrt', 70)
        path, data = self.pipeline.candidate(ids[0])
        data['created_at'] = '2026-01-01T00:00:00+08:00'
        write_json(path / 'candidate.json', data)
        path, data = self.pipeline.candidate(duplicate)
        report = read_json(path / 'official.json')
        report['score'] = 1
        write_json(path / 'official.json', report)
        data['verification']['report_sha256'] = sha256(path / 'official.json')
        write_json(path / 'candidate.json', data)
        with self.pipeline.locked():
            result = self.pipeline.top_candidates('invsqrt')
        self.assertEqual([item['id'] for item in result['candidates']], ids)
        self.assertEqual(result['candidates'][0]['cost'], 70)
        self.assertIn(duplicate, result['candidates'][0]['equivalent_candidates'])

    def test_invalid_copy_falls_back_to_valid_same_artifact(self):
        _, ids = self.seed()
        replacement = self.fixture('invsqrt', 70)
        path, data = self.pipeline.candidate(ids[0])
        data['created_at'] = '2026-01-01T00:00:00+08:00'
        data['verification']['runtime_fingerprint'] = {'python': 'obsolete'}
        write_json(path / 'candidate.json', data)
        with self.pipeline.locked():
            result = self.pipeline.top_candidates('invsqrt')
        self.assertEqual([item['id'] for item in result['candidates']], [replacement, *ids[1:]])

    def test_shortfall_is_not_padded_with_duplicates(self):
        self.fixture('invsqrt', 100)
        cycle = Search(self.pipeline).plan('invsqrt')['tasks']['invsqrt']
        self.assertEqual(cycle['shortfall'], 2)
        self.assertEqual(len(cycle['roots']), 1)
        self.assertEqual(cycle['steps'][-1]['status'], 'unavailable')

    def test_invalid_early_copy_cannot_hide_a_better_valid_artifact_family(self):
        _, ids = self.seed()
        self.fixture('invsqrt', 85)
        replacement = self.fixture('invsqrt', 90)
        path, data = self.pipeline.candidate(ids[2])
        data['created_at'] = '2026-01-01T00:00:00+08:00'
        write_json(path / 'candidate.json', data)
        (path / 'output/invsqrt.kmb').write_bytes(b'changed')
        path, data = self.pipeline.candidate(replacement)
        report = read_json(path / 'official.json')
        report['score'] = 2
        write_json(path / 'official.json', report)
        data['verification']['report_sha256'] = sha256(path / 'official.json')
        write_json(path / 'candidate.json', data)
        with self.pipeline.locked():
            result = self.pipeline.top_candidates('invsqrt')
        self.assertEqual([item['id'] for item in result['candidates']], [replacement, *ids[:2]])

    def test_combined_candidate_records_all_same_task_parents(self):
        _, ids = self.seed()
        item = self.pipeline.create('invsqrt', 'combine', 'fixture', 'test', parents=ids)
        self.assertEqual(item['parent'], ids[0])
        self.assertEqual(item['parents'], ids)
        with self.assertRaisesRegex(PipelineError, 'same task'):
            self.pipeline.create('invsqrt', 'bad merge', 'fixture', 'test', parents=[ids[0], self.pipeline.state['best']['dqi']])

    def test_cycle_pins_three_branches_and_requires_separate_combined_validation(self):
        search, ids = self.seed()
        cycle = search.plan('invsqrt')['tasks']['invsqrt']
        cycle_id = cycle['cycle_id']
        first = self.child([ids[0]], 60)
        self.pipeline.promote(first)
        cycle = search.record('invsqrt', cycle_id, 'top1', [first])
        resumed = Search(self.pipeline).plan('invsqrt')['tasks']['invsqrt']
        self.assertEqual(resumed['cycle_id'], cycle_id)
        self.assertEqual([root['id'] for root in resumed['roots']], ids)
        with self.assertRaisesRegex(PipelineError, 'not pending'):
            search.record('invsqrt', cycle_id, 'combined', [first])
        # A more expensive valid child does not replace its own branch's root.
        second = self.child([ids[1]], 85)
        third = self.child([ids[2]], 65)
        search.record('invsqrt', cycle_id, 'top2', [second])
        cycle = search.record('invsqrt', cycle_id, 'top3', [third])
        parents = [first, ids[1], third]
        self.assertEqual(cycle['steps'][-1]['parents'], parents)
        self.assertEqual(cycle['steps'][-1]['status'], 'pending')
        merge = self.pipeline.create('invsqrt', 'merge', 'fixture', 'test', parents=parents)
        with self.assertRaisesRegex(PipelineError, 'completed official validation'):
            search.record('invsqrt', cycle_id, 'combined', [merge['id']])
        # The three individual PASS reports cannot stand in for the merge.
        self.assertEqual(read_json(search.path)['tasks']['invsqrt']['status'], 'active')
        combined = self.child(parents, 50)
        cycle = search.record('invsqrt', cycle_id, 'combined', [combined])
        self.assertEqual(cycle['status'], 'completed')
        updated = search.plan('invsqrt')['tasks']['invsqrt']
        self.assertNotEqual(updated['cycle_id'], cycle_id)
        self.assertEqual(updated['roots'][0]['id'], combined)
        self.assertTrue((search.path.parent / 'top3-history' / f'{cycle_id}.json').is_file())

    def test_each_independent_result_requires_its_own_evidence_and_ancestry(self):
        search, ids = self.seed()
        cycle = search.plan('invsqrt')['tasks']['invsqrt']
        child = self.pipeline.create('invsqrt', 'unverified', 'fixture', 'test', parent=ids[0])
        with self.assertRaisesRegex(PipelineError, 'completed official validation'):
            search.record('invsqrt', cycle['cycle_id'], 'top1', [child['id']])
        wrong = self.child([ids[1]], 60)
        with self.assertRaisesRegex(PipelineError, 'step parents'):
            search.record('invsqrt', cycle['cycle_id'], 'top1', [wrong])
        with self.assertRaisesRegex(PipelineError, 'cycle changed'):
            search.record('invsqrt', 'old-cycle', 'top1', [wrong])

    def test_full_official_failure_completes_branch_but_not_an_interrupted_check(self):
        search, ids = self.seed()
        cycle = search.plan('invsqrt')['tasks']['invsqrt']
        cid = self.child([ids[0]], 60)
        path, data = self.pipeline.candidate(cid)
        record = data.pop('verification')
        write_json(path / 'official.json', {'status': 'FAIL', 'error': 'incorrect phase'})
        record.update(passed=False, returncode=1, report_sha256=sha256(path / 'official.json'))
        data['runs'] = [record]
        write_json(path / 'candidate.json', data)
        with self.assertRaisesRegex(PipelineError, 'completed official validation'):
            search.record('invsqrt', cycle['cycle_id'], 'top1', [cid])
        record['finished_at'] = self.pipeline.now_string()
        write_json(path / 'candidate.json', data)
        result = search.record('invsqrt', cycle['cycle_id'], 'top1', [cid])
        self.assertEqual(result['steps'][0]['results'][0]['status'], 'FAIL')
        self.assertEqual(result['steps'][-1]['status'], 'blocked')

    def test_infeasibility_requires_bound_measurements_not_a_deferral(self):
        search, _ = self.seed()
        cycle = search.plan('invsqrt')['tasks']['invsqrt']
        proof = self.proof(cycle, 'top1')
        saved = read_json(proof)
        write_json(proof, {**saved, 'conclusion': 'time_limit'})
        with self.assertRaisesRegex(PipelineError, 'concrete conclusion'):
            search.record('invsqrt', cycle['cycle_id'], 'top1', evidence=proof)
        write_json(proof, saved)
        result = search.record('invsqrt', cycle['cycle_id'], 'top1', evidence=proof)
        self.assertEqual(result['steps'][0]['evidence']['sha256'], sha256(proof))

    def test_pinned_parent_mutation_does_not_silently_refresh_the_cycle(self):
        search, ids = self.seed()
        cycle = search.plan('invsqrt')['tasks']['invsqrt']
        before = deepcopy(read_json(search.path))
        path, _ = self.pipeline.candidate(ids[0])
        (path / 'output/invsqrt.kmb').write_bytes(b'changed')
        with self.assertRaisesRegex(PipelineError, 'Artifact changed'):
            search.plan('invsqrt')
        self.assertEqual(read_json(search.path), before)
        self.assertEqual(before['tasks']['invsqrt']['cycle_id'], cycle['cycle_id'])

    def test_general_round_does_not_refresh_finished_task_ahead_of_others(self):
        search, _ = self.seed()
        plan = search.plan()
        cycle = plan['tasks']['invsqrt']
        for key in ('top1', 'top2', 'top3', 'combined'):
            proof = self.proof(cycle, key)
            cycle = search.record('invsqrt', cycle['cycle_id'], key, evidence=proof)
        next_plan = search.plan()
        self.assertEqual(next_plan['tasks']['invsqrt']['cycle_id'], cycle['cycle_id'])
        self.assertEqual(next_plan['tasks']['invsqrt']['status'], 'completed')
        self.assertEqual(next_plan['tasks']['dqi']['status'], 'active')


    def test_close_relatives_do_not_fill_top3_but_unrelated_near_ties_do(self):
        search, ids = self.seed()
        sibling = self.child([ids[0]], cost=70.03)
        unrelated = self.fixture('invsqrt', 70.02)
        path, data = self.pipeline.candidate(unrelated)
        data.update(parent=None, parents=[])  # e.g. an imported public artifact
        write_json(path / 'candidate.json', data)
        self.pipeline.config['top3_min_relative_gap'] = 0.001
        cycle = search.plan('invsqrt')['tasks']['invsqrt']
        self.assertEqual([item['id'] for item in cycle['roots']], [ids[0], unrelated, ids[1]])
        self.assertIn({'id': sibling, 'reason': f'near_duplicate_of {ids[0]}'}, cycle['ranking_exclusions'])

    def test_far_better_leader_preempts_unfinished_cycle(self):
        search, ids = self.seed()
        first = search.plan('invsqrt')['tasks']['invsqrt']
        leader = self.fixture('invsqrt', 69.5)
        self.pipeline.config['top3_preempt_fraction'] = 0.01
        self.assertEqual(search.plan('invsqrt')['tasks']['invsqrt']['cycle_id'], first['cycle_id'])
        leader = self.fixture('invsqrt', 60)
        cycle = search.plan('invsqrt')['tasks']['invsqrt']
        self.assertNotEqual(cycle['cycle_id'], first['cycle_id'])
        self.assertEqual(cycle['roots'][0]['id'], leader)
        self.assertEqual(cycle['replaces']['cycle_id'], first['cycle_id'])
        archived = read_json(self.pipeline.storage / 'research/top3-history' / (first['cycle_id'] + '.json'))
        self.assertEqual(archived['status'], 'preempted')
        with self.assertRaises(PipelineError):
            search.record('invsqrt', first['cycle_id'], 'top1', [self.child([ids[0]])])

    def test_frontier_orders_tasks_by_public_headroom(self):
        search, ids = self.seed()
        self.pipeline.promote(ids[0])
        allocation = search.frontier('invsqrt', 35, 'notebook/v3', 'claimed')['allocation']
        self.assertEqual(allocation[0]['task'], 'invsqrt')
        self.assertAlmostEqual(allocation[0]['log_score_headroom'], math.log(2) / 3)
        self.assertEqual({row['status'] for row in allocation[1:]}, {'unknown_frontier'})
        search.frontier('invsqrt', 50, 'other/v1', 'claimed')
        stored = read_json(self.pipeline.storage / 'research/frontier.json')['invsqrt']
        self.assertEqual((stored['cost'], len(stored['history'])), (35, 2))
        self.assertEqual(search.plan('invsqrt')['allocation'][0]['public_best'], 35)
        with self.assertRaises(PipelineError):
            search.frontier('dqi', 1, 'x', None)


    def test_allocation_shares_follow_headroom_with_a_floor(self):
        search, _ = self.seed()
        allocation = search.frontier('invsqrt', 35, 'notebook/v3', 'claimed')['allocation']
        self.assertAlmostEqual(sum(row['share'] for row in allocation), 1, places=2)
        self.assertEqual(allocation[0]['task'], 'invsqrt')
        self.assertGreater(allocation[0]['share'], allocation[1]['share'])
        self.assertTrue(all(row['share'] >= 0.15 for row in allocation))

    def test_auto_no_change_only_when_at_most_one_branch_improved(self):
        search, ids = self.seed()
        cycle_id = search.plan('invsqrt')['tasks']['invsqrt']['cycle_id']
        with self.assertRaisesRegex(PipelineError, 'not pending'):
            search.record('invsqrt', cycle_id, 'combined', auto_no_change=True)
        first = self.child([ids[0]], 60)
        search.record('invsqrt', cycle_id, 'top1', [first])
        search.record('invsqrt', cycle_id, 'top2', [self.child([ids[1]], 95)])
        cycle = search.record('invsqrt', cycle_id, 'top3', evidence=self.proof(
            search.plan('invsqrt')['tasks']['invsqrt'], 'top3'))
        self.assertEqual(cycle['steps'][-1]['parents'], [first, ids[1], ids[2]])
        cycle = search.record('invsqrt', cycle_id, 'combined', auto_no_change=True)
        self.assertEqual(cycle['status'], 'completed')
        proof = read_json(cycle['steps'][-1]['evidence']['path'])
        self.assertEqual(proof['conclusion'], 'no_change')
        self.assertIn(first, proof['reason'])

    def test_auto_no_change_refuses_two_improved_branches(self):
        search, ids = self.seed()
        cycle_id = search.plan('invsqrt')['tasks']['invsqrt']['cycle_id']
        search.record('invsqrt', cycle_id, 'top1', [self.child([ids[0]], 60)])
        search.record('invsqrt', cycle_id, 'top2', [self.child([ids[1]], 61)])
        search.record('invsqrt', cycle_id, 'top3', [self.child([ids[2]], 95)])
        with self.assertRaisesRegex(PipelineError, 'real combined candidate'):
            search.record('invsqrt', cycle_id, 'combined', auto_no_change=True)

    def test_two_day_review_periods_are_anchored_and_complete(self):
        from datetime import date
        search, _ = self.seed()
        self.assertEqual(search.review_period(date(2026, 11, 3))['interval'], ['2026-11-01', '2026-11-03'])
        self.assertEqual(search.review_period(date(2026, 11, 4))['period'], '2026-11-01')
        self.assertEqual(search.review_period(date(2026, 11, 5))['period'], '2026-11-03')

    def test_handoff_rank_brief_and_report(self):
        search, ids = self.seed()
        search.plan('invsqrt')
        search.handoff('invsqrt', 'validate X', step='top1', candidates=['c1', 'c1'], commands=['cmd'], run_id='r1')
        document = search.handoff('invsqrt', 'record X', step='top1')
        self.assertEqual(document['tasks']['invsqrt']['next_action'], 'record X')
        self.assertEqual(document['tasks']['invsqrt']['history'][0]['candidates'], ['c1'])
        with self.assertRaisesRegex(PipelineError, '--next'):
            search.handoff('invsqrt')
        write_json(search.hypotheses_path, {'queue': [
            {'id': 'low', 'task': 'dqi', 'expected_log_combined_gain_prior': 0.01, 'p_success': 0.5, 'effort_hours': 1},
            {'id': 'high', 'task': 'dqi', 'expected_log_combined_gain_prior': 0.05, 'p_success': 0.5, 'effort_hours': 1},
            {'id': 'resume', 'task': 'invsqrt', 'status': 'pending_validation', 'candidate_ids': ['c1']},
            {'id': 'vague', 'task': 'dfthcsos'},
            {'id': 'done', 'status': 'completed', 'candidate_ids': ['c0']}]})
        ranked = search.rank()
        self.assertEqual([item['id'] for item in ranked['items']], ['resume', 'high', 'low', 'vague'])
        self.assertIn('p_success', ranked['items'][-1]['missing'])
        brief = search.brief()
        self.assertEqual(brief['cycles']['invsqrt']['roots'][0]['id'], ids[0])
        self.assertTrue(brief['due']['daily_public_scan']['due'])
        review = brief['due']['review']
        self.assertTrue(review['due'])
        write_json(self.pipeline.storage / 'research/reviews/index.json', {'last_completed_period': review['period']})
        self.assertFalse(search.brief()['due']['review']['due'])
        self.assertEqual(brief['handoff']['invsqrt']['next_action'], 'record X')
        report = search.report()
        self.assertIn('Top-3', report)
        self.assertIn('record X', report)


if __name__ == '__main__':
    unittest.main()
