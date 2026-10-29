"""Behavioral safety tests. Fake reports exercise bookkeeping, not scientific acceptance."""
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
import zipfile

from pipeline import Pipeline, PipelineError, artifact_manifest, check_report, improvement, positive, safe_receipt, sha256, write_json
import pipeline as pipeline_module


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

    def test_geometric_improvement_and_bad_costs(self):
        self.assertAlmostEqual(improvement(self.old_costs, {"dqi": 50, "invsqrt": 100, "dfthcsos": 100}), 2 ** (1 / 3))
        for value in (float("nan"), float("inf"), 0, -1, True, None):
            with self.assertRaises(PipelineError):
                positive(value)

    def test_no_improvement_skips_without_archive(self):
        self.assertEqual(self.pipeline.prepare()["reason"], "no_improvement")
        self.assertFalse((self.pipeline.storage / "submissions").exists())

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
