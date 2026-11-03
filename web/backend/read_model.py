"""Small, cached projections of existing VQCC evidence. Never acquires pipeline.lock."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import threading
import time
from zoneinfo import ZoneInfo

from automation.runner import redact
from automation.submission_policy import (ATTEMPTED, submission_allowance, submission_quota_date,
                                          submission_success_date, successful_submission_id)
from .artifacts import ArtifactRegistry
from .resources import ResourceMonitor, normalize_task_sample

TASKS = ("dqi", "invsqrt", "dfthcsos")
ACTIVE = {"starting", "running", "cancel_requested", "unknown"}
ID = re.compile(r"[A-Za-z0-9_-]+")
SCREEN_REJECTED_DECISIONS = {
    "measured_no_gain_in_tested_scope",
    "no_lower_toffoli_count",
    "screened_out_no_proved_reduction",
    "screened_out_no_width_gain",
}
SEARCH_STOPPED = {
    "bounded_deadline",
    "iteration_limit",
    "line_search_stalled",
    "numerical_progress_stalled",
}
GENERATION_FAILED = {"error", "failed", "generation_failed"}


def clean(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()
                if key.lower() not in {"access_token", "refresh_token", "authorization", "password", "api_key", "client_secret"}}
    return value


def identity_alive(pid, birth):
    if pid is None or birth is None:
        return None
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[19]) == int(birth)
    except (FileNotFoundError, ProcessLookupError):
        return False


def preverification_state(directory, task, generation):
    """Summarize recorded pre-verification evidence without judging missing evidence."""
    build_status = generation.get("build_status")
    generation_status = generation.get("status")
    decision = generation.get("decision")
    reason = decision or generation_status or build_status

    if (
        build_status in {"rejected", "screen_rejected"}
        or generation.get("passes_numerical_gates") is False
        or generation.get("best_feasible_found") is False
        or isinstance(decision, str)
        and (
            decision in SCREEN_REJECTED_DECISIONS
            or decision.startswith(("rejected_", "screened_out_"))
            or "no_gain" in decision
            or "no_lower" in decision
        )
        or any(
            isinstance(generation.get(key), (int, float))
            and not isinstance(generation.get(key), bool)
            and generation[key] <= 0
            for key in ("saved_toffoli", "unconditional_toffolis_saved")
        )
    ):
        return "screen_rejected", reason or "recorded_screen_did_not_show_an_improvement"
    if build_status in GENERATION_FAILED or generation_status in GENERATION_FAILED or generation.get("error"):
        return "generation_failed", generation.get("error") or reason or "generation_failed"
    if generation_status in SEARCH_STOPPED:
        return "search_stopped", generation_status

    output = directory / "output"
    files = sorted(
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    ) if output.exists() else []
    if task in {"dqi", "invsqrt"}:
        ready = len(files) == 1 and files[0] in {f"{task}.kmb", f"{task}.kmx"}
    else:
        angles = []
        invalid = False
        for name in files:
            if name == "submission.npz":
                continue
            match = re.fullmatch(r"angle_k_(\d+)\.(kmb|kmx)", name)
            if match:
                angles.append(int(match.group(1)))
            else:
                invalid = True
        ready = (
            not invalid
            and "submission.npz" in files
            and bool(angles)
            and sorted(angles) == list(range(len(angles)))
        )
    if ready:
        return "awaiting_validation", "official_verifier_not_run"
    if files:
        return "artifact_incomplete", "output_does_not_match_the_official_artifact_layout"
    if generation:
        return "analysis_only", reason or generation.get("kind") or "no_official_artifact_generated"
    return "not_generated", "no_generation_or_verification_record"


class ReadModel:
    def __init__(self, config_path, jobs=None):
        self.config_path = Path(config_path).resolve()
        self.config = json.loads(self.config_path.read_text())
        self.storage = Path(os.environ.get("VQCC_STORAGE_ROOT", self.config["storage_root"])).resolve()
        self.jobs = jobs
        self.tz = ZoneInfo(self.config.get("timezone", "Asia/Shanghai"))
        self.artifacts = ArtifactRegistry(self.storage)
        self.resource_monitor = ResourceMonitor(self.storage, self.config['gpu_ids'])
        self._cache = {}
        self._cache_lock = threading.RLock()
        self._local = threading.local()
        self._jsonl_cache = {}
        self._index = None
        self._index_at = 0
        self._index_observation = None

    def now(self):
        return datetime.now(self.tz)

    def _observation(self):
        if not hasattr(self._local, "observation"):
            self._local.observation = {"stale": False, "partial": False, "times": [], "revisions": []}
        return self._local.observation

    def _partial(self):
        self._observation()["partial"] = True

    def _path(self, directory, identifier):
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise ValueError("Invalid identifier")
        path = self.storage / directory / identifier
        if not path.resolve().is_relative_to(self.storage / directory):
            raise ValueError("Invalid artifact path")
        return path

    def _json(self, path, default=None, optional=False):
        path = Path(path)
        observation = self._observation()
        with self._cache_lock:
            cached = self._cache.get(path)
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(self.storage):
                    raise ValueError("Path is outside storage")
                stat = path.stat()
                signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
                if stat.st_size > 16 * 1024 * 1024:
                    raise ValueError("Metadata exceeds size limit")
                if cached is None or cached[0] != signature:
                    raw = path.read_bytes()
                    value = json.loads(raw)
                    # Atomic replacements can race with stat; read again next time.
                    cached = (signature, value, stat.st_mtime, hashlib.sha256(raw).hexdigest())
                    self._cache[path] = cached
                observation["times"].append(cached[2])
                observation["revisions"].append(f"{path.relative_to(self.storage)}:{cached[0]}")
                return deepcopy(cached[1])
            except (OSError, ValueError):
                if cached:
                    observation["stale"] = True
                    observation["times"].append(cached[2])
                    return deepcopy(cached[1])
                if not optional:
                    observation["partial"] = True
                return deepcopy(default)

    def envelope(self, data):
        observation = self._observation()
        updated = max(observation["times"], default=None)
        revision = data.get("revision") if isinstance(data, dict) else None
        if revision is None:
            signature = "|".join(sorted(set(observation["revisions"]))) + json.dumps(data, sort_keys=True, ensure_ascii=False)
            revision = hashlib.sha256(signature.encode()).hexdigest()[:16]
        result = {"data": clean(data), "observed_at": datetime.now(timezone.utc).isoformat(),
                  "source_updated_at": datetime.fromtimestamp(updated, timezone.utc).isoformat() if updated else None,
                  "revision": revision,
                  "freshness": "stale" if observation["stale"] else "current",
                  "consistency": "partial" if observation["partial"] or observation["stale"] else "consistent"}
        self._local.observation = {"stale": False, "partial": False, "times": [], "revisions": []}
        return result

    def pipeline(self):
        return self._json(self.storage / "state/pipeline.json", {"best": {}, "submissions": {}})

    def control(self):
        if (self.storage / "console/state.json").exists():
            return self._json(self.storage / "console/state.json", {})
        return self.jobs.snapshot() if self.jobs is not None else {}

    def _report(self, directory, filename, expected_sha=None):
        if not filename:
            return {}
        relative = Path(filename)
        if relative.is_absolute() or ".." in relative.parts:
            self._partial()
            return {}
        path = directory / relative
        report = self._json(path, {})
        cached = self._cache.get(path)
        if expected_sha and cached and cached[3] != expected_sha:
            self._partial()
            return {"status": "EVIDENCE_STALE", "error": "验证报告与记录指纹不符"}
        return report

    def _candidate(self, cid, details=False, state=None):
        directory = self._path("experiments", cid)
        candidate = self._json(directory / "candidate.json", {})
        if not candidate:
            raise KeyError(cid)
        generation = self._json(directory / "generation.json", {}, optional=True)
        verification = candidate.get("verification") or {}
        report = self._report(directory, verification.get("report"), verification.get("report_sha256"))
        status = "not_run"
        status_reason = None
        if verification:
            status = report.get("status", "unknown")
            if verification.get("passed") is False:
                status = "FAIL"
            status_reason = report.get("error")
        elif candidate.get("runs"):
            latest = candidate["runs"][-1]
            if latest.get("passed") is False or latest.get("returncode", 0) != 0:
                status = "FAIL"
                report = self._report(directory, latest.get("report"))
                status_reason = report.get("error") or "official_verifier_failed"
            else:
                status, status_reason = preverification_state(directory, candidate.get("task"), generation)
        else:
            status, status_reason = preverification_state(directory, candidate.get("task"), generation)
        state = state if state is not None else self.pipeline()
        task = candidate.get("task")
        cost = report.get("score") if status == "PASS" else None
        baseline = state.get("baseline_costs", {}).get(task)
        summary = {"id": cid, "task": task, "created_at": candidate.get("created_at"),
                   "parent": candidate.get("parent"), "hypothesis": candidate.get("hypothesis"),
                   "parameters": generation.get("parameters", candidate.get("parameters", {})),
                   "generator_revision": generation.get("generator_sha256"),
                   "official_cost": cost, "validation_status": status,
                   "validation_reason": status_reason,
                   "verified_at": verification.get("finished_at"),
                   "promoted_at": candidate.get("promoted_at"),
                   "verification_kind": verification.get("kind"),
                   "evidence_integrity": "stale" if status == "EVIDENCE_STALE" else "not_rechecked" if verification else None,
                   "best": state.get("best", {}).get(task) == cid,
                   "improvement": 1 - cost / baseline if cost is not None and baseline else None,
                   "metrics": {key: value for key, value in report.items()
                               if key not in {"status", "score", "command"}},
                   "failure_reason": generation.get("reason") or report.get("error"),
                   "diagnostic_status": "recorded" if candidate.get("robustness") else "not_recorded",
                   "research_id": candidate.get("research_id")}
        if details:
            artifacts = []
            files = [directory / "candidate.json", directory / "generation.json"]
            if verification.get("report"):
                files.append(directory / verification["report"])
            for item in candidate.get("robustness", []):
                if item.get("report"):
                    files.append(directory / item["report"])
            for file in files:
                if file.exists():
                    try:
                        artifacts.append(self.artifacts.register(file))
                    except ValueError:
                        self._partial()
            lineage = [{"id": cid, "parent": candidate.get("parent"), "task": task}]
            parent = candidate.get("parent")
            seen = {cid}
            while parent and parent not in seen:
                seen.add(parent)
                ancestor = self._json(self._path("experiments", parent) / "candidate.json", {}, optional=True)
                if not ancestor:
                    lineage.append({"id": parent, "parent": None, "task": None, "unknown": True})
                    break
                lineage.append({"id": parent, "parent": ancestor.get("parent"), "task": ancestor.get("task")})
                parent = ancestor.get("parent")
            summary.update(verification=verification or None, diagnostics=candidate.get("robustness", []),
                           generation=generation, artifacts=artifacts, lineage=lineage,
                           source=candidate.get("source"), license=candidate.get("license"),
                           runs=candidate.get("runs", []), promoted_at=candidate.get("promoted_at"),
                           actions={"validate": True, "promote": status == "PASS" and not summary["best"], "clone": True},
                           reproduction={"candidate_id": cid, "parameters": summary["parameters"],
                                         "source": verification.get("source"),
                                         "environment": verification.get("runtime_fingerprint"),
                                         "validation_command": shlex.join(["conda", "run", "-n", self.config["conda_env"], self.config["python_executable"], "automation/pipeline.py", "--config", str(self.config_path), "validate", cid])})
        return clean(summary)

    def experiment(self, identifier):
        return self._candidate(identifier, details=True)

    def _experiment_items(self, state=None):
        state = state if state is not None else self.pipeline()
        # Cache the metadata index briefly. Circuit files are never opened here.
        with self._cache_lock:
            if self._index is None or time.monotonic() - self._index_at >= 5:
                items = []
                for path in (self.storage / "experiments").glob("*/candidate.json"):
                    try:
                        items.append(self._candidate(path.parent.name, state=state))
                    except (KeyError, ValueError):
                        self._partial()
                self._index = sorted(items, key=lambda x: (x.get("created_at") or "", x["id"]), reverse=True)
                self._index_at = time.monotonic()
                self._index_observation = deepcopy(self._observation())
            elif self._index_observation:
                observation = self._observation()
                observation["stale"] |= self._index_observation["stale"]
                observation["partial"] |= self._index_observation["partial"]
                observation["times"].extend(self._index_observation["times"])
                observation["revisions"].extend(self._index_observation["revisions"])
            items = deepcopy(self._index)
        for item in items:
            item["best"] = state.get("best", {}).get(item["task"]) == item["id"]
        return items

    def experiments(self, task=None, validation=None, cursor=0, limit=50, **filters):
        state = self.pipeline()
        items = self._experiment_items(state)
        if task:
            items = [item for item in items if item["task"] == task]
        if validation:
            items = [item for item in items if item["validation_status"] == validation]
        for key in ("parent", "generator_revision", "diagnostic_status", "research_id"):
            if filters.get(key):
                items = [item for item in items if item.get(key) == filters[key]]
        if filters.get("best") is not None:
            items = [item for item in items if item["best"] == filters["best"]]
        if filters.get("q") or filters.get("query"):
            q = (filters.get("q") or filters["query"]).lower()
            items = [item for item in items if q in json.dumps(item, ensure_ascii=False).lower()]
        start, limit = int(cursor or 0), min(200, max(1, int(limit)))
        return {"items": items[start:start + limit], "next_cursor": str(start + limit) if start + limit < len(items) else None,
                "total": len(items)}

    def task_history(self, task=None):
        if task is not None and task not in TASKS:
            raise ValueError("Unknown task")
        state = self.pipeline()
        candidates = self._experiment_items(state)
        histories = []
        for name in TASKS:
            if task is not None and name != task:
                continue
            scores = [item for item in candidates
                      if item.get("task") == name
                      and item.get("validation_status") == "PASS"
                      and isinstance(item.get("official_cost"), (int, float))
                      and not isinstance(item.get("official_cost"), bool)
                      and math.isfinite(item["official_cost"])
                      and item["official_cost"] > 0]
            scores.sort(key=lambda item: (
                (item.get("verified_at") or item.get("created_at")) is None,
                item.get("verified_at") or item.get("created_at") or "",
                item["id"],
            ))
            score_history = [{
                "candidate_id": item["id"],
                "created_at": item.get("created_at"),
                "verified_at": item.get("verified_at"),
                "recorded_at": item.get("verified_at") or item.get("created_at"),
                "promoted_at": item.get("promoted_at"),
                "official_cost": item["official_cost"],
                "is_promoted": bool(item.get("promoted_at")),
                "is_current_best": bool(item.get("best")),
            } for item in scores]
            promoted = sorted((item for item in scores if item.get("promoted_at")),
                              key=lambda item: (item["promoted_at"], item["id"]))
            baseline = state.get("baseline_costs", {}).get(name)
            baseline = baseline if isinstance(baseline, (int, float)) and baseline > 0 else None
            previous = baseline
            improvement_history = []
            for item in promoted:
                cost = item["official_cost"]
                improvement_history.append({
                    "candidate_id": item["id"],
                    "promoted_at": item["promoted_at"],
                    "official_cost": cost,
                    "previous_best_cost": previous,
                    "step_reduction": 1 - cost / previous if previous else None,
                    "baseline_reduction": 1 - cost / baseline if baseline else None,
                    "baseline_factor": baseline / cost if baseline else None,
                    "is_current_best": bool(item.get("best")),
                })
                previous = cost
            current_id = state.get("best", {}).get(name)
            current = next((item for item in scores if item["id"] == current_id), None)
            histories.append({
                "task": name,
                "baseline_cost": baseline,
                "current_best_id": current_id,
                "current_best_cost": current.get("official_cost") if current else None,
                "pass_count": len(score_history),
                "improvement_count": len(improvement_history),
                "score_history": score_history,
                "improvement_history": improvement_history,
            })
        return {"items": histories}

    def compare(self, ids):
        if isinstance(ids, str):
            ids = ids.split(",")
        if not 2 <= len(ids) <= 4 or len(set(ids)) != len(ids):
            raise ValueError("Choose 2–4 distinct candidates")
        items = [self.experiment(cid) for cid in ids]
        if len({item["task"] for item in items}) != 1:
            raise ValueError("Only candidates for the same task can be compared")
        keys = sorted(set().union(*(item["parameters"] for item in items)))
        differences = [key for key in keys if len({json.dumps(item["parameters"].get(key), sort_keys=True) for item in items}) > 1]
        evidence = [item["verification"] or {} for item in items]
        signatures = [json.dumps({key: v.get(key) for key in ("runtime_fingerprint", "verifiers")}, sort_keys=True) for v in evidence]
        return {"items": items, "task": items[0]["task"], "parameter_differences": differences,
                "comparable_environment": len(set(signatures)) == 1 and all(evidence),
                "historical_verifier_limitations": [item["id"] for item in items if (item["verification"] or {}).get("historical_verifier_hashes_available") is False],
                "reference_id": ids[0], "cost_changes": {
                    item["id"]: 1 - item["official_cost"] / items[0]["official_cost"]
                    if item["official_cost"] is not None and items[0]["official_cost"] else None for item in items}}

    def _jsonl(self, path, maximum=1000):
        path = Path(path)
        if not path.resolve().is_relative_to(self.storage):
            self._partial()
            return []
        with self._cache_lock:
            try:
                stat = path.stat()
            except FileNotFoundError:
                return []
            record = self._jsonl_cache.get(path)
            if record is None or record["inode"] != stat.st_ino or stat.st_size < record["offset"]:
                record = {"inode": stat.st_ino, "offset": 0, "items": deque(maxlen=maximum), "usage": []}
            with path.open("rb") as stream:
                stream.seek(record["offset"])
                while line := stream.readline():
                    if not line.endswith(b"\n"):
                        self._partial()
                        break
                    record["offset"] = stream.tell()
                    try:
                        item = json.loads(line)
                        record["items"].append(item)
                        if isinstance(item.get("usage"), dict):
                            record["usage"].append(item)
                    except ValueError:
                        self._partial()
            self._jsonl_cache[path] = record
            return clean(list(record["items"]))

    def runs(self, identifier):
        directory = self._path("runs", identifier)
        if not directory.is_dir():
            raise KeyError(identifier)
        result = self._json(directory / "result.json", {}, optional=True)
        context = self._json(directory / "context.json", {}, optional=True)
        job = next((j for j in self._jobs() if j.get("run_id") == identifier), None)
        events = self._jsonl(directory / "timeline.jsonl")
        legacy_events = self._jsonl(directory / "events.jsonl")
        events = events + legacy_events
        resources = self._jsonl(directory / "resources.jsonl")
        if not resources:
            resources = [item for item in events if item.get("type") == "resource.sample"]
        report = self.artifacts.register(directory / "report.md") if (directory / "report.md").is_file() else None
        usage_events = [event["usage"] for event in events if isinstance(event.get("usage"), dict)]
        return {"run_id": identifier, "state": result.get("status", (job or {}).get("state", "unknown")),
                "result": result, "context": context, "job": job, "events": events,
                "timeline": [event for event in events if event.get("stage")], "resources": resources,
                "model": context.get("model"), "requested_model": context.get("requested_model"),
                "effective_model": context.get("effective_model"), "reasoning": context.get("reasoning"),
                "service_tier": context.get("service_tier"), "report": report,
                "usage": {"observations": usage_events, "complete": False,
                          "coverage": "仅保留实际返回字段；历史及子代理覆盖可能不完整"},
                "candidate_ids": (job or {}).get("candidate_ids", []) or ([link["candidate_id"]] if (link := self._json(directory / "candidate-link.json", {}, optional=True)).get("candidate_id") else []),
                "outcome": "运行结束不表示科学验证通过"}

    def usage(self, date=None):
        date = date or self.now().date().isoformat()
        # Duration belongs to the Shanghai start date; reservation dates remain in the budget ledger.
        datetime.strptime(date, "%Y-%m-%d")
        result = self.jobs.usage(date) if self.jobs else {"date": date, "reserved": None, "started": None,
                    "available": None, "limit": None, "reserve_submit": None, "reserve_reconcile": None}
        observations, tokens = [], {}
        model_seconds, local_seconds = [], []
        model_runs = 0
        jobs = {job.get("run_id"): job for job in self._jobs()}
        for directory in (self.storage / "runs").iterdir() if (self.storage / "runs").exists() else []:
            if not directory.is_dir():
                continue
            run = {**jobs.get(directory.name, {}), **self._json(directory / "result.json", {}, optional=True)}
            if not run.get("started_at"):
                continue
            started = datetime.fromisoformat(run["started_at"])
            if started.astimezone(self.tz).date().isoformat() != date:
                continue
            kind = run.get("mode", run.get("kind", ""))
            local = kind.startswith("local_") or kind == "prepare_preview"
            elapsed = run.get("elapsed_seconds")
            if isinstance(elapsed, (int, float)):
                (local_seconds if local else model_seconds).append(elapsed)
            if local:
                continue
            model_runs += 1
            path = directory / "events.jsonl"
            self._jsonl(path)
            for event in self._jsonl_cache.get(path, {}).get("usage", []):
                observations.append({"run_id": directory.name, "type": event.get("type"),
                                     "at": event.get("at"), "usage": event["usage"]})
                # Codex turn.completed fields are per turn. Other event scopes remain raw observations.
                if event.get("type") == "turn.completed":
                    for key, value in event["usage"].items():
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            tokens[key] = tokens.get(key, 0) + value
        result.update(tokens=tokens or None, token_observations=clean(observations),
                      model_seconds=sum(model_seconds) if model_seconds else None,
                      local_seconds=sum(local_seconds) if local_seconds else None,
                      usage_complete=False, observed_model_runs=model_runs,
                      coverage="次数沿用预留日期；时长按北京时间启动日归属，仅统计结束报告。token 仅汇总已返回的 turn.completed 原始字段，缓存输入不重复相加，子代理及中断运行覆盖不完整。")
        return result

    def _jobs(self):
        state = self.control()
        jobs = state.get("jobs", [])
        return list(jobs.values()) if isinstance(jobs, dict) else jobs

    def _legacy_jobs(self):
        """Join old slot records with final results; absence of a report is not liveness."""
        records = {}
        for path in (self.storage / "runtime/slots").glob("*.json"):
            slot = self._json(path, {}, optional=True)
            if not slot:
                continue
            run_id = slot.get("run_id") or (Path(slot["run_dir"]).name if slot.get("run_dir") else None)
            key = run_id or path.stem
            records[key] = {**slot, "job_id": slot.get("slot", path.stem), "run_id": run_id}
        for directory in (self.storage / "runs").iterdir() if (self.storage / "runs").exists() else []:
            if not directory.is_dir():
                continue
            result = self._json(directory / "result.json", {}, optional=True)
            context = self._json(directory / "context.json", {}, optional=True)
            previous = records.get(directory.name, {})
            if not result and not context and not previous:
                continue
            records[directory.name] = {**previous, **result, "run_id": directory.name,
                                      "job_id": previous.get("job_id") or result.get("slot") or "legacy-" + directory.name,
                                      "mode": result.get("mode", previous.get("mode", context.get("mode"))),
                                      "task": context.get("task"), "model": context.get("model"),
                                      "reasoning": context.get("reasoning"), "service_tier": context.get("service_tier"),
                                      "config_revision": context.get("config_revision"), "stop_by": context.get("stop_by"),
                                      "requested_model": context.get("requested_model"), "has_result": bool(result)}
        items = []
        for record in records.values():
            status = record.get("status", "unknown")
            alive = identity_alive(record.get("pid"), record.get("pid_start"))
            if status in {"starting", "running", "cancel_requested"} and alive is not True:
                status = "unknown"
            started = record.get("started_at")
            seconds = None
            if started and record.get("stop_by"):
                seconds = max(0, int((datetime.fromisoformat(record["stop_by"]) - datetime.fromisoformat(started)).total_seconds()))
            items.append({**record, "state": status, "kind": record.get("mode"), "legacy": True,
                          "revision": 0, "created_at": started, "max_seconds": seconds,
                          "origin": "manual" if str(record["job_id"]).startswith("manual-") else "automatic",
                          "model": record.get("model"), "config_revision": record.get("config_revision"),
                          "process_alive": alive, "blocked_reason": "历史记录缺少可核实运行身份" if status == "unknown" else None,
                          "calls_model": record.get("mode") in {"optimize", "smoke", "submit", "reconcile"}})
        return items

    def list_jobs(self, state=None, cursor=0, limit=50):
        items = deepcopy(self._jobs())
        queued = sorted((item for item in items if item['state'] in {'queued', 'blocked'}),
                        key=lambda item: (0 if item['kind'] in {'submit', 'reconcile'} else
                                          2 if item.get('origin') == 'automatic' else 1,
                                          item['created_at']))
        for position, item in enumerate(queued, 1):
            item['queue_position'] = position
        run_ids = {item.get("run_id") for item in items if item.get("run_id")}
        job_ids = {item["job_id"] for item in items}
        items.extend(item for item in self._legacy_jobs() if item.get("run_id") not in run_ids and item["job_id"] not in job_ids)
        items.sort(key=lambda item: (item.get("created_at") or "", item["job_id"]), reverse=True)
        if state:
            items = [item for item in items if item["state"] == state]
        start, limit = int(cursor or 0), min(200, max(1, int(limit)))
        return {"items": [self._execution_view(item) for item in items[start:start + limit]],
                "next_cursor": str(start + limit) if start + limit < len(items) else None, "total": len(items)}

    def _execution_view(self, item):
        item = deepcopy(item)
        if item.get('started_at') and item['state'] in {'running', 'cancel_requested'}:
            item['elapsed_seconds'] = max(0, (self.now() - datetime.fromisoformat(item['started_at'])).total_seconds())
        return clean(item)

    def job(self, identifier):
        item = next((item for item in self._jobs() if item["job_id"] == identifier), None)
        if item is None:
            item = next((item for item in self._legacy_jobs() if item["job_id"] == identifier), None)
        if item is None:
            raise KeyError(identifier)
        return self._execution_view(item)

    def research(self):
        original = self._json(self.storage / "research/hypotheses.json", {}, optional=True)
        edits = self._json(self.storage / "console/research.json", {}, optional=True)
        revision = edits.get("revision", 0)
        edits = edits.get("overrides", edits)
        items = []
        for item in original.get("queue", []):
            title = item.get("hypothesis", item.get("title", ""))
            fingerprint = json.dumps([item.get("task"), title, item.get("source")], ensure_ascii=False)
            rid = item.get("id") or "hyp_" + hashlib.sha256(fingerprint.encode()).hexdigest()[:20]
            override = edits.get(rid, {})
            items.append({"id": rid, "title": title, "task": item.get("task"),
                          "status": override.get("status", item.get("status", "pending")),
                          "priority": override.get("priority", item.get("rank")),
                          "notes": override.get("notes", ""), "source": item.get("source"),
                          "expected_gain": item.get("expected_log_combined_gain_prior"),
                          "estimate_kind": "unmeasured_prior", "actual_gain": None,
                          "parent": item.get("parent"), "gate": item.get("gate"),
                          "experiment_ids": override.get("experiment_ids", item.get("experiment_ids", [])),
                          "enabled": override.get("enabled", True), "revision": override.get("revision", 0)})
        items.sort(key=lambda item: (item["priority"] is None, item["priority"] or 0))
        cursors = self._json(self.storage / "research/cursors.json", {}, optional=True)
        topics = cursors.get("topics", [])
        return {"items": clean(items), "revision": revision, "coverage": {"listed_topics": cursors.get("listed_topics"),
                    "full_text_topics": sum(topic.get("messages_fetched") is True for topic in topics) if topics else None,
                    "updated_at": cursors.get("updated_at"), "estimates_are_unmeasured_priors": True},
                "negative_results": clean(original.get("negative_results", {})),
                "updated_at": original.get("updated_at")}

    def _best(self, state):
        items = []
        for task in TASKS:
            cid = state.get("best", {}).get(task)
            if cid:
                try:
                    items.append(self._candidate(cid, state=state))
                    continue
                except KeyError:
                    self._partial()
            items.append({"task": task, "id": cid, "official_cost": None, "validation_status": "unknown", "improvement": None})
        return items

    def submissions(self):
        state = self.pipeline()
        best = self._best(state)
        items = sorted(state.get("submissions", {}).values(), key=lambda item: (item.get("date", ""), item.get("created_at", "")), reverse=True)
        now = self.now()
        today = now.date().isoformat()
        allowance = submission_allowance(state, self.config, now)
        quota_unit = "成功提交" if allowance["quota_basis"] == "successful_submissions" else "提交尝试"
        exhausted = allowance["remaining_today"] == 0
        unresolved = any(item.get("status") in {"upload_started", "submitted", "score_unknown"} and not item.get("submission_id") for item in items)
        costs = {item["task"]: item["official_cost"] for item in best}
        previous = state.get("last_submitted_costs", {})
        improvement = math.prod(previous[t] / costs[t] for t in TASKS) ** (1 / 3) if all(previous.get(t) and costs[t] for t in TASKS) else None
        before_deadline = now < datetime.fromisoformat(self.config["deadline"])
        known = [
            ("recorded_verification", all(item["validation_status"] == "PASS" for item in best), "三个组件具备已记录的完整官方验证"),
            ("improvement", improvement is not None and improvement > 1 + 1e-12, "相对上次提交组合存在改进"),
            ("window", allowance["window_open"], "优化结束后即可检查并提交改进" if allowance["policy"] == "after_optimization" else "当前处于配置的提交窗口"),
            ("deadline", before_deadline, "未过比赛截止"),
            ("daily_attempt", not exhausted, f"本地每日额度剩余 {allowance['remaining_today']} / {allowance['daily_limit']} 次{quota_unit}"),
            ("reconciliation", not unresolved, "没有缺少提交 ID 的不确定上传"),
        ]
        if allowance["policy"] in {"after_optimization", "daily_windows"}:
            known.append(("unsubmitted_combination", not any(item.get("status") in ATTEMPTED and item.get("selected") == state.get("best") for item in items), "当前最佳组合尚未尝试提交"))
        if allowance["policy"] == "daily_windows":
            known.append(("window_attempt", allowance.get("window_attempts", 0) == 0, "当前上传窗口尚未使用"))
        checks = [{"id": key, "passed": passed, "label": label} for key, passed, label in known]
        checks.extend([{"id": "full_integrity", "passed": None, "label": "执行时重新核验产物、来源、环境与 ZIP"},
                       {"id": "platform_recent", "passed": None, "label": "提交任务查询平台近期记录后决定是否上传"}])
        reference = next((item.get("token") or str(item.get("submission_id")) for item in items if item.get("submission_id")), None)
        for item in items:
            item["platform_score"] = item.get("public_score")
            item["quota_date"] = (submission_success_date(item, self.config)
                                  if allowance["quota_basis"] == "successful_submissions" and successful_submission_id(item)
                                  else submission_quota_date(item, self.config))
            item["quota_timezone"] = allowance["quota_timezone"]
            item["preview_stale"] = item.get("status") == "prepared" and (item.get("selected") != state.get("best") or (allowance["policy"] != "after_optimization" and item.get("date") != today))
        scored = []
        for item in items:
            score = item.get("public_score")
            if (not isinstance(score, (int, float)) or isinstance(score, bool)
                    or not math.isfinite(score)):
                continue
            receipt = item.get("receipt") if isinstance(item.get("receipt"), dict) else {}
            scored.append({
                "submission_id": item.get("submission_id"),
                "submitted_at": receipt.get("submittedAt") or receipt.get("createdAt")
                    or receipt.get("date") or item.get("reserved_at")
                    or item.get("created_at") or item.get("date"),
                "score_observed_at": item.get("updated_at"),
                "platform_score": score,
                "selected": item.get("selected"),
                "costs": item.get("costs"),
                "token": item.get("token"),
            })
        scored.sort(key=lambda item: (item.get("submitted_at") is None,
                                      item.get("submitted_at") or "",
                                      str(item.get("submission_id") or "")))
        previous_score = None
        for item in scored:
            item["previous_score"] = previous_score
            item["absolute_change"] = (item["platform_score"] - previous_score
                                       if previous_score is not None else None)
            item["relative_change"] = ((item["platform_score"] / previous_score) - 1
                                       if previous_score not in (None, 0) else None)
            previous_score = item["platform_score"]
        eligibility = {"checks": checks, "eligible": all(passed for _, passed, _ in known),
                       **allowance,
                       "submission_times": self.config.get("daily_submission_times", [self.config.get("daily_submission_time", "20:00")]),
                       "official_daily_limit": self.config.get("official_max_daily_submissions", 5),
                       "today_used": exhausted, "integrity_check_required": True}
        return {"items": clean(items), "score_history": clean(scored),
                "best": best, "eligibility": eligibility,
                "activity": self.submission_activity(eligibility, items),
                "combined_improvement": improvement, "reference_id": reference,
                "observed_at": datetime.now(timezone.utc).isoformat()}

    def submission_activity(self, eligibility, submissions):
        """Explain execution separately from eligibility and platform acceptance."""
        jobs = sorted((job for job in self._jobs() if job['kind'] == 'submit'),
                      key=lambda job: job['created_at'], reverse=True)
        pending = next((job for job in jobs if job['state'] in ACTIVE | {'queued', 'blocked'}), None)
        latest = pending or next(iter(jobs), {})
        activity = {'job_id': latest.get('job_id'), 'run_id': latest.get('run_id'),
                    'observed_at': latest.get('finished_at') or latest.get('started_at') or latest.get('created_at'),
                    'report': None, 'report_excerpt': None, 'blocked_reason': latest.get('blocked_reason')}
        if latest.get('run_id'):
            report = self._path('runs', latest['run_id']) / 'report.md'
            if report.is_file():
                activity['report'] = self.artifacts.register(report)
                # Quote the recorded conclusion; do not infer remote state from model prose.
                activity['report_excerpt'] = clean(report.read_text().strip().split('\n\n', 1)[0][:1200])
        if pending:
            state = pending['state']
            messages = {'queued': '提交请求已排队，尚未上传。', 'blocked': '提交请求正在等待条件满足，尚未开始执行。',
                        'starting': '提交任务正在启动，尚不能确认上传。', 'running': '提交任务正在检查或上传，结果以平台回执为准。',
                        'cancel_requested': '已请求停止提交任务，等待确认结果。', 'unknown': '提交任务的运行状态待核实。'}
            activity.update(code=state, message=messages[state], next_action='打开任务详情查看进度和等待原因。')
            return activity
        failures = {check['id'] for check in eligibility['checks'] if check['passed'] is False}
        explanations = [
            ('deadline', '比赛提交截止时间已过。', '可继续查看历史记录。'),
            ('reconciliation', '存在尚未确认结果的上传，暂不发起下一次。', '先查询平台并对账。'),
            ('unsubmitted_combination', '当前最佳组合已经尝试提交，不会重复上传。', '等待新的已验证改进；评分见提交台账。'),
            ('recorded_verification', '当前组合尚不具备三个任务的完整通过记录。', '完成验证后再提交。'),
            ('improvement', '当前组合相对上次提交没有新的成本改进。', '等待下一轮优化产生改进。'),
            ('daily_attempt', '本地当日提交额度已达到配置上限。', '等待配额重置后再检查。'),
            ('window_attempt', '当前上传窗口已经使用。', '等待下一提交窗口。'),
            ('window', '当前不在已配置的提交时段。', '等待下一提交窗口。'),
        ]
        for code, message, action in explanations:
            if code in failures:
                activity.update(code=code, message=message, next_action=action)
                return activity
        started, finished = latest.get('started_at'), latest.get('finished_at')
        recorded = any(item.get('reserved_at') and started and finished and
                       datetime.fromisoformat(started) <= datetime.fromisoformat(item['reserved_at']) <= datetime.fromisoformat(finished)
                       for item in submissions if item.get('status') in ATTEMPTED)
        if latest and finished and not recorded:
            activity.update(code='no_upload_recorded', message='最近提交任务已结束，但没有记录到该次上传。',
                            next_action='查看下面的运行结论；解决阻塞后可在提交中心重新请求提交。')
        else:
            trigger = ('下一轮优化结束后会自动检查' if eligibility.get('policy') == 'after_optimization'
                       else '调度器会在配置的上传窗口检查')
            activity.update(code='eligible', message='本地记录满足提交条件，当前没有待执行的提交请求。',
                            next_action=trigger + '；也可在提交中心请求提交。上传前仍需核验完整性及平台额度。')
        return activity

    def queue_status(self, jobs, scheduler, usage):
        now = self.now()
        control = self.control()
        occupied = set(control.get('slots', {})) | {path.stem for path in (self.storage / 'runtime/slots').glob('*.json')}
        upcoming = {'optimize': None, 'reconcile': None}
        for offset in (0, 1):
            day = now + timedelta(days=offset)
            windows = [('optimize', start, end) for start, end in self.config['optimize_windows']]
            windows.append(('reconcile', self.config['reconcile_time'], None))
            for kind, start, end in windows:
                hour, minute = map(int, start.split(':'))
                begins = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if end:
                    hour, minute = map(int, end.split(':'))
                    closes = day.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(minutes=5)
                else:
                    closes = begins + timedelta(hours=2)
                slot = f'{day.date().isoformat()}-{kind}' + (f'-{start.replace(":", "")}' if kind == 'optimize' else '')
                planned = max(begins, now)
                if slot not in occupied and planned < closes and planned < datetime.fromisoformat(self.config['deadline']):
                    if upcoming[kind] is None or planned < upcoming[kind]:
                        upcoming[kind] = planned
        queued = sum(job['state'] == 'queued' for job in jobs)
        blocked = sum(job['state'] == 'blocked' for job in jobs)
        active = sum(job['state'] in ACTIVE for job in jobs)
        if not scheduler.get('dispatch_enabled', True) or scheduler.get('process_alive') is not True:
            message = '调度器未运行或尚未确认身份，自动任务暂不会启动。'
        elif scheduler['paused']:
            message = '自动调度已暂停；恢复后会在可用时段检查任务。'
        elif now >= datetime.fromisoformat(self.config['deadline']):
            message = '已到比赛截止时间，不再创建自动任务。'
        elif queued or blocked:
            message = f'当前有 {queued} 项排队、{blocked} 项等待条件满足；同一时刻执行一项。'
        elif active:
            trigger = ('优化结束后会检查是否需要提交。' if self.config.get('submission_policy') == 'after_optimization'
                       else '到配置的上传窗口会检查是否需要提交。')
            message = '当前任务正在执行，后续没有已排队任务。' + trigger
        else:
            message = '当前没有排队任务。每个优化时段只创建一轮任务，本轮完成后等待下一时段，不会提前排满全天。'
        reservations = usage.get('reservations', [])
        def available(kind):
            if usage.get('available') is None:
                return None
            protected = sum(max(0, usage['reserve_' + mode] - sum(r['kind'] == mode for r in reservations))
                            for mode in ('submit', 'reconcile') if mode != kind)
            return max(0, usage['available'] - protected)
        return {'queued': queued, 'blocked': blocked, 'active': active, 'message': message,
                'next_optimization_at': upcoming['optimize'].isoformat() if upcoming['optimize'] else None,
                'next_reconcile_at': upcoming['reconcile'].isoformat() if upcoming['reconcile'] else None,
                'schedule_note': '计划检查时刻（北京时间）；实际启动还需调度开启、执行器空闲、预算和资源可用。',
                'model_available': usage.get('available'), 'optimization_available': available('optimize'),
                'submission_available': available('submit')}

    def scheduler(self):
        daemon = self._json(self.storage / "runtime/daemon.json", {}, optional=True)
        control = self.control()
        return {**daemon, "process_alive": identity_alive(daemon.get("pid"), daemon.get("pid_start")),
                "paused": bool(control.get("paused", control.get("scheduler", {}).get("paused", False))) or (self.storage / "runtime/PAUSED").exists(),
                "dispatch_enabled": control.get('scheduler', {}).get('dispatch_enabled', True),
                "console_enabled": (self.storage / "console/state.json").exists()}

    def overview(self):
        submissions = self.submissions()
        jobs = self._jobs()
        current = next((item for item in jobs if item.get("state") in ACTIVE), None)
        if current is None:
            legacy = sorted(self._legacy_jobs(), key=lambda item: item.get("started_at") or "", reverse=True)
            current = next((item for item in legacy if item["state"] in ACTIVE), None)
        sample = {}
        if current and current.get("run_id"):
            directory = self._path("runs", current["run_id"])
            timeline = self._jsonl(directory / "timeline.jsonl")
            stage = next((event for event in reversed(timeline) if event.get('type') == 'stage.started'), None)
            if stage and current['state'] == 'running':
                current.update(stage=stage.get('stage'), stage_message=stage.get('message'),
                               stage_observed_at=stage.get('at'))
            if current.get('started_at') and current['state'] in {'running', 'cancel_requested'}:
                current['elapsed_seconds'] = max(0, (self.now() - datetime.fromisoformat(current['started_at'])).total_seconds())
            samples = self._jsonl(directory / "resources.jsonl")
            if not samples:
                samples = [item for item in timeline if item.get("type") == "resource.sample"]
            if samples:
                sample = samples[-1]
        cfg = self.config
        control = self.control()
        active_cfg = next((item["config"] for item in control.get("configs", []) if item["revision"] == control.get("active_revision")), control.get("config", {}))
        cfg = {**cfg, **active_cfg}
        running_cfg = current['config'] if current and isinstance(current.get('config'), dict) else cfg
        usage = self.usage()
        latest_score = submissions["score_history"][-1] if submissions["score_history"] else {}
        alerts = []
        if submissions["eligibility"]["today_used"]:
            alerts.append({"source": "submission_ledger", "message": "本地当日提交额度已用尽", "observed_at": submissions["observed_at"], "href": "/submissions"})
        if current and current.get("state") == "unknown":
            alerts.append({"source": "runner", "message": "运行身份待核实；缺少结束记录不能证明仍在运行", "observed_at": submissions["observed_at"], "href": "/jobs"})
        scheduler = self.scheduler()
        task_resources = normalize_task_sample(sample, current, now=self.now())
        host_resources = self.resource_monitor.snapshot(gpu_ids=running_cfg['gpu_ids'])
        return {"current_job": clean(current), "best": submissions["best"],
                "combined_improvement": submissions["combined_improvement"], "reference_id": submissions["reference_id"],
                "platform_score": latest_score.get("platform_score"),
                "platform_score_submission_id": latest_score.get("submission_id"),
                "platform_score_at": latest_score.get("submitted_at"),
                "submission": submissions["eligibility"],
                "resources": {"cpu_cores": task_resources['cpu_cores'], "cpu_limit": running_cfg["cpu_limit"],
                              "rss_gib": task_resources['rss_gib'],
                              "memory_stop_gib": running_cfg["memory_stop_gib"], "memory_gib": running_cfg["memory_gib"],
                              "gpu": host_resources['gpu'], "gpu_ids": running_cfg["gpu_ids"],
                              "free_gib": host_resources['disk']['free_gib'],
                              "host": host_resources, "task": task_resources,
                              "observed_at": task_resources['observed_at'], "memory_scope": "进程树 RSS 求和，共享页可能重复计入"},
                "usage": usage, "scheduler": scheduler, "alerts": alerts,
                "submission_activity": submissions['activity'],
                "queue": self.queue_status(jobs + ([current] if current and current.get('legacy') else []), scheduler, usage),
                "next_job": next((item for item in jobs if item.get("state") in {"queued", "blocked"}), None)}
