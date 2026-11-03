#!/usr/bin/env python3
"""Manage the project-only scheduler. Preview is the default; no system cron edits."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from runner import ROOT, load_config, proc_table, verify_environment, write_json


def running(runtime):
    path = runtime / 'daemon.json'
    if not path.exists():
        return None
    status = json.loads(path.read_text())
    process = proc_table().get(status.get('pid'))
    if process is None or process[1] != status.get('pid_start') or status.get('status') != 'running':
        return None
    if status.get('project_root') != str(ROOT):
        raise RuntimeError('Scheduler identity belongs to a different project root')
    return status


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'automation/config.json')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--install', action='store_true')
    group.add_argument('--remove', action='store_true')
    parser.add_argument('--start', action='store_true')
    args = parser.parse_args()
    cfg = load_config(args.config)
    verify_environment(cfg)
    storage = Path(cfg['storage_root'])
    runtime = storage / 'runtime'
    command = [str(ROOT / 'automation/launch.sh'), '--config', str(args.config.resolve()), 'daemon']
    policy = cfg.get('submission_policy', 'daily_window')
    submit_at = (None if policy == 'after_optimization' else
                 cfg['daily_submission_times'] if policy == 'daily_windows' else cfg['daily_submission_time'])
    if not args.install and not args.remove:
        print(json.dumps({'command': command, 'timezone': cfg['timezone'], 'optimize_windows': cfg['optimize_windows'], 'submission_policy': policy, 'max_daily_submissions': cfg.get('max_daily_submissions', 1), 'submit_at': submit_at, 'reconcile_at': cfg['reconcile_time'], 'system_services_changed': False}, indent=2))
        return
    if not storage.is_dir():
        raise RuntimeError('Provision the approved data directory first')
    runtime.mkdir(exist_ok=True)
    previous = running(runtime)
    if args.remove:
        if previous:
            os.kill(previous['pid'], signal.SIGTERM)
            for _ in range(50):
                if running(runtime) is None:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError('Scheduler has not stopped yet; inspect its running task before forcing termination')
        (runtime / 'schedule.json').unlink(missing_ok=True)
        print(json.dumps({'status': 'stopped', 'project': str(ROOT), 'system_services_changed': False}))
        return
    # Only transport settings needed by this host; no API keys or session IDs.
    allowed = {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'NODE_USE_ENV_PROXY'}
    transport = {k: os.environ[k] for k in allowed if k in os.environ}
    if transport:
        write_json(runtime / 'transport-env.json', transport)
        (runtime / 'transport-env.json').chmod(0o600)
    result = {'status': 'installed', 'project_root': str(ROOT), 'storage': str(storage), 'command': command, 'timezone': cfg['timezone'], 'submission_policy': policy, 'max_daily_submissions': cfg.get('max_daily_submissions', 1), 'submission_time': submit_at, 'system_services_changed': False, 'restart_note': 'This container has no init service. After a container restart, verify the mount/auth and run install_schedule.py --install --start again.'}
    write_json(runtime / 'schedule.json', result)
    if args.start and previous is None:
        env = os.environ.copy()
        # Request/session identifiers from an interactive tool must not outlive it.
        for key in tuple(env):
            if key.startswith('CODEX_') and key not in ('CODEX_HOME',):
                del env[key]
        with (runtime / 'scheduler.log').open('a') as log:
            child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, env=env)
        for _ in range(30):
            previous = running(runtime)
            if previous:
                break
            if child.poll() is not None:
                raise RuntimeError('Scheduler failed to start; inspect runtime/scheduler.log')
            time.sleep(0.5)
        if previous is None:
            raise RuntimeError('Scheduler did not report readiness; inspect runtime/scheduler.log')
    result['running'] = previous is not None
    if previous:
        result['pid'] = previous['pid']
    write_json(runtime / 'schedule.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
