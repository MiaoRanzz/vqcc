"""Behavioral safety tests. Fake reports exercise bookkeeping, not scientific acceptance."""
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
import zipfile

from pipeline import Pipeline, PipelineError, artifact_manifest, check_report, improvement, positive, read_json, safe_receipt, sha256, write_json
import pipeline as pipeline_module
from submission_policy import submission_allowance, submission_windows


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        (self.root / "automation").mkdir(parents=True)
        (self.root / "verifiers").mkdir()
        (self.root / "verifiers" / "official.txt").write_text("unchanged verifier")
        config = self.root / "automation" / "config.json"
        write_json(config, {"storage_root": str(self.base / "artifacts"), "project_root": str(self.root), "deadline": "2099-01-01T00:00:00+08:00", "timezone": "Asia/Shanghai", "daily_submission_time": "00:00", "submit_window_minutes": 1440, "min_free_gib": 0})
        self.pipeline = Pipeline(config)
        self.old_costs = {"dqi": 100.0, "invsqrt": 100.0, "dfthcsos": 100.0}
        with self.pipeline.locked():
            self.pipeline.state["last_submitted_costs"] = self.old_costs
            self.pipeline.state["baseline_costs"] = self.old_costs
            self.pipeline.save()
        for task in self.old_costs:
            cid = self.fixture(task, 100)
            with self.pipeline.locked():
                self.pipeline.state["best"][task] = cid
                self.pipeline.save()

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, task, cost):
        item = self.pipeline.create(task, "test hypothesis", "local fixture", "test-only")
        path = Path(item["directory"])
        out = path / "output"
        if task == "dfthcsos":
            (out / "angle_k_0.kmb").write_bytes(b"angle")
            (out / "submission.npz").write_bytes(b"factorization")
            report = {"status": "PASS", "score": cost, "verified_shots": 64, "resources": {"angles_within_cap": True}}
        else:
            circuit = out / f"{task}.kmb"
            circuit.write_bytes(f"{task}-{cost}".encode())
            report = {"status": "PASS", "score": cost, "circuit_sha256": sha256(circuit), "verified_shots": 200540928}
            if task == "dqi":
                report.update(m=4095, n=70, degree=12, r=2016, verified_shots=102400, log2_delta=-128, effective_error_rate=0.001)
        write_json(path / "official.json", report)
        item["verification"] = {"kind": "official", "runtime_fingerprint": self.pipeline.runtime_fingerprint(), "artifacts": artifact_manifest(out, task), "verifiers": self.pipeline.verifier_manifest(), "report": "official.json", "report_sha256": sha256(path / "official.json")}
        write_json(path / "candidate.json", item)
        return item["id"]

    def receipt(self, payload):
        path = self.base / "receipt.json"
        write_json(path, payload)
        return path

    def improved_package(self):
        cid = self.fixture("invsqrt", 80)
        self.pipeline.promote(cid)
        return self.pipeline.prepare()

    def unsubmitted_evidence(self):
        self.pipeline.config.update(competition="test-competition", submission_policy="after_optimization",
                                    max_daily_submissions=5, submission_quota_timezone="UTC")
        clock = patch.object(self.pipeline, "now", return_value=datetime.fromisoformat("2026-10-30T16:30:00+08:00"))
        now = clock.start()
        self.addCleanup(clock.stop)
        item = self.improved_package()
        self.pipeline.reserve(item["token"])
        self.pipeline.record(item["token"], self.receipt({"state": "upload_unconfirmed"}))
        run_id = "20261030T162900-submit-test"
        directory = self.pipeline.storage / "runs" / run_id
        directory.mkdir(parents=True)
        documents = {
            "context": {"mode": "submit", "run_id": run_id, "job_id": "submit-job"},
            "result": {"mode": "submit", "run_id": run_id, "job_id": "submit-job", "status": "completed",
                       "started_at": "2026-10-30T16:29:00+08:00", "finished_at": "2026-10-30T16:32:00+08:00"},
            "checkpoint": {"token": item["token"], "archive_sha256": item["archive_sha256"],
                           "failure_observation": {"token": item["token"], "stage": "upload_bytes",
                                                   "at": "2026-10-30T16:31:00+08:00", "error_type": "ConnectionError"}},
            "prepared": item,
            "preflight": {"competition": "test-competition", "account": "test-account", "team": "test-team",
                          "complete": True, "submissions": [{"ref": 10}]},
            "history": {"competition": "test-competition", "checked_at": "2026-10-30T16:59:00+08:00",
                        "complete": True, "pages": 1, "limits": {"numTotal": 1, "numToday": 1, "numAllowedNow": 4},
                        "submissions": [{"ref": 10, "date": "2026-10-30T16:00:00+08:00", "description": "prior accepted submission",
                                         "teamName": "test-team", "submittedByRef": "test-account", "totalBytes": 1}]},
        }
        names = {"context": "context.json", "result": "result.json", "checkpoint": "checkpoint.json",
                 "prepared": "prepared.json", "preflight": "preupload-preflight.json", "history": "remote-history.json"}
        files = {}
        for name, value in documents.items():
            path = directory / names[name]
            write_json(path, value)
            files[name] = {"path": str(path), "sha256": sha256(path)}
        script = directory / "submit_reserved.py"
        script.write_text("""import sys
stage = 'preflight'
try:
    stage = 'upload_bytes'
    result = transfer.put('blob')
    stage = 'create_submission'
    submitted = api.create_submission(request)
except BaseException as error:
    sys.exit(1)
""")
        files["script"] = {"path": str(script), "sha256": sha256(script)}
        proof = {"schema_version": 1, "token": item["token"], "archive_sha256": item["archive_sha256"],
                 "submit_run_id": run_id, "files": files}
        path = directory / "resolution-evidence.json"
        write_json(path, proof)
        now.return_value = datetime.fromisoformat("2026-10-30T17:00:00+08:00")
        return item, path, proof

    def test_proven_unsubmitted_resolution_preserves_quota_dedup_and_evidence(self):
        item, path, proof = self.unsubmitted_evidence()
        result = self.pipeline.resolve_unsubmitted(item["token"], path)
        self.assertEqual(result["status"], "not_submitted")
        self.assertEqual(result["receipt"], {"state": "upload_unconfirmed"})
        self.assertEqual(result["resolution"]["files"], proof["files"])
        self.assertTrue(result["resolution"]["quota_reservation_retained"])
        self.assertEqual(result["resolution"]["blob_receipt"], "unknown")
        self.assertEqual(result["events"][0]["status"], "upload_started")
        self.assertEqual(result["events"][-1]["status"], "not_submitted")
        again = self.pipeline.resolve_unsubmitted(item["token"], path)
        self.assertEqual(len(again["events"]), len(result["events"]))
        self.assertEqual(self.pipeline.prepare()["reason"], "already_attempted_candidate")
        allowance = pipeline_module.submission_allowance(self.pipeline.status(), self.pipeline.config, self.pipeline.now())
        self.assertEqual(allowance["attempts_today"], 1)
        self.assertEqual(allowance["remaining_today"], 4)
        self.assertEqual(self.pipeline.status()["last_submitted_costs"], self.old_costs)
        with self.assertRaisesRegex(PipelineError, "cannot erase"):
            self.pipeline.record(item["token"], self.receipt({"state": "upload_unconfirmed"}))
        self.pipeline.promote(self.fixture("invsqrt", 70))
        self.assertEqual(self.pipeline.prepare()["status"], "prepared")

    def test_unsubmitted_resolution_rejects_incomplete_or_conflicting_proof(self):
        item, path, proof = self.unsubmitted_evidence()
        originals = {name: read_json(entry["path"]) for name, entry in proof["files"].items() if name != "script"}
        cases = [
            ("checkpoint", lambda value: value["failure_observation"].update(stage="create_submission")),
            ("checkpoint", lambda value: value.update(submission_id=99)),
            ("result", lambda value: value.update(status="running")),
            ("result", lambda value: value.update(job_id="unrelated-job")),
            ("history", lambda value: value.update(complete=False)),
            ("history", lambda value: value.update(checked_at="2026-10-30T16:31:00+08:00")),
            ("history", lambda value: value.update(checked_at="2026-10-30T17:01:00+08:00")),
            ("history", lambda value: value.update(competition="another-competition")),
            ("history", lambda value: value["limits"].update(numToday=0)),
            ("history", lambda value: value["limits"].update(numTotal=2)),
            ("history", lambda value: value["submissions"][0].update(teamName="another-team")),
            ("history", lambda value: value["submissions"][0].update(description=item["token"])),
            ("prepared", lambda value: value.update(archive_sha256="0" * 64)),
        ]
        for name, mutate in cases:
            with self.subTest(name=name, change=cases.index((name, mutate))):
                modified = deepcopy(originals[name])
                mutate(modified)
                file = proof["files"][name]["path"]
                write_json(file, modified)
                proof["files"][name]["sha256"] = sha256(file)
                write_json(path, proof)
                with self.assertRaises(PipelineError):
                    self.pipeline.resolve_unsubmitted(item["token"], path)
                self.assertEqual(self.pipeline.status()["submissions"][item["token"]]["status"], "upload_started")
                write_json(file, originals[name])
                proof["files"][name]["sha256"] = sha256(file)

    def test_daily_success_limit_allows_three_ids_after_confirmed_upload_failure(self):
        failed, proof, _ = self.unsubmitted_evidence()
        self.pipeline.config.update(max_daily_submissions=3, submission_quota_basis='successful_submissions')
        resolved = self.pipeline.resolve_unsubmitted(failed['token'], proof)
        self.assertTrue(resolved['resolution']['attempt_record_retained'])
        self.assertFalse(resolved['resolution']['quota_reservation_retained'])
        for index, cost in enumerate((70, 60, 50)):
            self.pipeline.promote(self.fixture('invsqrt', cost))
            prepared = self.pipeline.prepare()
            self.pipeline.reserve(prepared['token'])
            quota = submission_allowance(self.pipeline.status(), self.pipeline.config, self.pipeline.now())
            self.assertEqual(quota['successes_today'], index)
            self.assertEqual(quota['remaining_today'], 3 - index)
            self.assertEqual(self.pipeline.prepare()['reason'], 'previous_submission_needs_reconciliation')
            recorded = self.pipeline.record(prepared['token'], self.receipt({'ref': 800 + index}))
            self.assertEqual(recorded['accepted_at'], self.pipeline.now_string())
            self.pipeline.record(prepared['token'], self.receipt({'ref': 800 + index}))
        quota = submission_allowance(self.pipeline.status(), self.pipeline.config, self.pipeline.now())
        self.assertEqual(quota['attempts_today'], 4)
        self.assertEqual(quota['successes_today'], 3)
        self.assertEqual(quota['remaining_today'], 0)
        self.pipeline.promote(self.fixture('invsqrt', 40))
        self.assertEqual(self.pipeline.prepare()['reason'], 'daily_submission_limit_reached')

    def test_unsubmitted_resolution_rejects_hash_drift_or_changed_uploader(self):
        item, path, proof = self.unsubmitted_evidence()
        script = Path(proof["files"]["script"]["path"])
        original = script.read_text()
        script.write_text(original + "# changed\n")
        with self.assertRaisesRegex(PipelineError, "hash mismatch"):
            self.pipeline.resolve_unsubmitted(item["token"], path)
        script.write_text(original.replace("sys.exit(1)", "pass"))
        proof["files"]["script"]["sha256"] = sha256(script)
        write_json(path, proof)
        with self.assertRaisesRegex(PipelineError, "control flow"):
            self.pipeline.resolve_unsubmitted(item["token"], path)
        self.assertEqual(self.pipeline.status()["submissions"][item["token"]]["status"], "upload_started")

    def test_unsubmitted_resolution_cannot_override_known_submission_id(self):
        item, path, _ = self.unsubmitted_evidence()
        self.pipeline.record(item["token"], self.receipt({"ref": 99}))
        with self.assertRaisesRegex(PipelineError, "without a known submission ID"):
            self.pipeline.resolve_unsubmitted(item["token"], path)
        self.assertEqual(self.pipeline.status()["submissions"][item["token"]]["submission_id"], 99)

    def test_geometric_improvement_and_bad_costs(self):
        self.assertAlmostEqual(improvement(self.old_costs, {"dqi": 50, "invsqrt": 100, "dfthcsos": 100}), 2 ** (1 / 3))
        for value in (float("nan"), float("inf"), 0, -1, True, None):
            with self.assertRaises(PipelineError):
                positive(value)

    def test_no_improvement_skips_without_archive(self):
        self.assertEqual(self.pipeline.prepare()["reason"], "no_improvement")
        self.assertFalse((self.pipeline.storage / "submissions").exists())

    def test_after_optimization_allows_five_improvements_outside_old_window(self):
        self.pipeline.config.update(submission_policy='after_optimization', max_daily_submissions=5,
                                    submission_quota_timezone='UTC', daily_submission_time='20:00', submit_window_minutes=45)
        with patch.object(self.pipeline, 'now', return_value=datetime.fromisoformat('2026-10-30T10:00:00+08:00')):
            for index, cost in enumerate((90, 80, 70, 60, 50)):
                self.pipeline.promote(self.fixture('invsqrt', cost))
                prepared = self.pipeline.prepare()
                reserved = self.pipeline.reserve(prepared['token'])
                self.assertEqual(reserved['quota_date'], '2026-10-30')
                self.pipeline.record(prepared['token'], self.receipt({'ref': 1000 + index}))
            self.pipeline.promote(self.fixture('invsqrt', 40))
            self.assertEqual(self.pipeline.prepare()['reason'], 'daily_submission_limit_reached')
        # Beijing midnight does not reset Kaggle's UTC-day allowance.
        with patch.object(self.pipeline, 'now', return_value=datetime.fromisoformat('2026-10-31T00:01:00+08:00')):
            self.assertEqual(self.pipeline.prepare()['reason'], 'daily_submission_limit_reached')
        with patch.object(self.pipeline, 'now', return_value=datetime.fromisoformat('2026-10-31T08:01:00+08:00')):
            self.assertEqual(self.pipeline.prepare()['status'], 'prepared')

    def test_after_optimization_unknown_upload_blocks_and_rejected_candidate_not_retried(self):
        self.pipeline.config.update(submission_policy='after_optimization', max_daily_submissions=5,
                                    submission_quota_timezone='UTC')
        item = self.improved_package()
        self.pipeline.reserve(item['token'])
        self.assertEqual(self.pipeline.prepare()['reason'], 'previous_submission_needs_reconciliation')
        self.pipeline.record(item['token'], self.receipt({'ref': 123, 'status': 'rejected'}))
        self.assertEqual(self.pipeline.prepare()['reason'], 'already_attempted_candidate')
        self.pipeline.promote(self.fixture('invsqrt', 70))
        self.assertEqual(self.pipeline.prepare()['status'], 'prepared')

    def test_after_optimization_reserves_at_current_quota_date(self):
        self.pipeline.config.update(submission_policy='after_optimization', max_daily_submissions=5,
                                    submission_quota_timezone='UTC')
        with patch.object(self.pipeline, 'now', return_value=datetime.fromisoformat('2026-10-30T23:59:00+08:00')):
            item = self.improved_package()
        with patch.object(self.pipeline, 'now', return_value=datetime.fromisoformat('2026-10-31T08:01:00+08:00')):
            reserved = self.pipeline.reserve(item['token'])
            self.assertEqual(reserved['date'], '2026-10-30')
            self.assertEqual(reserved['quota_date'], '2026-10-31')

    def daily_windows(self):
        self.pipeline.config.update(submission_policy='daily_windows',
                                    daily_submission_times=['08:00', '20:00'],
                                    max_daily_submissions=2, official_max_daily_submissions=5,
                                    submission_quota_timezone='UTC', submit_window_minutes=45)

    def test_daily_windows_allow_one_attempt_each_and_two_per_quota_day(self):
        self.daily_windows()
        with patch.object(self.pipeline, 'now', return_value=datetime.fromisoformat('2026-10-30T08:00:00+08:00')) as clock:
            first = self.improved_package()
            reserved = self.pipeline.reserve(first['token'])
            self.assertEqual(reserved['window_id'], '2026-10-30T08:00:00+08:00')
            self.assertEqual(reserved['quota_timezone'], 'UTC')
            self.pipeline.record(first['token'], self.receipt({'ref': 101}))
            self.pipeline.promote(self.fixture('invsqrt', 70))
            self.assertEqual(self.pipeline.prepare()['reason'], 'already_attempted_window')
            clock.return_value = datetime.fromisoformat('2026-10-30T20:00:00+08:00')
            second = self.pipeline.prepare()
            self.pipeline.reserve(second['token'])
            self.pipeline.record(second['token'], self.receipt({'ref': 102}))
            self.pipeline.promote(self.fixture('invsqrt', 60))
            self.assertEqual(self.pipeline.prepare()['reason'], 'daily_submission_limit_reached')
            clock.return_value = datetime.fromisoformat('2026-10-31T00:01:00+08:00')
            self.assertEqual(self.pipeline.prepare()['reason'], 'daily_submission_limit_reached')
            clock.return_value = datetime.fromisoformat('2026-10-31T08:00:00+08:00')
            self.assertEqual(self.pipeline.reserve(self.pipeline.prepare()['token'])['quota_date'], '2026-10-31')

    def test_daily_windows_reject_upload_outside_window_and_at_end(self):
        self.daily_windows()
        with patch.object(self.pipeline, 'now', return_value=datetime.fromisoformat('2026-10-30T07:59:59+08:00')) as clock:
            item = self.improved_package()
            for stamp in ('2026-10-30T07:59:59+08:00', '2026-10-30T08:45:00+08:00',
                          '2026-10-30T19:59:59+08:00', '2026-10-30T20:45:00+08:00'):
                clock.return_value = datetime.fromisoformat(stamp)
                with self.assertRaisesRegex(PipelineError, 'submission window'):
                    self.pipeline.reserve(item['token'])
            clock.return_value = datetime.fromisoformat('2026-10-30T20:44:59+08:00')
            self.assertEqual(self.pipeline.reserve(item['token'])['window_id'], '2026-10-30T20:00:00+08:00')

    def test_daily_windows_preserve_unknown_and_candidate_dedup_between_windows(self):
        self.daily_windows()
        with patch.object(self.pipeline, 'now', return_value=datetime.fromisoformat('2026-10-30T08:00:00+08:00')) as clock:
            item = self.improved_package()
            self.pipeline.reserve(item['token'])
            clock.return_value = datetime.fromisoformat('2026-10-30T20:00:00+08:00')
            self.assertEqual(self.pipeline.prepare()['reason'], 'previous_submission_needs_reconciliation')
            self.pipeline.record(item['token'], self.receipt({'ref': 101, 'status': 'rejected'}))
            self.assertEqual(self.pipeline.prepare()['reason'], 'already_attempted_candidate')
            self.pipeline.promote(self.fixture('invsqrt', 70))
            self.assertEqual(self.pipeline.prepare()['status'], 'prepared')

    def test_daily_windows_count_prior_policy_attempts_without_resetting_history(self):
        self.daily_windows()
        now = datetime.fromisoformat('2026-10-30T08:10:00+08:00')
        historical = {'status': 'not_submitted', 'submission_policy': 'after_optimization',
                      'date': '2026-10-29', 'quota_date': '2026-10-30', 'quota_timezone': 'UTC',
                      'reserved_at': '2026-10-30T08:02:00+08:00'}
        with self.pipeline.locked():
            self.pipeline.state['submissions']['old-attempt'] = historical
            self.pipeline.save()
        with patch.object(self.pipeline, 'now', return_value=now):
            self.assertEqual(self.pipeline.prepare()['reason'], 'already_attempted_window')
        allowance = submission_allowance(self.pipeline.state, self.pipeline.config, now)
        self.assertEqual(allowance['attempts_today'], 1)
        self.assertEqual(allowance['window_attempts'], 1)
        self.assertEqual(allowance['remaining_today'], 1)
        # A second attempt from the old policy consumes the new, lower limit too.
        with self.pipeline.locked():
            self.pipeline.state['submissions']['old-attempt-two'] = {**historical, 'reserved_at': '2026-10-30T12:00:00+08:00'}
            self.pipeline.save()
        with patch.object(self.pipeline, 'now', return_value=datetime.fromisoformat('2026-10-30T20:00:00+08:00')):
            self.assertEqual(self.pipeline.prepare()['reason'], 'daily_submission_limit_reached')

    def test_daily_windows_next_window_tracks_morning_evening_and_deadline(self):
        self.daily_windows()
        for stamp, expected in [('2026-10-30T07:59:00+08:00', '2026-10-30T08:00:00+08:00'),
                                ('2026-10-30T08:45:00+08:00', '2026-10-30T20:00:00+08:00'),
                                ('2026-10-30T20:45:00+08:00', '2026-10-31T08:00:00+08:00')]:
            now = datetime.fromisoformat(stamp)
            self.assertEqual(submission_allowance(self.pipeline.state, self.pipeline.config, now)['next_window'], expected)
        self.pipeline.config['deadline'] = '2026-10-31T07:59:00+08:00'
        allowance = submission_allowance(self.pipeline.state, self.pipeline.config, datetime.fromisoformat('2026-10-30T20:45:00+08:00'))
        self.assertIsNone(allowance['next_window'])
        with self.assertRaises(ValueError):
            submission_windows({**self.pipeline.config, 'daily_submission_times': ['08:00', '08:10']}, now)

    def test_resolution_uses_official_quota_instead_of_lower_local_limit(self):
        item, path, _ = self.unsubmitted_evidence()
        self.daily_windows()
        resolved = self.pipeline.resolve_unsubmitted(item['token'], path)
        self.assertEqual(resolved['status'], 'not_submitted')
        allowance = pipeline_module.submission_allowance(self.pipeline.status(), self.pipeline.config, self.pipeline.now())
        self.assertEqual(allowance['daily_limit'], 2)
        self.assertEqual(allowance['attempts_today'], 1)
        self.assertEqual(allowance['remaining_today'], 1)
        # An omitted official setting keeps the platform default of five;
        # the smaller local allowance must not be used to reject its history.
        self.pipeline.config.pop('official_max_daily_submissions')
        self.assertEqual(self.pipeline.resolve_unsubmitted(item['token'], path)['status'], 'not_submitted')

    def test_tampered_artifact_cannot_be_promoted(self):
        cid = self.fixture("invsqrt", 80)
        path, _ = self.pipeline.candidate(cid)
        (path / "output" / "invsqrt.kmb").write_bytes(b"modified")
        with self.assertRaisesRegex(PipelineError, "changed after verification"):
            self.pipeline.promote(cid)

    def test_changed_verifier_invalidates_existing_checks(self):
        cid = self.fixture("invsqrt", 80)
        (self.root / "verifiers" / "official.txt").write_text("changed")
        with self.assertRaisesRegex(PipelineError, "revalidation"):
            self.pipeline.promote(cid)

    def test_report_tampering_and_partial_report_rejected(self):
        cid = self.fixture("invsqrt", 80)
        path, data = self.pipeline.candidate(cid)
        report = json.loads((path / "official.json").read_text())
        report["verified_shots"] = 64
        with self.assertRaisesRegex(PipelineError, "full official input"):
            check_report("invsqrt", report, data["verification"]["artifacts"])
        write_json(path / "official.json", report)
        with self.assertRaisesRegex(PipelineError, "report changed"):
            self.pipeline.promote(cid)

    def test_packaging_correct_names_and_tampered_zip_rejected(self):
        item = self.improved_package()
        with zipfile.ZipFile(item["archive"]) as archive:
            self.assertEqual(set(archive.namelist()), {"dqi.kmb", "invsqrt.kmb", "dfthcsos/angle_k_0.kmb", "dfthcsos/submission.npz"})
        with open(item["archive"], "ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(PipelineError, "ZIP changed"):
            self.pipeline.reserve(item["token"])

    def test_same_day_duplicate_and_unknown_outcome_block(self):
        item = self.improved_package()
        self.pipeline.reserve(item["token"])
        self.assertEqual(self.pipeline.prepare()["reason"], "already_attempted_today")
        with self.pipeline.locked():
            self.pipeline.state["submissions"][item["token"]]["date"] = "2020-01-01"
            self.pipeline.save()
        self.assertEqual(self.pipeline.prepare()["reason"], "previous_submission_needs_reconciliation")
        self.pipeline.record(item["token"], self.receipt({"ref": 123}))
        self.assertEqual(self.pipeline.status()["submissions"][item["token"]]["status"], "score_unknown")
        cid = self.fixture("invsqrt", 70)
        self.pipeline.promote(cid)
        self.assertEqual(self.pipeline.prepare()["status"], "prepared")

    def test_new_best_invalidates_prepared_preview(self):
        item = self.improved_package()
        self.pipeline.promote(self.fixture("invsqrt", 70))
        with self.assertRaisesRegex(PipelineError, "Best candidates changed"):
            self.pipeline.reserve(item["token"])
        current = self.pipeline.prepare()
        self.assertEqual(self.pipeline.reserve(current["token"])["costs"]["invsqrt"], 70)

    def test_metadata_cannot_be_claimed_scored(self):
        item = self.improved_package()
        self.pipeline.reserve(item["token"])
        with self.assertRaisesRegex(PipelineError, "not requested"):
            self.pipeline.record(item["token"], self.receipt({"ref": 123}), requested_status="scored")
        result = self.pipeline.record(item["token"], self.receipt({"ref": 123, "publicScore": "4.25", "status": "complete"}))
        self.assertEqual(result["public_score"], 4.25)
        with self.assertRaisesRegex(PipelineError, "different submission"):
            self.pipeline.record(item["token"], self.receipt({"ref": 456}))

    def test_secret_fields_never_persist(self):
        result = safe_receipt({"structuredContent": {"ref": 123, "token": "secret", "url": "https://signed.example", "status": "pending"}})
        self.assertEqual(result, {"ref": 123, "status": "pending"})

    def test_snake_case_kaggle_score_is_recorded(self):
        item = self.improved_package()
        self.pipeline.reserve(item['token'])
        receipt = {"ref": 123, "status": "COMPLETE", "public_score": "2.18204",
                   "url": "https://example.com/private?token=secret"}
        result = self.pipeline.record(item['token'], self.receipt(receipt))
        self.assertEqual(result['status'], 'scored')
        self.assertEqual(result['public_score'], 2.18204)
        self.assertNotIn('url', result['receipt'])

    def test_candidate_paths_and_duplicate_angle_rejected(self):
        with self.assertRaises(PipelineError):
            self.pipeline.candidate_dir("../../outside")
        output = self.base / "invalid"
        output.mkdir()
        for name in ("submission.npz", "angle_k_0.kmb", "angle_k_0.kmx"):
            (output / name).write_bytes(b"x")
        with self.assertRaises(PipelineError):
            artifact_manifest(output, "dfthcsos")

    def test_small_stochastic_gain_needs_independent_evidence(self):
        cid = self.fixture("dqi", 99)
        with self.assertRaisesRegex(PipelineError, "independent"):
            self.pipeline.promote(cid)
        # A large structural gain can be evaluated without mandatory duplicate full verification.
        cid = self.fixture("dqi", 80)
        self.assertEqual(self.pipeline.promote(cid)["status"], "promoted")

    def test_identical_verified_candidate_reuses_success(self):
        cid = self.fixture("invsqrt", 80)
        with patch.object(self.pipeline, "runtime", side_effect=AssertionError("Must not rerun an identical official check")):
            self.assertEqual(self.pipeline.validate(cid)["kind"], "reused_official")

    def test_failed_replication_cannot_be_silently_ignored(self):
        cid = self.fixture("dqi", 99)
        path, data = self.pipeline.candidate(cid)
        data["runs"] = [{"kind": "robustness", "artifacts": data["verification"]["artifacts"], "verifiers": data["verification"]["verifiers"], "returncode": 1}]
        write_json(path / "candidate.json", data)
        with self.assertRaisesRegex(PipelineError, "only favorable"):
            self.pipeline.promote(cid)

    def test_late_submission_is_rejected(self):
        item = self.improved_package()
        self.pipeline.config.update(daily_submission_time="20:00", submit_window_minutes=45)
        with patch.object(self.pipeline, "now", return_value=self.pipeline.now().replace(hour=23, minute=0)):
            with self.assertRaisesRegex(PipelineError, "submission window"):
                self.pipeline.reserve(item["token"])

    def test_old_receipt_cannot_regress_submitted_frontier(self):
        item = self.improved_package()
        self.pipeline.reserve(item["token"])
        self.pipeline.record(item["token"], self.receipt({"ref": 123}))
        with self.pipeline.locked():
            self.pipeline.state["submissions"]["historical"] = {"token": "historical", "date": "2020-01-01", "status": "score_unknown", "submission_id": 100, "costs": self.old_costs}
            self.pipeline.save()
        self.pipeline.record("historical", self.receipt({"ref": 100, "publicScore": 1.5}))
        self.assertEqual(self.pipeline.status()["last_submitted_costs"]["invsqrt"], 80)

    def test_runtime_versions_changed_requires_revalidation(self):
        cid = self.fixture("invsqrt", 80)
        with patch.object(self.pipeline, "runtime_fingerprint", return_value={"python": "changed"}):
            with self.assertRaisesRegex(PipelineError, "versions changed"):
                self.pipeline.verified(cid)

    def test_archived_source_is_bound_but_current_edits_are_allowed(self):
        cid = self.fixture("invsqrt", 80)
        path, data = self.pipeline.candidate(cid)
        archived = path / "source-snapshot" / "builder.py"
        archived.parent.mkdir()
        archived.write_text("original source")
        data["verification"]["source"] = {"directory": "source-snapshot", "files": [{"path": "builder.py", "sha256": sha256(archived)}]}
        write_json(path / "candidate.json", data)
        (self.root / "builder.py").write_text("new experimental source")
        self.pipeline.verified(cid)
        archived.write_text("changed archived source")
        with self.assertRaisesRegex(PipelineError, "Archived source changed"):
            self.pipeline.verified(cid)

    def test_failed_revalidation_revokes_old_attestation(self):
        cid = self.fixture("invsqrt", 80)
        path, _ = self.pipeline.candidate(cid)
        (path / "output" / "invsqrt.kmb").write_bytes(b"new circuit that fails")
        failed = subprocess.CompletedProcess([], 1, "", "failure")
        with patch.object(self.pipeline, "runtime", return_value=(["fake-python"], {})), patch("pipeline.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(PipelineError, "verifier failed"):
                self.pipeline.validate(cid)
        _, data = self.pipeline.candidate(cid)
        self.assertNotIn("verification", data)
        self.assertEqual(data["runs"][-1]["returncode"], 1)

    def test_external_config_does_not_relocate_project(self):
        external = self.base / "external-config.json"
        config = dict(self.pipeline.config)
        config.pop("project_root")
        write_json(external, config)
        relocated = Pipeline(external)
        self.assertEqual(relocated.root, Path(pipeline_module.__file__).resolve().parent.parent)

    def test_environment_overrides_replace_stale_absolute_interpreter(self):
        prefix = self.base / "moved" / "portable-vqcc"
        executable = prefix / "bin" / "python"
        self.pipeline.config["python_executable"] = "/old/host/envs/vqcc/bin/python"
        results = [subprocess.CompletedProcess([], 0, json.dumps({"envs": [str(prefix)]})), subprocess.CompletedProcess([], 0, json.dumps({"executable": str(executable), "prefix": str(prefix)}))]
        with patch.dict("os.environ", {"VQCC_CONDA_ENV": "portable-vqcc", "VQCC_ENV_PREFIX": str(prefix), "VQCC_CONDA_BIN": "/custom/conda"}), patch("pipeline.subprocess.run", side_effect=results):
            command, identity = self.pipeline.runtime()
        self.assertEqual(command, ["/custom/conda", "run", "--no-capture-output", "-n", "portable-vqcc", str(executable)])
        self.assertEqual(identity["prefix"], str(prefix))

    def test_stale_interpreter_without_override_is_rejected(self):
        prefix = self.base / "moved" / "vqcc"
        self.pipeline.config["python_executable"] = "/old/host/envs/vqcc/bin/python"
        result = subprocess.CompletedProcess([], 0, json.dumps({"envs": [str(prefix)]}))
        with patch.dict("os.environ", {}, clear=True), patch("pipeline.subprocess.run", return_value=result):
            with self.assertRaisesRegex(PipelineError, "outside the Conda prefix"):
                self.pipeline.runtime()

    def test_conflicting_environment_prefix_override_is_rejected(self):
        prefix = self.base / "moved" / "vqcc"
        result = subprocess.CompletedProcess([], 0, json.dumps({"envs": [str(prefix)]}))
        with patch.dict("os.environ", {"VQCC_CONDA_ENV": "vqcc", "VQCC_ENV_PREFIX": str(self.base / "wrong-prefix")}), patch("pipeline.subprocess.run", return_value=result):
            with self.assertRaisesRegex(PipelineError, "does not match"):
                self.pipeline.runtime()


if __name__ == "__main__":
    unittest.main()
