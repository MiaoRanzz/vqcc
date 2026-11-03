"""Queue and supervisor acceptance using isolated state and fake processes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from jobs import ControlError, Jobs, atomic_json

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / 'automation/config.json').read_text())
# Pin the earlier schedule and budget defaults; these cases test queue logic, not the current deployment.
for _key in ('submission_timezone', 'optimize_slot_minutes', 'daily_model_limit',
             'optimize_allow_subagents', 'validation_parallelism'):
    BASE.pop(_key, None)
BASE.update(daily_submission_time='20:00', daily_submission_times=['08:00', '20:00'], max_daily_submissions=3,
            submit_window_minutes=45, reconcile_time='20:55',
            optimize_windows=[['00:10', '05:55'], ['06:10', '07:25'], ['09:10', '11:55'], ['12:10', '17:55'], ['18:10', '19:25']])


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='vqcc-console-')
        self.addCleanup(self.tmp.cleanup)
        self.storage = Path(self.tmp.name)
        (self.storage / 'runtime').mkdir()
        self.path = self.storage / 'config.json'
        self.cfg = {**BASE, 'submission_policy': 'daily_window', 'storage_root': str(self.storage), 'min_free_gib': 0,
                    'model': 'fake-model', 'python_executable': sys.executable}
        atomic_json(self.path, self.cfg)
        self.now = datetime.fromisoformat('2026-10-30T10:00:00+08:00')
        self.jobs = Jobs(self.path, initialize=True, clock=lambda: self.now)

    def request(self, **extra):
        return {'kind': 'smoke', 'max_seconds': 30, **extra}

    def enqueue(self, key='once', **extra):
        return self.jobs.enqueue(self.request(**extra), key)

    def test_parallel_idempotent_creation_and_mismatched_body(self):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.enqueue(), range(2)))
        self.assertEqual(results[0]['job_id'], results[1]['job_id'])
        self.assertEqual(len(self.jobs.snapshot()['jobs']), 1)
        with self.assertRaises(ControlError) as caught:
            self.enqueue(hypothesis='different')
        self.assertEqual(caught.exception.code, 'STATE_CONFLICT')

    def test_relay_optimize_slots_do_not_pile_up_and_may_use_subagents(self):
        self.jobs.base['optimize_allow_subagents'] = True
        self.jobs.enqueue_slot(('2026-10-30-optimize-1000', 'optimize', 3600))
        self.jobs.enqueue_slot(('2026-10-30-optimize-1100', 'optimize', 3600))
        jobs = list(self.jobs.snapshot()['jobs'].values())
        self.assertEqual([job['slot_id'] for job in jobs], ['2026-10-30-optimize-1000'])
        self.assertTrue(jobs[0]['allow_subagents'])
        self.jobs.cancel(jobs[0]['job_id'], 'queued', jobs[0]['revision'], 'cancel')
        self.jobs.enqueue_slot(('2026-10-30-optimize-1100', 'optimize', 3600))
        self.assertIn('2026-10-30-optimize-1100', [job['slot_id'] for job in self.jobs.snapshot()['jobs'].values()])

    def test_cancel_queued_does_not_reserve_model_budget(self):
        job = self.enqueue()
        self.jobs.cancel(job['job_id'], 'queued', job['revision'], 'cancel')
        self.assertEqual(self.jobs.usage()['reserved'], 0)
        self.assertIsNone(self.jobs.claim())

    def test_cancel_starting_conflicts_and_stop_is_separate(self):
        job = self.enqueue()
        started = self.jobs.claim()
        with self.assertRaises(ControlError):
            self.jobs.cancel(job['job_id'], 'queued', job['revision'], 'cancel')
        self.jobs.stop(started['job_id'], started['run_id'], started['revision'], 'stop')
        factory = lambda: self.fail('cancelled starting job must not spawn')
        self.assertIsNone(self.jobs.spawn(started['job_id'], started['run_id'], factory))
        self.assertEqual(self.jobs.usage()['reserved'], 0)
        self.assertFalse(self.jobs.snapshot()['scheduler']['paused'])

    def test_atomic_last_budget_and_local_queue_progress(self):
        with self.jobs.transaction() as state:
            state['configs'][0]['config'].update(daily_model_limit=1, reserve_submit=0, reserve_reconcile=0)
        self.enqueue(key='a')
        self.enqueue(key='b')
        with ThreadPoolExecutor(2) as pool:
            claimed = list(pool.map(lambda _: self.jobs.claim(), range(2)))
        started = next(job for job in claimed if job)
        self.assertEqual(sum(job is not None for job in claimed), 1)
        # An attempted startup remains consumed even if the run failed.
        self.jobs.finished(started['job_id'], {'status': 'failed', 'finished_at': self.now.isoformat()})
        local = self.enqueue(key='c', kind='prepare_preview')
        self.assertEqual(self.jobs.claim()['job_id'], local['job_id'])
        self.assertEqual(self.jobs.usage()['reserved'], 1)

    def test_reserved_submission_and_reconciliation_are_within_total(self):
        with self.jobs.transaction() as state:
            for i in range(4):
                state['reservations'][str(i)] = {'budget_date': '2026-10-30', 'kind': 'optimize', 'started_at': 'yes'}
            self.assertEqual(self.jobs._budget_reason({'kind': 'optimize'}, state), 'DAILY_MODEL_BUDGET_EXHAUSTED')
            self.assertIsNone(self.jobs._budget_reason({'kind': 'submit'}, state))
            state['reservations']['s'] = {'budget_date': '2026-10-30', 'kind': 'submit', 'started_at': 'yes'}
            self.assertEqual(self.jobs._budget_reason({'kind': 'submit'}, state), 'DAILY_MODEL_BUDGET_EXHAUSTED')
            self.assertIsNone(self.jobs._budget_reason({'kind': 'reconcile'}, state))
            state['reservations']['r'] = {'budget_date': '2026-10-30', 'kind': 'reconcile', 'started_at': 'yes'}
            self.assertEqual(self.jobs._budget_reason({'kind': 'reconcile'}, state), 'DAILY_MODEL_BUDGET_EXHAUSTED')

    def test_pause_keeps_manual_tasks_and_existing_run(self):
        job = self.enqueue()
        self.jobs.scheduler('pause', 'pause')
        started = self.jobs.claim()
        self.assertEqual(started['job_id'], job['job_id'])
        self.assertEqual(started['state'], 'starting')
        self.jobs.scheduler('resume', 'resume')
        self.assertEqual(self.jobs.snapshot()['jobs'][job['job_id']]['state'], 'starting')

    def test_config_freezes_and_lower_resource_blocks_queued(self):
        job = self.enqueue()
        self.jobs.save_config({'cpu_limit': 10}, 1, 'save')
        self.jobs.activate_config(2, 2, 'activate')
        self.assertIsNone(self.jobs.claim())
        queued = self.jobs.snapshot()['jobs'][job['job_id']]
        self.assertEqual(queued['config']['cpu_limit'], 20)
        self.assertEqual(queued['blocked_reason'], 'CONFIG_RESOURCE_LIMIT')
        with self.assertRaises(ControlError):
            self.jobs.save_config({'cpu_limit': 12}, 1, 'stale')

    def test_rollback_creates_new_revision_and_old_activation_is_rejected(self):
        self.jobs.save_config({'cpu_limit': 10}, 1, 'save')
        self.jobs.activate_config(2, 2, 'activate')
        with self.assertRaises(ControlError):
            self.jobs.activate_config(1, 2, 'rollback-direct')
        original = self.jobs.config_view()['history'][0]['config']
        self.jobs.save_config(original, 2, 'rollback-copy')
        self.jobs.activate_config(3, 3, 'activate-copy')
        self.assertEqual(self.jobs.config_view()['config']['cpu_limit'], 20)

    def test_generator_schema_refresh_and_dataset_binding(self):
        original = self.jobs.parameter_schemas()['generator_revision']
        with patch('jobs.generator_revision', return_value='updated-source'):
            self.assertEqual(self.jobs.parameter_schemas()['generator_revision'], 'updated-source')
        self.assertEqual(self.jobs.parameter_schemas()['generator_revision'], original)
        job = self.enqueue(kind='local_experiment', task='dfthcsos', hypothesis='source binding')
        dataset = {**self.jobs.dataset(), 'sha256': 'changed'}
        with patch.object(self.jobs, 'dataset', return_value=dataset):
            self.assertIsNone(self.jobs.claim())
        self.assertEqual(self.jobs.snapshot()['jobs'][job['job_id']]['blocked_reason'], 'DATASET_CHANGED')

    def test_long_job_waits_for_protected_window(self):
        self.now = datetime.fromisoformat('2026-10-30T19:24:40+08:00')
        self.assertEqual(self.jobs.preview(self.request())['blocked_reason'], 'PROTECTED_WINDOW')
        self.now = datetime.fromisoformat('2026-10-30T21:16:00+08:00')
        self.assertIsNone(self.jobs.preview(self.request())['blocked_reason'])

    def test_late_reconcile_extends_protection_then_expires(self):
        atomic_json(self.storage / 'state/pipeline.json', {'submissions': {'s': {'date': '2026-10-30', 'status': 'score_unknown', 'submission_id': 7}}})
        self.now = datetime.fromisoformat('2026-10-30T21:16:00+08:00')
        self.assertEqual(self.jobs.preview(self.request())['blocked_reason'], 'PROTECTED_WINDOW')
        self.now = datetime.fromisoformat('2026-10-30T22:55:00+08:00')
        self.assertIsNone(self.jobs.preview(self.request())['blocked_reason'])

    def test_restart_startup_intent_never_respawns(self):
        job = self.enqueue()
        started = self.jobs.claim()
        with self.jobs.transaction() as state:
            state['jobs'][job['job_id']]['supervisor_start'] = -1
        restarted = Jobs(self.path, clock=lambda: self.now)
        self.assertIsNone(restarted.claim())
        self.assertEqual(restarted.snapshot()['jobs'][job['job_id']]['state'], 'unknown')
        self.assertEqual(restarted.usage()['reserved'], 1)

    def test_cross_midnight_not_spawned_moves_reservation(self):
        self.now = datetime.fromisoformat('2026-10-30T23:59:00+08:00')
        self.enqueue()
        started = self.jobs.claim()
        self.now = datetime.fromisoformat('2026-10-31T00:00:01+08:00')
        class Fake:
            pid = os.getpid()
        self.jobs.spawn(started['job_id'], started['run_id'], Fake)
        self.assertEqual(self.jobs.usage('2026-10-30')['reserved'], 0)
        self.assertEqual(self.jobs.usage('2026-10-31')['started'], 1)

    def test_started_unknown_budget_keeps_original_date(self):
        self.now = datetime.fromisoformat('2026-10-30T23:59:00+08:00')
        self.enqueue()
        started = self.jobs.claim()
        class Fake:
            pid = os.getpid()
        self.jobs.spawn(started['job_id'], started['run_id'], Fake)
        self.now = datetime.fromisoformat('2026-10-31T00:00:01+08:00')
        self.assertIsNone(self.jobs.claim())
        self.assertEqual(self.jobs.usage('2026-10-30')['started'], 1)
        self.assertEqual(self.jobs.usage('2026-10-31')['reserved'], 0)

    def test_stop_scheduler_rejects_active_and_shared_lock(self):
        self.enqueue()
        self.jobs.claim()
        with self.assertRaises(ControlError):
            self.jobs.scheduler('stop', 'stop-scheduler')
        with self.jobs.transaction() as state:
            for job in state['jobs'].values():
                job['state'] = 'completed'
        with (self.storage / 'runtime/agent.lock').open('a') as locked:
            fcntl.flock(locked, fcntl.LOCK_EX)
            with self.assertRaises(ControlError):
                self.jobs.scheduler('stop', 'stop-locked')
        self.assertFalse(self.jobs.scheduler('stop', 'stop-idle')['dispatch_enabled'])

    def test_final_result_wins_over_stop_request(self):
        self.enqueue()
        started = self.jobs.claim()
        self.jobs.stop(started['job_id'], started['run_id'], started['revision'], 'stop')
        self.jobs.finished(started['job_id'], {'status': 'completed', 'stop_reason': None, 'finished_at': self.now.isoformat()})
        record = self.jobs.snapshot()['jobs'][started['job_id']]
        self.assertEqual(record['state'], 'completed')
        self.assertIn('stop_requested_at', record)

    def test_unknown_parameter_and_cross_parameter_validation(self):
        for params in ({'bogus': 1}, {'delta_bits': 17, 'coef_bits': 17}):
            with self.assertRaises(ControlError):
                self.jobs.preview(self.request(kind='local_experiment', task='invsqrt', parameters=params, hypothesis='x'))
        for params in ({'prefix_bits': 1}, {'brot': 30, 'batch_size': 75}):
            with self.assertRaises(ControlError):
                self.jobs.preview(self.request(kind='local_experiment', task='dfthcsos', parameters=params, hypothesis='x'))

    def test_known_yesterday_submission_does_not_consume_today(self):
        atomic_json(self.storage / 'state/pipeline.json', {'submissions': {'s': {'date': '2026-10-29', 'status': 'score_unknown', 'submission_id': 7}}})
        self.assertEqual(self.jobs.submission_precheck(), 'EVIDENCE_STALE')
        atomic_json(self.storage / 'state/pipeline.json', {'submissions': {'s': {'date': '2026-10-29', 'status': 'upload_started'}}})
        self.assertEqual(self.jobs.submission_precheck(), 'SUBMISSION_NEEDS_RECONCILIATION')

    def test_automatic_slot_uses_remaining_window_after_queue_delay(self):
        self.jobs.enqueue_slot(('2026-10-30-optimize-0610', 'optimize', 1200))
        self.now = self.now.replace(second=7)
        job = self.jobs.claim()
        self.assertIsNotNone(job)
        self.assertEqual(job['max_seconds'], 1183)
        self.assertEqual(job['requested_max_seconds'], 1190)

    def test_local_generation_never_calls_model(self):
        preview = self.jobs.preview(self.request(kind='local_experiment', task='dqi', parameters={'stack_cap': 1}, hypothesis='test'))
        self.assertTrue(preview['request']['validate'])
        self.assertFalse(preview['calls_model'])
        self.assertEqual(self.jobs.usage()['reserved'], 0)

    def test_all_local_experiments_require_official_validation(self):
        for task in ('dqi', 'invsqrt', 'dfthcsos'):
            for options in ({}, {'validate': True}):
                with self.subTest(task=task, options=options):
                    request = self.request(kind='local_experiment', task=task, hypothesis='test', **options)
                    self.assertTrue(self.jobs.preview(request)['request']['validate'])
                    job = self.jobs.enqueue(request, f'{task}-{options}')
                    self.assertTrue(self.jobs.snapshot()['jobs'][job['job_id']]['validate'])
            with self.subTest(task=task, validate=False):
                request = self.request(kind='local_experiment', task=task, hypothesis='test', validate=False)
                with self.assertRaises(ControlError) as error:
                    self.jobs.enqueue(request, task + '-disabled')
                self.assertEqual(error.exception.status, 422)
                self.assertIn('validate', error.exception.field_errors)
        self.assertEqual(self.jobs.usage()['reserved'], 0)


class SupervisorIntegrationTests(unittest.TestCase):
    """Run supervisors in separate processes to isolate Linux subreaper ownership."""
    setUp = QueueTests.setUp
    request = QueueTests.request
    enqueue = QueueTests.enqueue

    def write_fake(self, sleep=False):
        fake = self.storage / 'fake-codex'
        fake.write_text(f'''#!{sys.executable}
import json,sys,time
from pathlib import Path
prompt = sys.stdin.read()
Path({str(self.storage / 'model-input.json')!r}).write_text(json.dumps({{'argv': sys.argv[1:], 'prompt': prompt}}))
print(json.dumps({{'type': 'turn.completed', 'usage': {{'input_tokens': 12, 'output_tokens': 3}}}}), flush=True)
time.sleep({60 if sleep else 0.2})
''')
        fake.chmod(0o700)
        self.cfg['codex_executable'] = str(fake)
        atomic_json(self.path, self.cfg)

    def driver(self):
        script = self.storage / 'driver.py'
        script.write_text(f'''import sys,json,fcntl
from pathlib import Path
from datetime import datetime
sys.path.insert(0, {str(ROOT / 'automation')!r})
from jobs import Jobs
jobs = Jobs({str(self.path)!r}, clock=lambda: datetime.fromisoformat('2026-10-30T10:00:00+08:00'))
with (jobs.storage / 'runtime/agent.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    print(json.dumps(jobs.dispatch()))
''')
        env = {k: v for k, v in os.environ.items() if not k.startswith('VQCC_')}
        return subprocess.Popen([sys.executable, str(script)], cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_model_configuration_and_durable_run_evidence(self):
        self.write_fake()
        job = self.enqueue(model='fake-selected', reasoning='high', service_tier='priority')
        process = self.driver()
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        recorded = self.jobs.snapshot()['jobs'][job['job_id']]
        self.assertEqual(recorded['state'], 'completed')
        self.assertEqual(self.jobs.usage()['started'], 1)
        argv = json.loads((self.storage / 'model-input.json').read_text())['argv']
        self.assertEqual(argv[argv.index('--model') + 1], 'fake-selected')
        self.assertIn('model_reasoning_effort="high"', argv)
        self.assertIn('service_tier="priority"', argv)
        run = self.storage / 'runs' / recorded['run_id']
        events = [json.loads(line) for line in (run / 'timeline.jsonl').read_text().splitlines()]
        self.assertEqual(events[-1]['type'], 'run.finished')
        self.assertTrue(any(event['type'] == 'resource.sample' for event in events))
        self.assertEqual(json.loads((run / 'result.json').read_text())['job_id'], job['job_id'])

    def test_optimization_receives_persistent_top3_workflow_within_one_model_job(self):
        self.write_fake()
        job = self.enqueue(kind='optimize', task='invsqrt')
        process = self.driver()
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        recorded = self.jobs.snapshot()['jobs'][job['job_id']]
        context = json.loads((self.storage / 'runs' / recorded['run_id'] / 'context.json').read_text())
        self.assertEqual(context['optimization_strategy'], 'top3_independent_then_combined')
        self.assertEqual(context['optimization_parents_per_task'], 3)
        self.assertEqual(context['search_progress'], str(self.storage / 'research/top3.json'))
        self.assertEqual(context['search_plan_command'][-3:], ['plan', '--task', 'invsqrt'])
        self.assertIn(sys.executable, context['search_plan_command'])
        self.assertEqual(self.jobs.usage()['started'], 1)
        self.assertFalse((self.storage / 'research/top3.json').exists())

    def test_stop_exact_running_job_retains_budget(self):
        self.write_fake(sleep=True)
        job = self.enqueue()
        process = self.driver()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                running = self.jobs.snapshot()['jobs'][job['job_id']]
                if running['state'] == 'running':
                    break
                time.sleep(0.03)
            self.assertEqual(running['state'], 'running')
            with self.assertRaises(ControlError):
                self.jobs.stop(job['job_id'], 'wrong-run', running['revision'], 'wrong')
            self.jobs.stop(job['job_id'], running['run_id'], running['revision'], 'stop')
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            record = self.jobs.snapshot()['jobs'][job['job_id']]
            self.assertEqual(record['state'], 'cancelled')
            self.assertEqual(record['stop_reason'], 'cancel_requested')
            self.assertEqual(self.jobs.usage()['reserved'], 1)
            self.assertFalse(self.jobs.snapshot()['scheduler']['paused'])
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=15)

    def test_local_pipeline_operation_does_not_invoke_fake_codex(self):
        self.write_fake()
        job = self.enqueue(kind='prepare_preview')
        process = self.driver()
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        record = self.jobs.snapshot()['jobs'][job['job_id']]
        # Empty fixture lacks verified candidates; the real pipeline rejects it.
        self.assertEqual(record['state'], 'failed')
        self.assertFalse((self.storage / 'model-input.json').exists())
        self.assertEqual(self.jobs.usage()['reserved'], 0)
        result = json.loads((self.storage / 'runs' / record['run_id'] / 'result.json').read_text())
        self.assertNotEqual(result['exit_code'], 0)
        report = (self.storage / 'runs' / record['run_id'] / 'report.md').read_text()
        self.assertIn('本地操作失败', report)
        self.assertIn('All three verified task baselines are required', report)



class AfterOptimizationTests(unittest.TestCase):
    request = QueueTests.request
    enqueue = QueueTests.enqueue

    def setUp(self):
        QueueTests.setUp(self)
        self.cfg.update(submission_policy='after_optimization', max_daily_submissions=5,
                        submission_quota_timezone='UTC', submission_quota_basis='attempts')
        atomic_json(self.path, self.cfg)
        self.jobs = Jobs(self.path, clock=lambda: self.now)
        self.pipeline = {'best': {}, 'submissions': {}, 'last_submitted_costs': {task: 100 for task in ('dqi', 'invsqrt', 'dfthcsos')}}
        for task in self.pipeline['last_submitted_costs']:
            cid = 'new-' + task
            self.pipeline['best'][task] = cid
            directory = self.storage / 'experiments' / cid
            atomic_json(directory / 'candidate.json', {'id': cid, 'task': task, 'verification': {'report': 'official.json'}})
            atomic_json(directory / 'official.json', {'score': 90})
        self.save_pipeline()

    def save_pipeline(self):
        atomic_json(self.storage / 'state/pipeline.json', self.pipeline)

    def complete_optimization(self, key='opt'):
        self.enqueue(key=key, kind='optimize')
        job = self.jobs.claim()
        self.jobs.finished(job['job_id'], {'status': 'completed', 'finished_at': self.now.isoformat()})
        return job

    def test_completed_optimization_queues_one_submit_before_next_optimization(self):
        first = self.enqueue(key='first', kind='optimize')
        running = self.jobs.claim()
        self.enqueue(key='second', kind='optimize')
        self.jobs.finished(running['job_id'], {'status': 'completed', 'finished_at': self.now.isoformat()})
        self.jobs.enqueue_completed_optimizations()
        submits = [job for job in self.jobs.snapshot()['jobs'].values() if job['kind'] == 'submit']
        self.assertEqual(len(submits), 1)
        self.assertEqual(submits[0]['trigger_job_id'], first['job_id'])
        self.assertEqual(submits[0]['trigger_run_id'], running['run_id'])
        self.assertEqual(self.jobs.claim()['kind'], 'submit')
        self.assertEqual(self.jobs.usage()['limit'], 6)

    def test_no_improvement_skips_followup_without_model_attempt(self):
        self.pipeline['last_submitted_costs'] = {task: 90 for task in self.pipeline['best']}
        self.save_pipeline()
        job = self.complete_optimization()
        state = self.jobs.snapshot()
        self.assertEqual(len(state['jobs']), 1)
        self.assertEqual(state['optimization_followups'][job['job_id']]['reason'], 'NO_IMPROVEMENT')
        self.assertEqual(self.jobs.usage()['reserved'], 1)

    def test_pause_defers_followup_until_resume(self):
        self.enqueue(kind='optimize')
        job = self.jobs.claim()
        self.jobs.scheduler('pause', 'pause')
        self.jobs.finished(job['job_id'], {'status': 'completed', 'finished_at': self.now.isoformat()})
        self.assertEqual(len(self.jobs.snapshot()['jobs']), 1)
        self.jobs.scheduler('resume', 'resume')
        self.jobs.enqueue_completed_optimizations()
        self.assertEqual(len(self.jobs.snapshot()['jobs']), 2)

    def test_latest_legacy_completed_optimization_imported_once(self):
        for number in (1, 2):
            atomic_json(self.storage / 'runtime/slots' / f'legacy-{number}.json',
                        {'mode': 'optimize', 'status': 'completed', 'run_dir': f'/old/runs/legacy-{number}',
                         'finished_at': f'2026-10-30T09:0{number}:00+08:00'})
        self.jobs.enqueue_completed_optimizations()
        self.jobs.enqueue_completed_optimizations()
        state = self.jobs.snapshot()
        self.assertEqual(len(state['jobs']), 1)
        submit = next(iter(state['jobs'].values()))
        self.assertEqual(submit['trigger_run_id'], 'legacy-2')
        self.assertEqual(len(state['optimization_followups']), 1)

    def test_submit_and_manual_reconcile_have_no_fixed_window_or_protection(self):
        for stamp in ('2026-10-30T09:00:00+08:00', '2026-10-30T19:50:00+08:00', '2026-10-30T23:00:00+08:00'):
            self.now = datetime.fromisoformat(stamp)
            for kind in ('submit', 'reconcile', 'smoke'):
                self.assertIsNone(self.jobs.preview(self.request(kind=kind))['blocked_reason'])
        self.now = datetime.fromisoformat('2027-01-21T07:58:59+08:00')
        self.assertEqual(self.jobs.preview(self.request(kind='submit'))['blocked_reason'], 'DEADLINE')

    def test_five_attempts_block_a_sixth_without_model_reservation(self):
        for index in range(5):
            self.pipeline['submissions'][str(index)] = {'date': '2026-10-30', 'quota_date': '2026-10-30', 'quota_timezone': 'UTC',
                                                       'status': 'submitted', 'submission_id': index + 1, 'selected': {}}
        self.save_pipeline()
        self.assertEqual(self.jobs.submission_precheck(), 'DAILY_SUBMISSION_LIMIT_REACHED')
        job = self.enqueue(kind='submit')
        self.assertIsNone(self.jobs.claim())
        self.assertEqual(self.jobs.snapshot()['jobs'][job['job_id']]['state'], 'blocked')
        self.assertEqual(self.jobs.usage()['reserved'], 0)

    def test_attempted_same_candidate_is_cancelled_without_reupload(self):
        self.pipeline['submissions']['prior'] = {'date': '2026-10-29', 'status': 'rejected', 'selected': dict(self.pipeline['best'])}
        self.save_pipeline()
        job = self.enqueue(kind='submit')
        self.assertIsNone(self.jobs.claim())
        self.assertEqual(self.jobs.snapshot()['jobs'][job['job_id']]['state'], 'cancelled')
        self.assertEqual(self.jobs.usage()['reserved'], 0)

    def test_quota_blocked_best_survives_midnight_and_runs_first_after_reset(self):
        for index in range(5):
            self.pipeline['submissions'][str(index)] = {
                'quota_date': '2026-10-30', 'quota_timezone': 'UTC',
                'status': 'submitted', 'submission_id': index + 1, 'selected': {}}
        self.save_pipeline()
        self.complete_optimization()
        pending = next(j for j in self.jobs.snapshot()['jobs'].values() if j['kind'] == 'submit')
        for stamp in ('2026-10-31T00:00:00+08:00', '2026-10-31T07:59:59+08:00'):
            self.now = datetime.fromisoformat(stamp)
            self.assertIsNone(self.jobs.claim())
            self.assertEqual(self.jobs.usage()['reserved'], 0)
        # Later improvements replace the best; the pending request does not freeze an old ZIP.
        directory = self.storage / 'experiments' / 'better-dqi'
        atomic_json(directory / 'candidate.json', {'verification': {'report': 'official.json'}})
        atomic_json(directory / 'official.json', {'score': 80})
        self.pipeline['best']['dqi'] = 'better-dqi'
        self.save_pipeline()
        self.enqueue(key='next-opt', kind='optimize')
        self.now = datetime.fromisoformat('2026-10-31T08:00:00+08:00')
        self.jobs = Jobs(self.path, clock=lambda: self.now)
        self.jobs.enqueue_completed_optimizations()
        claimed = self.jobs.claim()
        self.assertEqual(claimed['job_id'], pending['job_id'])
        self.assertEqual(self.jobs._pipeline_state()['best']['dqi'], 'better-dqi')
        self.assertEqual(self.jobs.usage()['reserved'], 1)
        self.assertEqual(sum(j['kind'] == 'submit' for j in self.jobs.snapshot()['jobs'].values()), 1)

    def test_finished_remote_quota_skip_is_rechecked_next_day_without_new_optimization(self):
        self.complete_optimization()
        submitted = self.jobs.claim()
        # Remote quota may include manual submissions absent from the local ledger.
        self.jobs.finished(submitted['job_id'], {'status': 'completed', 'finished_at': self.now.isoformat()})
        self.now = datetime.fromisoformat('2026-10-31T07:59:59+08:00')
        self.jobs.enqueue_completed_optimizations()
        self.assertEqual(sum(j['kind'] == 'submit' for j in self.jobs.snapshot()['jobs'].values()), 1)
        self.now = datetime.fromisoformat('2026-10-31T08:00:00+08:00')
        self.enqueue(key='next-opt', kind='optimize')
        self.jobs.enqueue_completed_optimizations()
        self.jobs = Jobs(self.path, clock=lambda: self.now)
        self.jobs.enqueue_completed_optimizations()
        submits = [j for j in self.jobs.snapshot()['jobs'].values() if j['kind'] == 'submit']
        self.assertEqual(len(submits), 2)
        claimed = self.jobs.claim()
        self.assertEqual(claimed['kind'], 'submit')
        self.assertEqual(claimed['slot_id'], '2026-10-31-submit-carryover')
        # A remote rejection must not cause a same-day retry loop.
        self.jobs.finished(claimed['job_id'], {'status': 'completed', 'finished_at': self.now.isoformat()})
        self.jobs.enqueue_completed_optimizations()
        self.assertEqual(sum(j['kind'] == 'submit' for j in self.jobs.snapshot()['jobs'].values()), 2)

    def test_carryover_respects_pause_and_does_not_resubmit_attempted_best(self):
        self.complete_optimization()
        submitted = self.jobs.claim()
        self.jobs.finished(submitted['job_id'], {'status': 'completed', 'finished_at': self.now.isoformat()})
        self.now = datetime.fromisoformat('2026-10-31T08:00:00+08:00')
        self.jobs.scheduler('pause', 'pause-rollover')
        self.jobs.enqueue_completed_optimizations()
        self.assertEqual(sum(j['kind'] == 'submit' for j in self.jobs.snapshot()['jobs'].values()), 1)
        self.jobs.scheduler('resume', 'resume-rollover')
        self.pipeline['submissions']['accepted'] = {
            'date': '2026-10-30', 'status': 'submitted', 'submission_id': 99,
            'selected': dict(self.pipeline['best'])}
        self.save_pipeline()
        self.jobs.enqueue_completed_optimizations()
        self.assertEqual(sum(j['kind'] == 'submit' for j in self.jobs.snapshot()['jobs'].values()), 1)

    def test_pending_submit_no_longer_improves_is_cancelled(self):
        self.complete_optimization()
        self.pipeline['last_submitted_costs'] = {task: 90 for task in self.pipeline['best']}
        self.save_pipeline()
        self.assertIsNone(self.jobs.claim())
        submit = next(job for job in self.jobs.snapshot()['jobs'].values() if job['kind'] == 'submit')
        self.assertEqual(submit['state'], 'cancelled')
        self.assertEqual(submit['blocked_reason'], 'NO_IMPROVEMENT')
        self.assertEqual(self.jobs.usage()['reserved'], 1)

    def test_unknown_upload_enqueues_one_query_and_never_another_upload(self):
        self.complete_optimization()
        submit = self.jobs.claim()
        self.pipeline['submissions']['uncertain'] = {'date': '2026-10-30', 'status': 'upload_started', 'selected': dict(self.pipeline['best'])}
        self.save_pipeline()
        self.jobs.finished(submit['job_id'], {'status': 'failed', 'finished_at': self.now.isoformat()})
        self.jobs.enqueue_completed_optimizations()
        queries = [job for job in self.jobs.snapshot()['jobs'].values() if job['kind'] == 'reconcile']
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]['trigger_job_id'], submit['job_id'])
        self.assertEqual(self.jobs.submission_precheck(), 'SUBMISSION_NEEDS_RECONCILIATION')
        query = self.jobs.claim()
        self.assertEqual(query['kind'], 'reconcile')
        # An inconclusive query is still the one automatic followup for this upload.
        self.jobs.finished(query['job_id'], {'status': 'completed', 'finished_at': self.now.isoformat()})
        self.jobs = Jobs(self.path, clock=lambda: self.now)
        for _ in range(3):
            self.jobs.enqueue_completed_optimizations()
        state = self.jobs.snapshot()
        self.assertEqual(sum(job['kind'] == 'reconcile' for job in state['jobs'].values()), 1)
        self.assertEqual(state['reconciliation_followups']['uncertain']['job_id'], query['job_id'])
        self.assertEqual(self.jobs.usage()['reserved'], 3)
        self.assertEqual(self.jobs.submission_precheck(), 'SUBMISSION_NEEDS_RECONCILIATION')

    def test_each_failed_upload_gets_a_query_but_grading_failures_do_not(self):
        self.pipeline['submissions'].update({
            'interrupted': {'status': 'upload_started'},
            'upload-rejected': {'status': 'rejected'},
            'grading-rejected': {'status': 'rejected', 'submission_id': 91},
            'accepted': {'status': 'score_unknown', 'submission_id': 92},
            'preview': {'status': 'prepared'},
        })
        self.save_pipeline()
        self.jobs.enqueue_completed_optimizations()
        self.jobs.enqueue_completed_optimizations()
        state = self.jobs.snapshot()
        followups = state['reconciliation_followups']
        self.assertEqual(set(followups), {'interrupted', 'upload-rejected'})
        self.assertEqual(len({item['job_id'] for item in followups.values()}), 2)
        for token, followup in followups.items():
            job = state['jobs'][followup['job_id']]
            self.assertEqual(job['kind'], 'reconcile')
            self.assertEqual(job['origin'], 'automatic')
            self.assertIn(token, job['hypothesis'])
        self.assertEqual(len(state['jobs']), 2)
        self.assertEqual(self.jobs.usage()['reserved'], 0)

    def test_new_upload_failure_does_not_reuse_an_already_running_query(self):
        existing = self.enqueue(key='existing-query', kind='reconcile')
        started = self.jobs.claim()
        class Fake:
            pid = os.getpid()
        self.jobs.spawn(existing['job_id'], started['run_id'], Fake)
        self.pipeline['submissions']['new-failure'] = {'status': 'upload_started'}
        self.save_pipeline()
        self.jobs.enqueue_completed_optimizations()
        state = self.jobs.snapshot()
        followup = state['reconciliation_followups']['new-failure']['job_id']
        self.assertNotEqual(followup, existing['job_id'])
        self.assertEqual(state['jobs'][existing['job_id']]['state'], 'running')
        self.assertEqual(state['jobs'][followup]['state'], 'queued')
        self.assertIsNone(self.jobs.claim())

    def test_upload_followup_recovers_enqueued_query_after_crash_and_config_change(self):
        self.pipeline['submissions']['interrupted'] = {'status': 'upload_started'}
        self.save_pipeline()
        self.jobs.enqueue_completed_optimizations()
        with self.jobs.transaction() as state:
            query_id = state.pop('reconciliation_followups')['interrupted']['job_id']
        self.jobs.save_config({'max_agent_seconds': 900}, 1, 'shorten')
        self.jobs.activate_config(2, 2, 'activate-shorter')
        self.jobs = Jobs(self.path, clock=lambda: self.now)
        self.jobs.enqueue_completed_optimizations()
        state = self.jobs.snapshot()
        self.assertEqual(state['reconciliation_followups']['interrupted']['job_id'], query_id)
        self.assertEqual(len(state['jobs']), 1)

    def test_upload_followup_waits_for_resume_and_model_budget(self):
        self.pipeline['submissions']['interrupted'] = {'status': 'upload_started'}
        self.save_pipeline()
        self.jobs.scheduler('pause', 'pause-upload-followup')
        self.jobs.enqueue_completed_optimizations()
        self.assertEqual(len(self.jobs.snapshot()['jobs']), 0)
        with self.jobs.transaction() as state:
            for index in range(6):
                state['reservations']['used-' + str(index)] = {
                    'budget_date': '2026-10-30', 'kind': 'optimize', 'started_at': 'yes'}
        self.jobs.scheduler('resume', 'resume-upload-followup')
        self.jobs.enqueue_completed_optimizations()
        query = next(iter(self.jobs.snapshot()['jobs'].values()))
        self.assertEqual(query['kind'], 'reconcile')
        self.assertEqual(query['blocked_reason'], 'DAILY_MODEL_BUDGET_EXHAUSTED')
        self.assertIsNone(self.jobs.claim())
        self.now = datetime.fromisoformat('2026-10-31T00:00:01+08:00')
        self.jobs.enqueue_completed_optimizations()
        self.assertEqual(self.jobs.claim()['job_id'], query['job_id'])
        self.assertEqual(len(self.jobs.snapshot()['jobs']), 1)

    def test_followup_preserves_existing_model_budget_limit(self):
        with self.jobs.transaction() as state:
            for index in range(6):
                state['reservations']['used-' + str(index)] = {'budget_date': '2026-10-30', 'kind': 'optimize', 'started_at': 'yes'}
        atomic_json(self.storage / 'runtime/slots/completed.json', {'mode': 'optimize', 'status': 'completed',
                    'run_dir': '/old/runs/completed', 'finished_at': '2026-10-30T09:00:00+08:00'})
        self.jobs.enqueue_completed_optimizations()
        self.assertIsNone(self.jobs.claim())
        submit = next(iter(self.jobs.snapshot()['jobs'].values()))
        self.assertEqual(submit['blocked_reason'], 'DAILY_MODEL_BUDGET_EXHAUSTED')
        self.assertEqual(self.jobs.usage()['reserved'], 6)


class DailyWindowsTests(unittest.TestCase):
    request = QueueTests.request
    enqueue = QueueTests.enqueue
    save_pipeline = AfterOptimizationTests.save_pipeline
    complete_optimization = AfterOptimizationTests.complete_optimization

    def setUp(self):
        AfterOptimizationTests.setUp(self)
        self.cfg.update(submission_policy='daily_windows', daily_submission_times=['08:00', '20:00'],
                        max_daily_submissions=2)
        atomic_json(self.path, self.cfg)
        self.jobs = Jobs(self.path, clock=lambda: self.now)

    def test_submit_only_runs_in_either_window_and_reconcile_remains_available(self):
        for hour in ('07:59', '08:45', '19:59', '20:45'):
            self.now = datetime.fromisoformat(f'2026-10-30T{hour}:00+08:00')
            self.assertEqual(self.jobs.preview(self.request(kind='submit'))['blocked_reason'], 'SUBMISSION_WINDOW')
            self.assertIsNone(self.jobs.preview(self.request(kind='reconcile'))['blocked_reason'])
        for hour in ('08:00', '08:44', '20:00', '20:44'):
            self.now = datetime.fromisoformat(f'2026-10-30T{hour}:00+08:00')
            self.assertIsNone(self.jobs.preview(self.request(kind='submit'))['blocked_reason'])

    def test_work_cannot_overlap_either_window_or_daily_reconciliation(self):
        for hour in ('07:25', '08:30', '19:25', '20:46', '21:14'):
            self.now = datetime.fromisoformat(f'2026-10-30T{hour}:00+08:00')
            self.assertEqual(self.jobs.preview(self.request())['blocked_reason'], 'PROTECTED_WINDOW')
        for hour in ('07:24', '08:45', '09:10', '21:16'):
            self.now = datetime.fromisoformat(f'2026-10-30T{hour}:00+08:00')
            self.assertIsNone(self.jobs.preview(self.request())['blocked_reason'])
        self.now = datetime.fromisoformat('2026-10-30T06:10:00+08:00')
        self.assertEqual(self.jobs.preview(self.request(kind='optimize', max_seconds=7200))['blocked_reason'], 'PROTECTED_WINDOW')

    def test_overnight_work_respects_tomorrows_window(self):
        self.jobs.base['daily_submission_times'] = ['00:30', '20:00']
        self.now = datetime.fromisoformat('2026-10-30T23:20:00+08:00')
        self.assertEqual(self.jobs.preview(self.request(max_seconds=2400))['blocked_reason'], 'PROTECTED_WINDOW')

    def test_morning_optimization_finishes_at_protection_boundary(self):
        self.now = datetime.fromisoformat('2026-10-30T06:10:00+08:00')
        self.jobs.enqueue_slot(('2026-10-30-optimize-0610', 'optimize', 4500))
        job = self.jobs.claim()
        self.assertEqual(job['kind'], 'optimize')
        self.assertEqual(job['max_seconds'], 4490)

    def test_morning_attempt_blocks_another_until_evening(self):
        self.pipeline['submissions']['morning'] = {
            'date': '2026-10-30', 'reserved_at': '2026-10-30T08:10:00+08:00',
            'quota_date': '2026-10-30', 'quota_timezone': 'UTC',
            'status': 'submitted', 'submission_id': 101, 'selected': {}}
        self.save_pipeline()
        self.now = datetime.fromisoformat('2026-10-30T08:15:00+08:00')
        pending = self.enqueue(kind='submit')
        self.assertIsNone(self.jobs.claim())
        self.assertEqual(self.jobs.snapshot()['jobs'][pending['job_id']]['blocked_reason'], 'ALREADY_ATTEMPTED_WINDOW')
        self.assertEqual(self.jobs.usage()['reserved'], 0)
        self.now = datetime.fromisoformat('2026-10-30T20:00:00+08:00')
        self.assertEqual(self.jobs.claim()['job_id'], pending['job_id'])

    def test_optimization_waits_for_scheduled_slot_and_best_carries_over(self):
        self.complete_optimization()
        self.jobs.enqueue_completed_optimizations()
        self.assertEqual(len(self.jobs.snapshot()['jobs']), 1)
        self.now = datetime.fromisoformat('2026-10-31T08:00:00+08:00')
        self.jobs.enqueue_completed_optimizations()
        self.assertEqual(len(self.jobs.snapshot()['jobs']), 1)
        self.jobs.enqueue_slot(('2026-10-31-submit-0800', 'submit', 1800))
        self.jobs.enqueue_slot(('2026-10-31-submit-0800', 'submit', 1800))
        self.assertEqual(self.jobs.claim()['kind'], 'submit')
        self.assertEqual(len(self.jobs.snapshot()['jobs']), 2)

    def test_queued_previous_policy_submit_waits_until_next_window(self):
        self.jobs.base['submission_policy'] = 'after_optimization'
        self.complete_optimization()
        pending = next(j for j in self.jobs.snapshot()['jobs'].values() if j['kind'] == 'submit')
        self.jobs = Jobs(self.path, clock=lambda: self.now)
        self.assertIsNone(self.jobs.claim())
        self.assertEqual(self.jobs.snapshot()['jobs'][pending['job_id']]['blocked_reason'], 'SUBMISSION_WINDOW')
        self.now = datetime.fromisoformat('2026-10-30T20:00:00+08:00')
        self.assertEqual(self.jobs.claim()['job_id'], pending['job_id'])

    def test_stale_submit_is_cancelled_without_using_model_budget(self):
        self.pipeline['last_submitted_costs'] = {task: 90 for task in self.pipeline['best']}
        self.save_pipeline()
        job = self.enqueue(kind='submit')
        self.assertIsNone(self.jobs.claim())
        self.assertEqual(self.jobs.snapshot()['jobs'][job['job_id']]['state'], 'cancelled')
        self.assertEqual(self.jobs.usage()['reserved'], 0)

    def test_two_windows_are_visible_in_deployment_projection(self):
        deployment = self.jobs.config()['deployment']
        self.assertEqual(deployment['daily_submission_times'], ['08:00', '20:00'])
        self.assertEqual(deployment['max_daily_submissions'], 2)

    def test_success_limit_ignores_failed_attempts_and_blocks_third_success(self):
        self.jobs.base.update(max_daily_submissions=3, submission_quota_basis='successful_submissions')
        self.now = datetime.fromisoformat('2026-10-30T20:00:00+08:00')
        for index, sid in enumerate((101, 102, None, None)):
            self.pipeline['submissions'][str(index)] = {
                'status': 'score_unknown' if sid else 'not_submitted', 'submission_id': sid,
                'reserved_at': '2026-10-30T12:00:00+08:00', 'selected': {}}
        self.save_pipeline()
        self.assertIsNone(self.jobs.preview(self.request(kind='submit'))['blocked_reason'])
        self.pipeline['submissions']['third'] = {
            'status': 'score_unknown', 'submission_id': 103,
            'reserved_at': '2026-10-30T13:00:00+08:00', 'selected': {}}
        self.save_pipeline()
        self.assertEqual(self.jobs.preview(self.request(kind='submit'))['blocked_reason'],
                         'DAILY_SUBMISSION_LIMIT_REACHED')
        self.assertEqual(self.jobs.config()['deployment']['submission_quota_basis'], 'successful_submissions')

    test_attempted_same_candidate_is_cancelled_without_reupload = AfterOptimizationTests.test_attempted_same_candidate_is_cancelled_without_reupload
    test_each_failed_upload_gets_a_query_but_grading_failures_do_not = AfterOptimizationTests.test_each_failed_upload_gets_a_query_but_grading_failures_do_not
    test_new_upload_failure_does_not_reuse_an_already_running_query = AfterOptimizationTests.test_new_upload_failure_does_not_reuse_an_already_running_query
    test_upload_followup_recovers_enqueued_query_after_crash_and_config_change = AfterOptimizationTests.test_upload_followup_recovers_enqueued_query_after_crash_and_config_change
    test_upload_followup_waits_for_resume_and_model_budget = AfterOptimizationTests.test_upload_followup_waits_for_resume_and_model_budget



class DeployedScheduleTests(unittest.TestCase):
    """A simulated day on the deployed config: every relay slot is dispatchable."""

    def test_day_of_relay_slots_never_hits_protection(self):
        from runner import select_slot
        deployed = json.loads((ROOT / 'automation/config.json').read_text())
        tmp = tempfile.TemporaryDirectory(prefix='vqcc-day-')
        self.addCleanup(tmp.cleanup)
        storage = Path(tmp.name)
        (storage / 'runtime').mkdir()
        path = storage / 'config.json'
        atomic_json(path, {**deployed, 'storage_root': str(storage), 'min_free_gib': 0, 'model': 'fake-model',
                           'python_executable': sys.executable})
        clock = {'now': datetime.fromisoformat('2026-11-04T00:00:00+08:00')}
        jobs = Jobs(path, initialize=True, clock=lambda: clock['now'])
        kinds = []
        while clock['now'] < datetime.fromisoformat('2026-11-05T00:00:00+08:00'):
            taken = lambda slot_id: (storage / 'runtime/slots' / (slot_id + '.json')).exists()
            slot = select_slot(jobs.base, clock['now'], taken)
            jobs.enqueue_slot(slot)
            state = jobs.snapshot()
            for job in [j for j in state['jobs'].values() if j['state'] in {'queued', 'blocked'}]:
                self.assertIsNone(jobs._window_reason(job, state), (clock['now'], job['slot_id']))
                kinds.append((job['kind'], job['slot_id']))
                # The run "finishes" immediately; the next period relays.
                jobs.cancel(job['job_id'], job['state'], job['revision'], 'simulated-' + job['job_id'])
            clock['now'] += timedelta(minutes=10)
        self.assertEqual([slot for kind, slot in kinds if kind == 'submit'], ['2026-11-04-submit-2340'])
        self.assertEqual([slot for kind, slot in kinds if kind == 'reconcile'], ['2026-11-04-reconcile'])
        optimize = [slot for kind, slot in kinds if kind == 'optimize']
        self.assertEqual(len(optimize), 23)  # every hour except 07:00 (upload); 09:00 starts after reconciliation
        self.assertNotIn('2026-11-04-optimize-0700', optimize)


if __name__ == '__main__':
    unittest.main()
