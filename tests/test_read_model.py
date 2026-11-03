"""Read projections use temporary evidence, never live scientific validators."""
from datetime import datetime, timedelta
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from web.backend.artifacts import ArtifactRegistry
from web.backend.read_model import ReadModel

ROOT = Path(__file__).resolve().parents[1]


class ReadModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = json.loads((ROOT / "automation/config.json").read_text())
        self.cfg["storage_root"] = str(self.root)
        for key in ("submission_policy", "max_daily_submissions", "submission_quota_timezone", "submission_quota_basis"):
            self.cfg.pop(key, None)
        self.config = self.root / "config.json"
        self.write(self.config, self.cfg)
        self.model = ReadModel(self.config)
        self.model.now = lambda: datetime.fromisoformat("2026-10-30T20:05:00+08:00")
        self.state = {"best": {"dqi": "one-dqi", "invsqrt": "one-invsqrt", "dfthcsos": "one-dfthcsos"},
                      "baseline_costs": {"dqi": 100, "invsqrt": 100, "dfthcsos": 100},
                      "last_submitted_costs": {"dqi": 100, "invsqrt": 100, "dfthcsos": 100},
                      "submissions": {"yesterday": {"token": "yesterday", "submission_id": 123,
                                          "date": "2026-10-29", "status": "score_unknown"}}}
        self.write(self.root / "state/pipeline.json", self.state)
        for task in ("dqi", "invsqrt", "dfthcsos"):
            self.candidate("one-" + task, task)

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def candidate(self, cid, task="invsqrt", **fields):
        official_score = fields.pop("official_score", 90)
        official_status = fields.pop("official_status", "PASS")
        directory = self.root / "experiments" / cid
        self.write(directory / "candidate.json", {"id": cid, "task": task, "parent": None,
                     "created_at": "2026-10-29T16:00:00+08:00", "hypothesis": "test",
                     "verification": {"kind": "official", "passed": True, "report": "official.json", "runtime_fingerprint": {"python": "3.13"}, "verifiers": []}, **fields})
        self.write(directory / "generation.json", {"parameters": {"delta_bits": 12}, "official_validation": "not_run"})
        self.write(directory / "official.json", {"status": official_status, "score": official_score, "num_qubits": 50})
        return directory

    def test_candidate_evidence_overrides_generation_not_run(self):
        candidate = self.model.experiment("one-invsqrt")
        self.assertEqual(candidate["validation_status"], "PASS")
        self.assertEqual(candidate["official_cost"], 90)
        self.assertEqual(candidate["evidence_integrity"], "not_rechecked")
        self.assertEqual(candidate["generation"]["official_validation"], "not_run")

    def test_unverified_candidates_expose_recorded_preverification_state(self):
        def unverified(cid, generation=None, output_files=()):
            directory = self.candidate(cid)
            candidate = json.loads((directory / "candidate.json").read_text())
            candidate.pop("verification")
            self.write(directory / "candidate.json", candidate)
            (directory / "official.json").unlink()
            if generation is None:
                (directory / "generation.json").unlink()
            else:
                self.write(directory / "generation.json", generation)
            for name in output_files:
                path = directory / "output" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("artifact")
            return self.model.experiment(cid)

        cases = [
            ("screened", {"decision": "measured_no_gain_in_tested_scope"}, (),
             "screen_rejected", "measured_no_gain_in_tested_scope"),
            ("failed-generation", {"status": "failed", "error": "builder crashed"}, (),
             "generation_failed", "builder crashed"),
            ("stopped-search", {"status": "iteration_limit"}, (),
             "search_stopped", "iteration_limit"),
            ("ready", {"build_status": "built"}, ("invsqrt.kmb",),
             "awaiting_validation", "official_verifier_not_run"),
            ("incomplete", {"build_status": "built"}, ("notes.txt",),
             "artifact_incomplete", "output_does_not_match_the_official_artifact_layout"),
            ("analysis", {"kind": "symbolic_bound"}, (),
             "analysis_only", "symbolic_bound"),
            ("not-generated", None, (),
             "not_generated", "no_generation_or_verification_record"),
        ]
        for cid, generation, files, expected_status, expected_reason in cases:
            with self.subTest(cid=cid):
                result = unverified(cid, generation, files)
                self.assertEqual(result["validation_status"], expected_status)
                self.assertEqual(result["validation_reason"], expected_reason)

        filtered = self.model.experiments(validation="screen_rejected")
        self.assertEqual([item["id"] for item in filtered["items"]], ["screened"])

    def test_unknown_score_and_today_quota_are_separate(self):
        submission = self.model.submissions()
        self.assertIsNone(submission["items"][0]["platform_score"])
        self.assertFalse(submission["eligibility"]["today_used"])
        self.assertTrue(submission["eligibility"]["eligible"])
        self.assertAlmostEqual(submission["combined_improvement"], 100 / 90)
        self.assertIsNone(self.model.overview()["platform_score"])

    def test_task_history_separates_pass_scores_from_promotions(self):
        verification = {"kind": "official", "passed": True, "report": "official.json",
                        "finished_at": "2026-10-29T17:00:00+08:00"}
        self.candidate("promoted-a", "invsqrt", official_score=80,
                       created_at="2026-10-29T16:30:00+08:00",
                       promoted_at="2026-10-29T17:05:00+08:00", verification=verification)
        verification = {**verification, "finished_at": "2026-10-29T18:00:00+08:00"}
        self.candidate("pass-only", "invsqrt", official_score=70,
                       created_at="2026-10-29T17:30:00+08:00", verification=verification)
        verification = {**verification, "finished_at": "2026-10-29T19:00:00+08:00"}
        self.candidate("promoted-b", "invsqrt", official_score=60,
                       created_at="2026-10-29T18:30:00+08:00",
                       promoted_at="2026-10-29T19:05:00+08:00", verification=verification)
        self.candidate("failed", "invsqrt", official_score=50, official_status="FAIL")
        stale = self.candidate("stale", "invsqrt", official_score=40)
        record = json.loads((stale / "candidate.json").read_text())
        record["verification"]["report_sha256"] = "not-the-current-report"
        self.write(stale / "candidate.json", record)
        self.state["best"]["invsqrt"] = "promoted-b"
        self.write(self.root / "state/pipeline.json", self.state)

        result = self.model.task_history("invsqrt")["items"][0]
        self.assertEqual(result["pass_count"], 4)
        self.assertEqual(result["improvement_count"], 2)
        self.assertEqual([item["candidate_id"] for item in result["score_history"]],
                         ["one-invsqrt", "promoted-a", "pass-only", "promoted-b"])
        self.assertEqual(result["score_history"][0]["recorded_at"],
                         "2026-10-29T16:00:00+08:00")
        self.assertEqual([item["candidate_id"] for item in result["improvement_history"]],
                         ["promoted-a", "promoted-b"])
        first, second = result["improvement_history"]
        self.assertAlmostEqual(first["step_reduction"], .2)
        self.assertAlmostEqual(second["step_reduction"], .25)
        self.assertAlmostEqual(second["baseline_reduction"], .4)
        self.assertAlmostEqual(second["baseline_factor"], 100 / 60)
        self.assertTrue(second["is_current_best"])
        self.assertNotIn("failed", {item["candidate_id"] for item in result["score_history"]})
        self.assertNotIn("stale", {item["candidate_id"] for item in result["score_history"]})

    def test_kaggle_score_history_keeps_last_known_score_when_newer_is_unknown(self):
        self.state["submissions"]["yesterday"].update(
            status="scored", public_score=2.0, updated_at="2026-10-29T17:00:00+08:00",
            receipt={"date": "2026-10-29T08:00:00Z"})
        self.state["submissions"]["scored"] = {
            "token": "scored", "submission_id": 456, "status": "scored",
            "date": "2026-10-30", "public_score": 3.0,
            "updated_at": "2026-10-30T17:00:00+08:00",
            "receipt": {"date": "2026-10-30T08:00:00Z"}}
        self.state["submissions"]["newer-unknown"] = {
            "token": "newer-unknown", "submission_id": 789, "status": "score_unknown",
            "date": "2026-10-30", "created_at": "2026-10-30T20:00:00+08:00"}
        self.write(self.root / "state/pipeline.json", self.state)

        scores = self.model.submissions()["score_history"]
        self.assertEqual([item["submission_id"] for item in scores], [123, 456])
        self.assertEqual(scores[-1]["previous_score"], 2.0)
        self.assertEqual(scores[-1]["absolute_change"], 1.0)
        self.assertEqual(scores[-1]["relative_change"], .5)
        overview = self.model.overview()
        self.assertEqual(overview["platform_score"], 3.0)
        self.assertEqual(overview["platform_score_submission_id"], 456)
        self.assertEqual(overview["platform_score_at"], "2026-10-30T08:00:00Z")

    def test_completed_submit_surfaces_report_without_claiming_upload(self):
        self.after_optimization()
        job = {'job_id': 'submit-job', 'kind': 'submit', 'state': 'completed', 'run_id': 'submit-run',
               'created_at': '2026-10-30T06:22:00+08:00', 'started_at': '2026-10-30T06:22:00+08:00',
               'finished_at': '2026-10-30T06:25:00+08:00'}
        self.write(self.root / 'console/state.json', {'jobs': {'submit-job': job}})
        run = self.root / 'runs/submit-run'
        run.mkdir(parents=True)
        (run / 'report.md').write_text('本轮未提交：平台历史查询认证失败。\n\n详细报告。')
        result = self.model.submissions()
        self.assertTrue(result['eligibility']['eligible'])
        self.assertEqual(result['activity']['code'], 'no_upload_recorded')
        self.assertIn('认证失败', result['activity']['report_excerpt'])
        self.assertEqual(result['activity']['job_id'], 'submit-job')
        self.assertIsNotNone(result['activity']['report']['id'])
        job['state'] = 'blocked'
        job['blocked_reason'] = 'DAILY_MODEL_BUDGET_EXHAUSTED'
        self.write(self.root / 'console/state.json', {'jobs': {'submit-job': job}})
        self.assertEqual(self.model.submissions()['activity']['code'], 'blocked')

    def test_empty_queue_explains_consumed_window_and_reserved_budget(self):
        self.after_optimization('2026-10-30T09:55:00+08:00')
        self.write(self.root / 'console/state.json', {'slots': {
            '2026-10-30-optimize-0610': 'job-early',
            '2026-10-30-optimize-0910': 'job-done'}})
        usage = {'available': 2, 'reserve_submit': 1, 'reserve_reconcile': 1,
                 'reservations': [{'kind': 'optimize'}, {'kind': 'submit'}, {'kind': 'optimize'}, {'kind': 'submit'}]}
        scheduler = {'process_alive': True, 'paused': False, 'dispatch_enabled': True}
        result = self.model.queue_status([], scheduler, usage)
        self.assertEqual(result['next_optimization_at'], '2026-10-30T12:10:00+08:00')
        self.assertEqual(result['optimization_available'], 1)
        self.assertEqual(result['submission_available'], 1)
        self.assertIn('每个优化时段只创建一轮', result['message'])
        scheduler['paused'] = True
        self.assertIn('暂停', self.model.queue_status([], scheduler, usage)['message'])
        scheduler.update(paused=False, dispatch_enabled=False)
        self.assertIn('未运行', self.model.queue_status([], scheduler, usage)['message'])

    def test_queue_next_day_and_deadline_are_not_execution_promises(self):
        self.after_optimization('2026-10-30T23:30:00+08:00')
        scheduler = {'process_alive': True, 'paused': False}
        usage = {'available': 0, 'reserve_submit': 1, 'reserve_reconcile': 1, 'reservations': []}
        result = self.model.queue_status([], scheduler, usage)
        self.assertEqual(result['next_optimization_at'], '2026-10-31T00:10:00+08:00')
        self.assertEqual(result['optimization_available'], 0)
        self.model.config['deadline'] = '2026-10-30T23:00:00+08:00'
        result = self.model.queue_status([], scheduler, usage)
        self.assertIsNone(result['next_optimization_at'])
        self.assertIn('截止', result['message'])

    def test_previous_uncertain_upload_blocks_new_day(self):
        self.state["submissions"]["yesterday"].pop("submission_id")
        self.state["submissions"]["yesterday"]["status"] = "upload_started"
        self.write(self.root / "state/pipeline.json", self.state)
        eligibility = self.model.submissions()["eligibility"]
        self.assertFalse(eligibility["today_used"])
        self.assertFalse(eligibility["eligible"])
        self.assertFalse(next(item["passed"] for item in eligibility["checks"] if item["id"] == "reconciliation"))

    def after_optimization(self, at="2026-10-30T13:10:00+08:00"):
        self.cfg.update(submission_policy="after_optimization", max_daily_submissions=5,
                        submission_quota_timezone="UTC")
        self.model.config = self.cfg
        self.model.now = lambda: datetime.fromisoformat(at)

    def test_after_optimization_one_attempt_does_not_exhaust_daily_quota(self):
        self.after_optimization()
        self.state["submissions"]["first"] = {"token": "first", "submission_id": 456,
                "date": "2026-10-30", "reserved_at": "2026-10-30T13:05:00+08:00",
                "status": "score_unknown"}
        self.write(self.root / "state/pipeline.json", self.state)
        result = self.model.submissions()
        eligibility = result["eligibility"]
        self.assertEqual(eligibility["attempts_today"], 1)
        self.assertEqual(eligibility["remaining_today"], 4)
        self.assertEqual(eligibility["daily_limit"], 5)
        self.assertEqual(eligibility["quota_timezone"], "UTC")
        self.assertFalse(eligibility["today_used"])
        self.assertTrue(eligibility["eligible"])
        self.assertTrue(eligibility["window_open"])
        self.assertIsNone(eligibility["next_window"])
        self.assertEqual(result["items"][0]["quota_date"], "2026-10-30")
        self.assertFalse(any("用尽" in alert["message"] for alert in self.model.overview()["alerts"]))

    def test_after_optimization_five_attempts_exhaust_quota_including_rejection(self):
        self.after_optimization()
        for i in range(5):
            self.state["submissions"][f"attempt-{i}"] = {
                "submission_id": 500 + i, "date": "2026-10-30",
                "reserved_at": "2026-10-30T12:00:00+08:00", "status": "rejected"}
        self.write(self.root / "state/pipeline.json", self.state)
        eligibility = self.model.submissions()["eligibility"]
        self.assertEqual(eligibility["attempts_today"], 5)
        self.assertEqual(eligibility["remaining_today"], 0)
        self.assertTrue(eligibility["today_used"])
        self.assertFalse(eligibility["eligible"])
        self.assertTrue(any("用尽" in alert["message"] for alert in self.model.overview()["alerts"]))

    def test_successful_submissions_require_platform_id_but_not_successful_grading(self):
        self.after_optimization()
        for token, status, submission_id in (
            ("unconfirmed", "upload_started", None),
            ("missing-id", "submitted", None),
            ("pending", "score_unknown", 601),
            ("graded", "scored", 602),
            ("grading-error", "rejected", 603),
            ("preview", "prepared", None),
        ):
            self.state["submissions"][token] = {
                "status": status, "submission_id": submission_id,
                "reserved_at": "2026-10-30T12:00:00+08:00"}
        self.write(self.root / "state/pipeline.json", self.state)
        eligibility = self.model.submissions()["eligibility"]
        self.assertEqual(eligibility["successes_today"], 3)
        self.assertEqual(eligibility["attempts_today"], 5)
        self.assertEqual(eligibility["remaining_today"], 0)
        self.assertFalse(eligibility["eligible"])
        self.assertEqual(self.model.overview()["submission"]["successes_today"], 3)

    def test_confirmed_unsubmitted_upload_keeps_attempt_quota_without_blocking_new_best(self):
        self.after_optimization()
        self.state["submissions"]["upload-failed"] = {
            "status": "not_submitted", "reserved_at": "2026-10-30T12:00:00+08:00",
            "selected": {"invsqrt": "older-candidate"}}
        self.write(self.root / "state/pipeline.json", self.state)
        eligibility = self.model.submissions()["eligibility"]
        self.assertEqual(eligibility["attempts_today"], 1)
        self.assertEqual(eligibility["remaining_today"], 4)
        self.assertEqual(eligibility["successes_today"], 0)
        self.assertTrue(eligibility["eligible"])

    def test_after_optimization_utc_quota_resets_at_eight_beijing(self):
        self.after_optimization("2026-10-31T00:05:00+08:00")
        self.state["submissions"]["late"] = {"submission_id": 456, "date": "2026-10-30",
                "reserved_at": "2026-10-30T23:55:00+08:00", "status": "score_unknown"}
        self.write(self.root / "state/pipeline.json", self.state)
        midnight = self.model.submissions()["eligibility"]
        self.assertEqual(midnight["quota_date"], "2026-10-30")
        self.assertEqual(midnight["attempts_today"], 1)
        self.assertEqual(midnight["successes_today"], 1)
        self.model.now = lambda: datetime.fromisoformat("2026-10-31T07:59:59+08:00")
        self.assertEqual(self.model.submissions()["eligibility"]["attempts_today"], 1)
        self.model.now = lambda: datetime.fromisoformat("2026-10-31T08:00:00+08:00")
        reset = self.model.submissions()["eligibility"]
        self.assertEqual(reset["quota_date"], "2026-10-31")
        self.assertEqual(reset["attempts_today"], 0)
        self.assertEqual(reset["successes_today"], 0)
        self.assertEqual(reset["remaining_today"], 5)

    def test_success_quota_projection_matches_enforcement_and_excludes_failed_upload(self):
        self.after_optimization()
        self.cfg.update(max_daily_submissions=3, submission_quota_basis='successful_submissions')
        self.state['submissions'].update({
            'accepted': {'status': 'score_unknown', 'submission_id': 601,
                         'reserved_at': '2026-10-30T12:00:00+08:00'},
            'failed': {'status': 'not_submitted', 'reserved_at': '2026-10-30T12:05:00+08:00'},
        })
        self.write(self.root / 'state/pipeline.json', self.state)
        quota = self.model.submissions()['eligibility']
        self.assertEqual((quota['successes_today'], quota['attempts_today'], quota['remaining_today']), (1, 2, 2))
        self.assertEqual(quota['daily_limit'], 3)
        self.assertTrue(quota['eligible'])
        self.assertIn('成功提交', next(c['label'] for c in quota['checks'] if c['id'] == 'daily_attempt'))
        self.assertEqual(self.model.overview()['submission']['remaining_today'], 2)

    def test_after_optimization_missing_id_still_blocks_despite_remaining_quota(self):
        self.after_optimization()
        self.state["submissions"]["yesterday"].pop("submission_id")
        self.state["submissions"]["yesterday"]["status"] = "upload_started"
        self.write(self.root / "state/pipeline.json", self.state)
        eligibility = self.model.submissions()["eligibility"]
        self.assertEqual(eligibility["remaining_today"], 5)
        self.assertFalse(eligibility["eligible"])
        self.assertFalse(next(c["passed"] for c in eligibility["checks"] if c["id"] == "reconciliation"))

    def test_after_optimization_prepared_preview_can_cross_day_without_using_quota(self):
        self.after_optimization()
        self.state["submissions"]["preview"] = {"date": "2026-10-29", "status": "prepared",
                "selected": self.state["best"]}
        self.write(self.root / "state/pipeline.json", self.state)
        result = self.model.submissions()
        preview = next(item for item in result["items"] if item["status"] == "prepared")
        self.assertFalse(preview["preview_stale"])
        self.assertEqual(result["eligibility"]["attempts_today"], 0)

    def test_after_optimization_already_attempted_combination_is_not_eligible(self):
        self.after_optimization()
        self.state["submissions"]["yesterday"]["selected"] = self.state["best"]
        self.write(self.root / "state/pipeline.json", self.state)
        eligibility = self.model.submissions()["eligibility"]
        self.assertFalse(eligibility["eligible"])
        self.assertFalse(next(c["passed"] for c in eligibility["checks"] if c["id"] == "unsubmitted_combination"))

    def test_after_optimization_missing_evidence_keeps_eligibility_unknown(self):
        self.after_optimization()
        (self.root / "experiments/one-invsqrt/official.json").unlink()
        result = self.model.submissions()
        self.assertFalse(result["eligibility"]["eligible"])
        self.assertIsNone(result["combined_improvement"])

    def test_missing_policy_preserves_daily_window_compatibility(self):
        self.model.now = lambda: datetime.fromisoformat("2026-10-30T13:10:00+08:00")
        eligibility = self.model.submissions()["eligibility"]
        self.assertEqual(eligibility["policy"], "daily_window")
        self.assertEqual(eligibility["daily_limit"], 1)
        self.assertFalse(eligibility["window_open"])
        self.assertFalse(eligibility["eligible"])
        self.assertEqual(eligibility["quota_timezone"], "Asia/Shanghai")

    def test_partial_json_preserves_last_snapshot_and_marks_stale(self):
        before = self.model.pipeline()
        self.model.envelope(before)
        (self.root / "state/pipeline.json").write_text('{"best":')
        response = self.model.envelope(self.model.pipeline())
        self.assertEqual(response["data"], before)
        self.assertEqual(response["freshness"], "stale")
        self.assertEqual(response["consistency"], "partial")

    def test_missing_report_is_unknown_not_pass(self):
        (self.root / "experiments/one-invsqrt/official.json").unlink()
        result = self.model.envelope(self.model.experiment("one-invsqrt"))
        self.assertEqual(result["data"]["validation_status"], "unknown")
        self.assertIsNone(result["data"]["official_cost"])
        self.assertEqual(result["consistency"], "partial")

    def test_changed_bound_report_is_not_pass(self):
        path = self.root / "experiments/one-invsqrt"
        candidate = json.loads((path / "candidate.json").read_text())
        candidate["verification"]["report_sha256"] = hashlib.sha256((path / "official.json").read_bytes()).hexdigest()
        self.write(path / "candidate.json", candidate)
        self.assertEqual(self.model.experiment("one-invsqrt")["validation_status"], "PASS")
        self.write(path / "official.json", {"status": "PASS", "score": 1})
        result = self.model.experiment("one-invsqrt")
        self.assertEqual(result["validation_status"], "EVIDENCE_STALE")
        self.assertIsNone(result["official_cost"])

    def test_same_task_comparison_and_missing_parent(self):
        self.candidate("two-invsqrt", parent="missing-parent")
        self.write(self.root / "experiments/two-invsqrt/generation.json", {"parameters": {"delta_bits": 13}})
        comparison = self.model.compare(["one-invsqrt", "two-invsqrt"])
        self.assertEqual(comparison["parameter_differences"], ["delta_bits"])
        self.assertTrue(comparison["items"][1]["lineage"][-1]["unknown"])
        with self.assertRaises(ValueError):
            self.model.compare(["one-dqi", "one-invsqrt"])

    def test_research_id_survives_reordering_and_overrides(self):
        item = {"task": "dqi", "hypothesis": "reuse workspace", "source": "paper", "rank": 1}
        self.write(self.root / "research/hypotheses.json", {"queue": [item]})
        first = self.model.research()["items"][0]
        item["rank"] = 5
        self.write(self.root / "research/hypotheses.json", {"queue": [item]})
        self.write(self.root / "console/research.json", {"overrides": {first["id"]: {"priority": 2, "notes": "next", "status": "supported"}}})
        second = self.model.research()["items"][0]
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["notes"], "next")
        self.assertEqual(second["priority"], 2)
        self.assertEqual(second["estimate_kind"], "unmeasured_prior")

    def test_jsonl_complete_lines_incremental_replacement(self):
        path = self.root / "runs/example/timeline.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('{"event_id":"one"}\n{"event_id":')
        self.assertEqual(len(self.model._jsonl(path)), 1)
        with path.open("a") as output:
            output.write('"two"}\n')
        self.assertEqual([item["event_id"] for item in self.model._jsonl(path)], ["one", "two"])
        path.write_text('{"event_id":"three"}\n')
        self.assertEqual([item["event_id"] for item in self.model._jsonl(path)], ["three"])

    def test_completed_run_without_candidate_is_not_scientific_pass(self):
        self.write(self.root / "runs/example/result.json", {"status": "completed"})
        result = self.model.runs("example")
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["candidate_ids"], [])
        self.assertIsNone(result["model"])
        self.assertFalse(result["usage"]["complete"])

    def test_legacy_history_joins_final_result_and_deduplicates_console_runs(self):
        self.write(self.root / "runtime/slots/manual-old.json", {"slot": "manual-old", "mode": "smoke", "status": "running", "run_dir": str(self.root / "runs/old"), "pid": 99999999, "started_at": "2026-10-29T00:00:00+08:00"})
        self.write(self.root / "runs/old/result.json", {"slot": "manual-old", "mode": "smoke", "status": "completed", "started_at": "2026-10-29T00:00:00+08:00"})
        jobs = self.model.list_jobs()["items"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["state"], "completed")
        self.assertTrue(self.model.job("manual-old")["legacy"])
        self.assertIsNone(jobs[0]["model"])
        self.write(self.root / "console/state.json", {"jobs": {"job-new": {"job_id": "job-new", "run_id": "old", "state": "completed"}}})
        self.assertEqual(self.model.list_jobs()["total"], 1)
        self.assertEqual(self.model.list_jobs()["items"][0]["job_id"], "job-new")

    def test_legacy_current_without_identity_has_reachable_unknown_detail(self):
        self.write(self.root / "runtime/slots/old.json", {"slot": "old", "mode": "optimize", "status": "running", "run_dir": str(self.root / "runs/old"), "pid": 99999999, "started_at": "2026-10-29T00:00:00+08:00"})
        current = self.model.overview()["current_job"]
        self.assertEqual(current["state"], "unknown")
        self.assertEqual(self.model.job(current["job_id"])["state"], "unknown")

    def test_usage_observes_tokens_without_counting_cached_input_twice(self):
        self.write(self.root / "runs/model/result.json", {"mode": "optimize", "status": "completed", "started_at": "2026-10-30T00:05:00+08:00", "elapsed_seconds": 12})
        self.write(self.root / "runs/local/result.json", {"mode": "local_validate", "status": "completed", "started_at": "2026-10-30T01:00:00+08:00", "elapsed_seconds": 5})
        path = self.root / "runs/model/events.jsonl"
        path.write_text(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 8}}) + "\n")
        usage = self.model.usage("2026-10-30")
        self.assertEqual(usage["tokens"]["input_tokens"], 100)
        self.assertEqual(usage["tokens"]["cached_input_tokens"], 40)
        self.assertEqual(usage["model_seconds"], 12)
        self.assertEqual(usage["local_seconds"], 5)
        self.assertFalse(usage["usage_complete"])
        self.assertEqual(self.model.usage("2026-10-30")["tokens"], usage["tokens"])
        self.assertIsNone(self.model.usage("2026-10-31")["tokens"])

    def test_report_id_survives_service_restart(self):
        path = self.root / "experiments/one-invsqrt/official.json"
        item = self.model.artifacts.register(path)
        restarted = ArtifactRegistry(self.root)
        self.assertEqual(restarted.resolve(item["id"]), path)

    def test_report_registration_blocks_escape_and_redacts_urls(self):
        outside = self.root / "outside.json"
        outside.write_text('{"secret":true}')
        directory = self.root / "experiments/one-invsqrt"
        (directory / "escape.json").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.model.artifacts.register(directory / "escape.json")
        report = directory / "safe.md"
        report.write_text("https://example.test/a?token=SECRET")
        item = self.model.artifacts.register(report)
        self.assertNotIn("SECRET", self.model.artifacts.read(item["id"]))
        with self.assertRaises(ValueError):
            self.model.experiment("../state")
        with self.assertRaises(KeyError):
            self.model.artifacts.resolve("made-up")


if __name__ == "__main__":
    unittest.main()
