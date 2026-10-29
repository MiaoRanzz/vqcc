"""Real-process regression tests; fake agents never contact a model or Kaggle."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG = json.loads((ROOT / "automation/config.json").read_text())


def process_identity(pid):
    try:
        parts = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {"state": parts[0], "start": int(parts[19])}
    except (OSError, ValueError, IndexError):
        return None


def alive(pid, start=None):
    process = process_identity(pid)
    return bool(process and process["state"] != "Z" and (start is None or process["start"] == start))


def cleanup_records(records):
    for record in records:
        if alive(record["pid"], record.get("start")):
            try:
                os.kill(record["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass


def isolated_env():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("VQCC_") and not key.startswith("CODEX_")}
    env["VQCC_ENV_PREFIX"] = sys.prefix
    env["VQCC_CONDA_ENV"] = "vqcc"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def global_cron_snapshot():
    paths = [Path("/etc/crontab"), *Path("/etc/cron.d").glob("*")]
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


@unittest.skipUnless(sys.platform == "linux", "Linux process supervision")
class ProcessRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vqcc-process-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.storage = self.base / "storage"
        (self.storage / "runtime").mkdir(parents=True)
        self.config = dict(BASE_CONFIG, storage_root=str(self.storage),
                           python_executable=sys.executable, min_free_gib=0,
                           cpu_limit=1, memory_gib=1, memory_stop_gib=0.8)
        self.config_path = self.base / "config.json"
        self.children_path = self.storage / "children.json"
        self.fake = self.base / "fake-codex"
        self.config["codex_executable"] = str(self.fake)

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def run_supervisor_case(self, *, detached, timeout):
        """Launch a fake agent that exits before its child, or exceeds its budget."""
        sleeper = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
        self.fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent(f"""
            import json,os,signal,subprocess,sys,time
            from pathlib import Path
            sys.stdin.read()
            child = subprocess.Popen([sys.executable, '-c', {sleeper!r}],
                                     start_new_session={detached!r},
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
            def identity(pid):
                fields = Path('/proc/' + str(pid) + '/stat').read_text().rsplit(')',1)[1].split()
                return {{'pid': pid, 'start': int(fields[19])}}
            Path({str(self.children_path)!r}).write_text(json.dumps([identity(os.getpid()), identity(child.pid)]))
            report = Path(sys.argv[sys.argv.index('--output-last-message') + 1])
            report.write_text('Fake process test, no model invocation.\\n')
            if {timeout!r}:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                time.sleep(60)
        """))
        self.fake.chmod(0o700)
        self.write_config()
        # Isolate the subreaper: it must never adopt or kill unrelated test-runner children.
        driver = textwrap.dedent(f"""
            import json,sys
            from pathlib import Path
            sys.path.insert(0, {str(ROOT / 'automation')!r})
            from runner import execute,load_config
            path=Path({str(self.config_path)!r})
            cfg=load_config(path)
            result=execute('smoke',cfg,path,{0.4 if timeout else 5},'test-slot',
                           Path(cfg['storage_root'])/'runtime'/'result.json')
            print(json.dumps(result))
        """)
        command = [sys.executable, "-c", driver]
        started = time.monotonic()
        try:
            result = subprocess.run(command, env=isolated_env(), cwd=ROOT,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(result.stdout)
            self.assertEqual(evidence["status"], "failed" if timeout else "completed")
            self.assertEqual(evidence["stop_reason"], "time_budget" if timeout else None)
            records = json.loads(self.children_path.read_text())
            self.assertTrue(all(not alive(item["pid"], item["start"]) for item in records), records)
            self.assertLess(time.monotonic() - started, 15)
        finally:
            if self.children_path.exists():
                cleanup_records(json.loads(self.children_path.read_text()))

    def test_early_agent_exit_cleans_same_session_orphan(self):
        self.run_supervisor_case(detached=False, timeout=False)

    def test_early_agent_exit_cleans_setsid_orphan(self):
        self.run_supervisor_case(detached=True, timeout=False)

    def test_timeout_kills_agent_and_setsid_child_ignoring_term(self):
        self.run_supervisor_case(detached=True, timeout=True)

    def test_project_daemon_exclusive_start_and_stop_without_global_services(self):
        marker = self.storage / "model-was-called"
        self.fake.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\nraise SystemExit(99)\n")
        self.fake.chmod(0o700)
        (self.storage / "runtime/PAUSED").touch()
        self.write_config()
        global_before = global_cron_snapshot()
        env = isolated_env()
        installer = [sys.executable, str(ROOT / "automation/install_schedule.py"),
                     "--config", str(self.config_path)]
        pid = None
        birth = None
        try:
            installed = subprocess.run(installer + ["--install", "--start"], env=env,
                                       cwd=ROOT, capture_output=True, text=True, timeout=25)
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            info = json.loads(installed.stdout)
            self.assertTrue(info["running"])
            self.assertFalse(info["system_services_changed"])
            pid = info["pid"]
            state_path = self.storage / "runtime/daemon.json"
            original = json.loads(state_path.read_text())
            birth = original["pid_start"]
            self.assertTrue(alive(pid, birth))

            # A competing daemon must exit without replacing the current PID/state.
            second = subprocess.run([sys.executable, str(ROOT / "automation/runner.py"),
                                     "--config", str(self.config_path), "daemon"],
                                    env=env, cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(json.loads(state_path.read_text())["pid"], pid)
            repeated = subprocess.run(installer + ["--install", "--start"], env=env,
                                      cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertEqual(json.loads(repeated.stdout)["pid"], pid)

            removed = subprocess.run(installer + ["--remove"], env=env, cwd=ROOT,
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
            deadline = time.monotonic() + 3
            while alive(pid, birth) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(alive(pid, birth))
            self.assertEqual(json.loads(state_path.read_text())["status"], "stopped")
            self.assertFalse((self.storage / "runtime/schedule.json").exists())
            self.assertFalse(marker.exists(), "Paused daemon must never invoke even the fake model")
            self.assertEqual(global_cron_snapshot(), global_before)
        finally:
            if pid is not None and alive(pid, birth):
                try:
                    subprocess.run(installer + ["--remove"], env=env, cwd=ROOT,
                                   capture_output=True, text=True, timeout=30)
                finally:
                    cleanup_records([{"pid": pid, "start": birth}])


if __name__ == "__main__":
    unittest.main()
