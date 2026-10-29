#!/usr/bin/env python3
"""Local, auditable VQCC candidates and submission intents; never uploads anything."""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
import platform
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from zoneinfo import ZoneInfo

TASKS = ("dqi", "invsqrt", "dfthcsos")
VERIFIERS = {"dqi": "verifiers/dqi/verify_submission_dqi.py", "invsqrt": "verifiers/invsqrt/verify_submission_invsqrt.py", "dfthcsos": "verifiers/dfthcsos/verify.py"}
INFLIGHT = {"upload_started", "submitted", "score_unknown"}
ATTEMPTED = INFLIGHT | {"scored", "rejected"}


class PipelineError(RuntimeError):
    pass


def read_json(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def positive(value):
    if isinstance(value, bool):
        raise PipelineError("Cost must be a finite positive number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PipelineError("Cost must be a finite positive number") from None
    if not math.isfinite(number) or number <= 0:
        raise PipelineError("Cost must be a finite positive number")
    return number


def improvement(previous, proposed):
    """Relative geometric improvement; independent of unknown official reference costs."""
    return math.exp(sum(math.log(positive(previous[t])) - math.log(positive(proposed[t])) for t in TASKS) / 3)


def artifact_manifest(directory, task):
    directory = Path(directory)
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    if any(p.is_symlink() for p in directory.rglob("*")):
        raise PipelineError("Candidate artifacts must be regular files, not symbolic links")
    names = [p.relative_to(directory).as_posix() for p in files]
    if task in ("dqi", "invsqrt"):
        if len(names) != 1 or names[0] not in (f"{task}.kmb", f"{task}.kmx"):
            raise PipelineError(f"Expected only {task}.kmb or {task}.kmx in output/")
    else:
        angles = []
        for name in names:
            if name == "submission.npz":
                continue
            match = re.fullmatch(r"angle_k_(\d+)\.(kmb|kmx)", name)
            if not match:
                raise PipelineError(f"Unexpected chemistry submission file: {name}")
            angles.append(int(match.group(1)))
        if "submission.npz" not in names or not angles or sorted(angles) != list(range(len(angles))):
            raise PipelineError("Chemistry requires submission.npz and gap-free unique angle_k_N circuits")
    return [{"path": name, "bytes": p.stat().st_size, "sha256": sha256(p)} for name, p in zip(names, files)]


def check_report(task, report, manifest):
    if report.get("status") != "PASS":
        raise PipelineError("Official verifier did not report PASS")
    positive(report.get("score"))
    shots = report.get("verified_shots", 0)
    if task == "dqi":
        expected = {"m": 4095, "n": 70, "degree": 12, "r": 2016, "verified_shots": 102400, "log2_delta": -128}
        if any(report.get(k) != v for k, v in expected.items()):
            raise PipelineError("DQI report does not use the full official problem and confidence settings")
        if not 0 <= report.get("effective_error_rate", 1) < 1 / 16:
            raise PipelineError("DQI failure upper bound is outside the official range")
    elif task == "invsqrt" and shots != 200540928:
        raise PipelineError("InvSqrt report does not cover the full official input domain")
    elif task == "dfthcsos":
        if not isinstance(shots, int) or shots <= 0 or shots % 64:
            raise PipelineError("Chemistry report has invalid full-verification shot count")
        if report.get("resources", {}).get("angles_within_cap") is not True:
            raise PipelineError("Chemistry report is missing the ANGLE qubit-cap check")
    if task != "dfthcsos" and manifest[0]["path"].endswith(".kmb"):
        if report.get("circuit_sha256") != manifest[0]["sha256"]:
            raise PipelineError("Official report belongs to a different circuit")


def safe_receipt(value):
    """Keep only result fields, never signed URLs, upload tokens, headers or credentials."""
    allowed = {"ref", "submissionId", "id", "status", "state", "publicScore", "privateScore", "score", "date", "submittedAt", "createdAt", "errorDescription"}
    found = {}
    def visit(obj):
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in allowed and isinstance(val, (str, int, float, bool)):
                    if isinstance(val, str) and ("http" in val.lower() or len(val) > 1000):
                        continue
                    found[key] = val
                elif key in ("content", "structuredContent", "result", "submission", "submissions", "data"):
                    visit(val)
                elif key == "text" and isinstance(val, str):
                    try:
                        visit(json.loads(val))
                    except (ValueError, TypeError):
                        pass
        elif isinstance(obj, list):
            for item in obj:
                visit(item)
    visit(value)
    return found


class Pipeline:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve()
        self.config = read_json(self.config_path)
        self.root = Path(self.config.get("project_root", Path(__file__).resolve().parent.parent)).resolve()
        self.storage = Path(os.environ.get("VQCC_STORAGE_ROOT", self.config["storage_root"])).expanduser().resolve()
        self.tz = ZoneInfo(self.config.get("timezone", "Asia/Shanghai"))
        self.storage.mkdir(parents=True, exist_ok=True)
        self.state_path = self.storage / "state" / "pipeline.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def now(self):
        return datetime.now(self.tz)

    def now_string(self):
        return self.now().isoformat(timespec="seconds")

    @contextlib.contextmanager
    def locked(self):
        with open(self.state_path.parent / "pipeline.lock", "a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.state = read_json(self.state_path) if self.state_path.exists() else {"schema": 1, "best": {}, "submissions": {}}
            yield

    def save(self):
        write_json(self.state_path, self.state)

    def active(self):
        deadline = datetime.fromisoformat(self.config["deadline"])
        if self.now() >= deadline:
            raise PipelineError("Competition deadline has passed")

    def disk_check(self):
        required = float(self.config.get("min_free_gib", 20)) * 1024 ** 3
        if shutil.disk_usage(self.storage).free < required:
            raise PipelineError("Storage free space is below the configured minimum")

    def candidate_dir(self, candidate_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", candidate_id):
            raise PipelineError("Invalid candidate identifier")
        return self.storage / "experiments" / candidate_id

    def candidate(self, candidate_id):
        path = self.candidate_dir(candidate_id)
        data = read_json(path / "candidate.json")
        if data.get("id") != candidate_id or data.get("task") not in TASKS:
            raise PipelineError("Invalid candidate metadata")
        return path, data

    def verifier_manifest(self):
        files = []
        for base in (self.root / "verifiers", self.root / "kickmix"):
            for path in sorted(base.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    files.append({"path": path.relative_to(self.root).as_posix(), "sha256": sha256(path)})
        return files

    def source_snapshot(self, destination, candidate_path=None):
        """Snapshot reproducible source, not huge experiment output or credentials."""
        files = []
        for base in (self.root / "automation", self.root / "optimizers", self.root / "generators", self.root / "submission" / "2026-10-29" / "source"):
            if not base.exists():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts:
                    continue
                if path.suffix not in (".py", ".sh", ".json", ".toml", ".md", ".txt", ".yaml", ".yml") and path.name != "LICENSE":
                    continue
                relative = path.relative_to(self.root)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                files.append({"path": relative.as_posix(), "sha256": sha256(target)})
        if candidate_path is not None:
            extra = list((candidate_path / "code").rglob("*"))
            extra.append(candidate_path / "generation.json")
            for path in sorted(extra):
                if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts:
                    continue
                if path.stat().st_size > 16 * 1024 ** 2:
                    continue
                relative = Path("candidate") / path.relative_to(candidate_path)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                files.append({"path": relative.as_posix(), "sha256": sha256(target)})
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True)
        return {"directory": destination.name, "git_head": result.stdout.strip() if result.returncode == 0 else None, "files": files}

    def runtime_fingerprint(self):
        return {"python": platform.python_version(), "numpy": importlib.metadata.version("numpy"), "scipy": importlib.metadata.version("scipy")}

    @staticmethod
    def baseline_fingerprint(environment):
        return {"python": environment["python_version"].split()[0], "numpy": environment["packages"]["numpy"], "scipy": environment["packages"]["scipy"]}

    def verified(self, candidate_id):
        path, data = self.candidate(candidate_id)
        verification = data.get("verification")
        if not verification or verification.get("kind") not in ("official", "imported_official"):
            raise PipelineError(f"Candidate {candidate_id} lacks official full verification")
        manifest = artifact_manifest(path / "output", data["task"])
        if manifest != verification["artifacts"]:
            raise PipelineError("Artifact changed after verification")
        if self.verifier_manifest() != verification["verifiers"]:
            raise PipelineError("Official verifier or kickmix changed; revalidation is required")
        if verification.get("runtime_fingerprint") != self.runtime_fingerprint():
            raise PipelineError("Python or NumPy/SciPy versions changed or were not attested; revalidation is required")
        source = verification.get("source")
        if source:
            snapshot_name = Path(source["directory"])
            if snapshot_name.name != str(snapshot_name):
                raise PipelineError("Unsafe source snapshot directory")
            for entry in source["files"]:
                relative = Path(entry["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise PipelineError("Unsafe source snapshot file")
                archived = path / snapshot_name / relative
                if not archived.is_file() or archived.is_symlink() or sha256(archived) != entry["sha256"]:
                    raise PipelineError("Archived source changed after verification")
        report_path = path / verification["report"]
        if sha256(report_path) != verification["report_sha256"]:
            raise PipelineError("Verification report changed after attestation")
        report = read_json(report_path)
        check_report(data["task"], report, manifest)
        return path, data, report

    def init(self, baseline):
        baseline = Path(baseline).resolve()
        with self.locked():
            if self.state.get("initialized"):
                # Upgrade only the initial imported attestation, using the actual recorded
                # environment. This never fabricates a newly executed official check.
                upgraded = []
                for cid in (f"baseline-20261029-{task}" for task in TASKS):
                    target, data = self.candidate(cid)
                    verification = data.get("verification", {})
                    if verification.get("kind") == "imported_official" and "runtime_fingerprint" not in verification:
                        recorded = read_json(Path(data["source"]) / "validation" / "environment.json")
                        fingerprint = self.baseline_fingerprint(recorded)
                        if fingerprint != self.runtime_fingerprint():
                            raise PipelineError("Recorded baseline environment differs from current runtime")
                        verification["runtime_fingerprint"] = fingerprint
                        write_json(target / "candidate.json", data)
                        upgraded.append(cid)
                return {"status": "already_initialized", "storage_root": str(self.storage), "environment_attestations_upgraded": upgraded}
            self.disk_check()
            manifest = read_json(baseline / "manifest.json")
            for entry in manifest["files"]:
                relative = Path(entry["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise PipelineError("Unsafe baseline manifest path")
                source = baseline / "files" / relative
                if source.is_symlink() or source.stat().st_size != entry["bytes"] or sha256(source) != entry["sha256"]:
                    raise PipelineError(f"Baseline manifest mismatch: {relative}")
            environment = read_json(baseline / "validation" / "environment.json")
            if sha256(self.root / "kickmix" / "kickmix.so") != environment["kickmix_sha256"]:
                raise PipelineError("Baseline kickmix differs from current runtime")
            fingerprint = self.baseline_fingerprint(environment)
            if fingerprint != self.runtime_fingerprint():
                raise PipelineError("Recorded baseline environment differs from current runtime")
            verifiers = self.verifier_manifest()
            costs = {}
            for task in TASKS:
                cid = f"baseline-20261029-{task}"
                target = self.candidate_dir(cid)
                if target.exists():
                    raise PipelineError(f"Partial import exists: inspect {target} before retrying")
                (target / "output").mkdir(parents=True)
                if task == "dfthcsos":
                    shutil.copytree(baseline / "files" / task, target / "output", dirs_exist_ok=True)
                else:
                    shutil.copy2(baseline / "files" / f"{task}.kmb", target / "output" / f"{task}.kmb")
                art = artifact_manifest(target / "output", task)
                report = read_json(baseline / "validation" / f"{task}.json")
                check_report(task, report, art)
                write_json(target / "official.json", report)
                data = {"id": cid, "task": task, "created_at": self.now_string(), "parent": None,
                        "hypothesis": "Imported existing 2026-10-29 verified baseline; checks were not rerun",
                        "source": str(baseline), "license": "See baseline ADAPTATION.md and upstream/LICENSE",
                        "verification": {"kind": "imported_official", "verified_at": "2026-10-29", "imported_at": self.now_string(),
                            "historical_verifier_hashes_available": False, "verifiers_at_import": True,
                            "runtime_fingerprint": fingerprint, "artifacts": art, "verifiers": verifiers, "report": "official.json", "report_sha256": sha256(target / "official.json")}}
                write_json(target / "candidate.json", data)
                self.state["best"][task] = cid
                costs[task] = positive(report["score"])
            receipt = safe_receipt(read_json(baseline / "kaggle_submission_receipt.json"))
            if receipt.get("ref") != 57763974:
                raise PipelineError("Unexpected historical submission ID")
            self.state.update({"initialized": self.now_string(), "baseline_costs": costs, "last_submitted_costs": costs})
            self.state["submissions"]["imported-57763974"] = {"token": "imported-57763974", "date": "2026-10-29", "status": "score_unknown", "submission_id": 57763974, "receipt": receipt, "costs": costs, "selected": dict(self.state["best"]), "archive_sha256": manifest["archive_sha256"], "imported": True}
            self.save()
            return {"status": "initialized", "best": self.state["best"], "platform_score": None, "existing_submission_id": 57763974}

    def create(self, task, hypothesis, source, license_info, parent=None):
        self.active()
        with self.locked():
            self.disk_check()
            cid = f"{self.now().strftime('%Y%m%dT%H%M%S')}-{task}-{secrets.token_hex(3)}"
            path = self.candidate_dir(cid)
            (path / "output").mkdir(parents=True)
            (path / "code").mkdir()
            data = {"id": cid, "task": task, "created_at": self.now_string(), "parent": parent or self.state["best"].get(task), "hypothesis": hypothesis, "source": source, "license": license_info}
            write_json(path / "candidate.json", data)
            return {**data, "directory": str(path), "output": str(path / "output"), "code": str(path / "code")}

    def runtime(self):
        env_name = os.environ.get("VQCC_CONDA_ENV", self.config.get("conda_env", "vqcc"))
        conda = os.environ.get("VQCC_CONDA_BIN", "conda")
        listing = subprocess.run([conda, "env", "list", "--json"], capture_output=True, text=True, check=True)
        prefixes = [Path(p).resolve() for p in json.loads(listing.stdout)["envs"] if Path(p).name == env_name]
        if len(prefixes) != 1:
            raise PipelineError("Cannot uniquely resolve the requested existing Conda environment")
        prefix = prefixes[0]
        prefix_override = os.environ.get("VQCC_ENV_PREFIX")
        if prefix_override and Path(prefix_override).expanduser().resolve() != prefix:
            raise PipelineError("VQCC_ENV_PREFIX does not match the selected Conda environment")
        has_override = prefix_override or "VQCC_CONDA_ENV" in os.environ
        executable = prefix / "bin" / "python" if has_override else Path(self.config.get("python_executable", str(prefix / "bin" / "python")))
        if not executable.is_relative_to(prefix):
            raise PipelineError("Configured Python executable is outside the Conda prefix")
        probe = subprocess.run([conda, "run", "-n", env_name, str(executable), "-c", "import json,sys; print(json.dumps({'executable':sys.executable,'prefix':sys.prefix}))"], capture_output=True, text=True, check=True)
        identity = json.loads(probe.stdout)
        if Path(identity["prefix"]).resolve() != prefix or not Path(identity["executable"]).is_relative_to(prefix):
            raise PipelineError("Conda interpreter identity does not match the selected environment")
        return [conda, "run", "--no-capture-output", "-n", env_name, str(executable)], identity

    def validate(self, cid, robustness=False):
        self.active()
        with self.locked():
            self.disk_check()
            path, data = self.candidate(cid)
            task = data["task"]
            if robustness and task != "dqi":
                raise PipelineError("Automatic independent-seed replication is limited to DQI finalists")
            if robustness:
                self.verified(cid)
            elif data.get("verification"):
                try:
                    _, _, previous_report = self.verified(cid)
                except PipelineError:
                    data.pop("verification", None)
                    write_json(path / "candidate.json", data)
                else:
                    return {"status": "PASS", "id": cid, "kind": "reused_official", "cost": previous_report["score"], "report": str(path / data["verification"]["report"])}
            before = artifact_manifest(path / "output", task)
            verifier_before = self.verifier_manifest()
            command, identity = self.runtime()
            input_path = path / "output" if task == "dfthcsos" else path / "output" / before[0]["path"]
            command += [str(self.root / VERIFIERS[task]), str(input_path)]
            if task != "dfthcsos":
                command += ["--max-workers", str(min(int(self.config.get("cpu_limit", 20)), 16))]
            seed = secrets.randbits(128) if robustness else None
            if seed is not None:
                command += ["--seed", str(seed)]
            suffix = f"robustness-{uuid.uuid4().hex[:8]}" if robustness else f"official-{uuid.uuid4().hex[:8]}"
            env = os.environ.copy()
            env.update({"PYTHONPATH": str(self.root / "kickmix"), "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
            started = self.now_string()
            start = time.monotonic()
            source = self.source_snapshot(path / f"{suffix}-source", path)
            with open(path / f"{suffix}.stdout", "w") as out, open(path / f"{suffix}.stderr", "w") as err:
                result = subprocess.run(command, cwd=self.root, env=env, stdout=out, stderr=err)
            if before != artifact_manifest(path / "output", task) or verifier_before != self.verifier_manifest():
                raise PipelineError("Artifacts or verifier changed during validation")
            try:
                report = read_json(path / f"{suffix}.stdout")
            except (ValueError, OSError):
                report = {"status": "FAIL", "error": "Verifier did not return a JSON report"}
            write_json(path / f"{suffix}.json", report)
            record = {"kind": "robustness" if robustness else "official", "started_at": started, "finished_at": self.now_string(), "elapsed_seconds": time.monotonic() - start, "command": command, "runtime": identity, "runtime_fingerprint": self.runtime_fingerprint(), "returncode": result.returncode, "passed": False, "seed": seed, "artifacts": before, "verifiers": verifier_before, "report": f"{suffix}.json", "report_sha256": sha256(path / f"{suffix}.json"), "source": source}
            data.setdefault("runs", []).append(record)
            if result.returncode == 0:
                try:
                    check_report(task, report, before)
                except PipelineError:
                    write_json(path / "candidate.json", data)
                    raise
                record["passed"] = True
                if robustness:
                    data.setdefault("robustness", []).append(record)
                else:
                    data["verification"] = record
            write_json(path / "candidate.json", data)
            if result.returncode != 0:
                raise PipelineError(f"Official verifier failed; inspect {path / (suffix + '.stderr')} and stdout")
            return {"status": "PASS", "id": cid, "kind": record["kind"], "cost": report["score"], "report": str(path / record["report"])}

    def promote(self, cid):
        self.active()
        with self.locked():
            path, data, report = self.verified(cid)
            task = data["task"]
            old_id = self.state["best"].get(task)
            old_cost = math.inf
            if old_id:
                _, _, old_report = self.verified(old_id)
                old_cost = positive(old_report["score"])
            cost = positive(report["score"])
            if cost >= old_cost:
                return {"status": "skipped", "reason": "no_improvement", "id": cid}
            # Small stochastic gains need independent evidence; no zero-error requirement.
            replication_margin = float(self.config.get("dqi_small_gain_fraction", 0.02))
            if task == "dqi" and cost / old_cost > 1 - replication_margin:
                for run in data.get("runs", []):
                    if run["kind"] == "robustness" and run["artifacts"] == data["verification"]["artifacts"] and run["verifiers"] == data["verification"]["verifiers"] and (run.get("returncode") != 0 or run.get("passed") is False):
                        raise PipelineError("A matching robustness run failed; investigate the failure instead of selecting only favorable replications")
                usable = []
                for record in data.get("robustness", []):
                    rp = path / record["report"]
                    if record["artifacts"] != data["verification"]["artifacts"] or record["verifiers"] != data["verification"]["verifiers"] or sha256(rp) != record["report_sha256"]:
                        continue
                    rr = read_json(rp)
                    check_report(task, rr, record["artifacts"])
                    usable.append(positive(rr["score"]))
                if not usable or max(usable) >= old_cost:
                    raise PipelineError(f"DQI improvement below {replication_margin:.0%} needs an independent full-size robustness run with cost below the incumbent; keep evidence separate")
            self.state["best"][task] = cid
            data["promoted_at"] = self.now_string()
            write_json(path / "candidate.json", data)
            self.save()
            return {"status": "promoted", "task": task, "id": cid, "previous": old_id, "cost": cost, "previous_cost": old_cost}

    def skip_reason(self, costs):
        today = self.now().date().isoformat()
        for item in self.state["submissions"].values():
            if item["status"] in ATTEMPTED and item["date"] == today:
                return "already_attempted_today"
        for item in self.state["submissions"].values():
            if item["status"] in INFLIGHT and not item.get("submission_id"):
                return "previous_submission_needs_reconciliation"
        previous = self.state.get("last_submitted_costs")
        if previous is None or improvement(previous, costs) <= 1 + 1e-12:
            return "no_improvement"
        return None

    def prepare(self):
        self.active()
        with self.locked():
            if set(self.state["best"]) != set(TASKS):
                raise PipelineError("All three verified task baselines are required")
            selected = dict(self.state["best"])
            candidates = {task: self.verified(cid) for task, cid in selected.items()}
            costs = {task: positive(value[2]["score"]) for task, value in candidates.items()}
            reason = self.skip_reason(costs)
            if reason:
                return {"status": "skipped", "reason": reason, "costs": costs}
            self.disk_check()
            today = self.now().date().isoformat()
            token = f"{today}-{secrets.token_hex(8)}"
            directory = self.storage / "submissions" / token
            directory.mkdir(parents=True)
            archive = directory / "submission.zip"
            files = []
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
                for task, (path, data, report) in candidates.items():
                    for entry in data["verification"]["artifacts"]:
                        arcname = f"dfthcsos/{entry['path']}" if task == "dfthcsos" else entry["path"]
                        output.write(path / "output" / entry["path"], arcname)
                        files.append({**entry, "path": arcname})
            with zipfile.ZipFile(archive) as check:
                if sorted(check.namelist()) != sorted(entry["path"] for entry in files):
                    raise PipelineError("ZIP file list does not match selected artifacts")
                for entry in files:
                    digest = hashlib.sha256()
                    with check.open(entry["path"]) as stream:
                        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != entry["sha256"]:
                        raise PipelineError("ZIP round-trip integrity failed")
            item = {"token": token, "date": today, "status": "prepared", "created_at": self.now_string(), "selected": selected, "costs": costs, "relative_improvement": improvement(self.state["last_submitted_costs"], costs), "archive": str(archive), "archive_sha256": sha256(archive), "archive_bytes": archive.stat().st_size, "files": files}
            self.state["submissions"][token] = item
            write_json(directory / "manifest.json", item)
            self.save()
            return item

    def reserve(self, token):
        self.active()
        with self.locked():
            now = self.now()
            hour, minute = map(int, self.config.get("daily_submission_time", "20:00").split(":"))
            start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            elapsed_minutes = (now - start).total_seconds() / 60
            if not 0 <= elapsed_minutes < int(self.config.get("submit_window_minutes", 45)):
                raise PipelineError("Outside the configured daily submission window")
            item = self.state["submissions"].get(token)
            if not item or item["status"] != "prepared":
                raise PipelineError("Submission is not in prepared state")
            if item["date"] != self.now().date().isoformat():
                raise PipelineError("Prepared package is from a different Shanghai calendar day")
            reason = self.skip_reason(item["costs"])
            if reason:
                raise PipelineError(reason)
            for cid in item["selected"].values():
                self.verified(cid)
            if sha256(item["archive"]) != item["archive_sha256"]:
                raise PipelineError("ZIP changed after preparation")
            item.update(status="upload_started", reserved_at=self.now_string())
            self.save()
            return item

    def record(self, token, receipt_file, requested_status=None, submission_id=None, score=None):
        with self.locked():
            item = self.state["submissions"].get(token)
            if not item or item["status"] not in ATTEMPTED:
                raise PipelineError("No reserved or historical submission to reconcile")
            receipt = safe_receipt(read_json(receipt_file))
            sid = receipt.get("ref", receipt.get("submissionId"))
            if sid is not None:
                sid = int(sid)
            if submission_id is not None:
                if sid is not None and sid != submission_id:
                    raise PipelineError("Receipt and supplied submission ID disagree")
                sid = submission_id
            if item.get("submission_id") and sid and item["submission_id"] != sid:
                raise PipelineError("Cannot reconcile a different submission ID")
            sid = sid or item.get("submission_id")
            state_text = str(receipt.get("status", receipt.get("state", ""))).lower()
            returned_score = receipt.get("publicScore", receipt.get("score"))
            if returned_score is not None:
                returned_score = positive(returned_score)
            if score is not None and (returned_score is None or float(score) != returned_score):
                raise PipelineError("A score must come from the supplied platform receipt")
            if state_text in ("error", "failed", "rejected", "invalid"):
                status = "rejected"
            elif returned_score is not None and sid is not None:
                status = "scored"
            elif sid is not None:
                status = "score_unknown" if not state_text else "submitted"
            else:
                status = "upload_started"
            if requested_status is not None and requested_status != status:
                # A receipt containing only a newly accepted ID can be recorded as submitted,
                # but it can never be turned into scored or rejected without platform evidence.
                if requested_status == "submitted" and sid is not None and status == "score_unknown":
                    status = "submitted"
                else:
                    raise PipelineError(f"Receipt supports {status!r}, not requested {requested_status!r}")
            if item["status"] == "scored" and status != "scored":
                raise PipelineError("Incomplete metadata cannot erase an already confirmed score")
            item.update(status=status, receipt=receipt, updated_at=self.now_string())
            if sid:
                item["submission_id"] = sid
                # Best components are promoted monotonically. Looking up a historical
                # receipt must not roll the submitted frontier back to an older circuit.
                previous = self.state.get("last_submitted_costs", item["costs"])
                self.state["last_submitted_costs"] = {task: min(positive(previous[task]), positive(item["costs"][task])) for task in TASKS}
            if returned_score is not None:
                item["public_score"] = returned_score
            item.setdefault("events", []).append({"at": self.now_string(), "status": status, "receipt": receipt})
            self.save()
            return item

    def status(self):
        with self.locked():
            return {"storage_root": str(self.storage), "timezone": str(self.tz), "now": self.now_string(), **self.state}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.json")))
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Import the already verified and submitted 2026-10-29 baseline")
    init.add_argument("--baseline", default="submission/2026-10-29")
    create = sub.add_parser("create", help="Create an isolated experiment; write circuit files into output/")
    create.add_argument("task", choices=TASKS)
    create.add_argument("--hypothesis", required=True)
    create.add_argument("--source", required=True)
    create.add_argument("--license", required=True, dest="license_info")
    create.add_argument("--parent")
    validate = sub.add_parser("validate", help="Run unchanged official full validation")
    validate.add_argument("id")
    validate.add_argument("--robustness", action="store_true", help="Separate fresh-seed full DQI replication; does not replace official score")
    promote = sub.add_parser("promote")
    promote.add_argument("id")
    sub.add_parser("prepare")
    reserve = sub.add_parser("reserve", help="Persist upload intent immediately before any external upload")
    reserve.add_argument("token")
    for name in ("record", "reconcile"):
        record = sub.add_parser(name, help="Ingest a redacted platform receipt; absence of status/score remains unknown")
        record.add_argument("token")
        record.add_argument("--receipt", required=True)
        record.add_argument("--status", choices=("submitted", "score_unknown", "scored", "rejected"))
        record.add_argument("--submission-id", type=int)
        record.add_argument("--score", type=float)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    pipeline = Pipeline(args.config)
    if args.command == "init":
        result = pipeline.init(args.baseline)
    elif args.command == "create":
        result = pipeline.create(args.task, args.hypothesis, args.source, args.license_info, args.parent)
    elif args.command == "validate":
        result = pipeline.validate(args.id, args.robustness)
    elif args.command == "promote":
        result = pipeline.promote(args.id)
    elif args.command == "prepare":
        result = pipeline.prepare()
    elif args.command == "reserve":
        result = pipeline.reserve(args.token)
    elif args.command in ("record", "reconcile"):
        result = pipeline.record(args.token, args.receipt, args.status, args.submission_id, args.score)
    else:
        result = pipeline.status()
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (PipelineError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
