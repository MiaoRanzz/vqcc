#!/usr/bin/env python3
"""Bounded local Codex runs and a project-only scheduler using an IANA timezone."""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def load_config(path):
    cfg = json.loads(Path(path).read_text())
    cfg['conda_env'] = os.environ.get('VQCC_CONDA_ENV', cfg['conda_env'])
    cfg['storage_root'] = os.environ.get('VQCC_STORAGE_ROOT', cfg['storage_root'])
    cfg['python_executable'] = os.environ.get('VQCC_ENV_PREFIX', str(Path(cfg['python_executable']).parent.parent)) + '/bin/python'
    if not (1 <= cfg['cpu_limit'] <= 20 and 0 < cfg['memory_stop_gib'] <= cfg['memory_gib'] <= 180):
        raise ValueError('Resource configuration exceeds approved limits')
    if not set(cfg['gpu_ids']).issubset({0, 1}):
        raise ValueError('Only GPUs 0 and 1 are authorized')
    ZoneInfo(cfg['timezone'])
    return cfg


def select_slot(cfg, now):
    """Return a single eligible slot; never catch up missed submission days."""
    now = now.astimezone(ZoneInfo(cfg['timezone']))
    if now >= dt.datetime.fromisoformat(cfg['deadline']):
        return None
    day = now.date().isoformat()
    def at(hhmm):
        return dt.datetime.combine(now.date(), dt.time.fromisoformat(hhmm), now.tzinfo)
    start = at(cfg['daily_submission_time'])
    if start <= now < start + dt.timedelta(minutes=cfg['submit_window_minutes']):
        return f'{day}-submit', 'submit', min(cfg['submit_timeout_seconds'], int((start + dt.timedelta(minutes=cfg['submit_window_minutes']) - now).total_seconds()))
    check = at(cfg['reconcile_time'])
    if check <= now < check + dt.timedelta(hours=2):
        return f'{day}-reconcile', 'reconcile', cfg['reconcile_timeout_seconds']
    for start_s, end_s in cfg['optimize_windows']:
        start, end = at(start_s), at(end_s)
        if start <= now < end - dt.timedelta(minutes=5):
            seconds = min(cfg['max_agent_seconds'], int((end - now).total_seconds()))
            seconds = min(seconds, int((dt.datetime.fromisoformat(cfg['deadline']) - now).total_seconds()))
            return f'{day}-optimize-{start_s.replace(":", "")}', 'optimize', seconds
    return None


def redact(text):
    text = re.sub(r'https?://[^\s"<>]+', lambda m: m[0].split('?')[0] + '?[redacted]' if '?' in m[0] else m[0], text)
    text = re.sub(r'''(?i)\bbearer\s+[^\s,"';}]+''', 'Bearer [redacted]', text)
    return re.sub(r'''(?ix)(["']?(?:api[_-]?key|access_token|refresh_token|client_secret|password|authorization)["']?\s*[:=]\s*)("[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''', r'\1"[redacted]"', text)


def event_summary(raw):
    """Do not persist tool arguments/results: uploads can contain signed secrets."""
    try:
        obj = json.loads(raw)
    except ValueError:
        return {'type': 'unstructured_output', 'bytes': len(raw)}
    result = {'type': obj.get('type', 'unknown')}
    if 'usage' in obj:
        result['usage'] = obj['usage']
    if 'error' in obj:
        result['error'] = redact(str(obj['error']))[:4000]
    item = obj.get('item', {})
    if isinstance(item, dict):
        result['item_type'] = item.get('type')
        for key in ('id', 'status', 'tool', 'server', 'exit_code'):
            if key in item:
                result[key] = item[key]
        if item.get('type') == 'agent_message':
            result['text'] = redact(item.get('text', ''))
    return result


def proc_table():
    result = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            result[int(entry.name)] = (int(fields[1]), int(fields[19]), max(0, int(fields[21])) * os.sysconf('SC_PAGE_SIZE'))
        except (OSError, ValueError, IndexError):
            continue
    return result


def tracked_processes(leader, known):
    table = proc_table()
    live = {pid for pid, birth in known.items() if pid in table and table[pid][1] == birth}
    if leader in table:
        live.add(leader)
    # execute() is a child subreaper: detached/orphaned grandchildren come here.
    live |= {pid for pid, (ppid, _, _) in table.items() if ppid == os.getpid()}
    while True:
        children = {pid for pid, (ppid, _, _) in table.items() if ppid in live}
        if children <= live:
            break
        live |= children
    for pid in live:
        known[pid] = table[pid][1]
    return live, sum(table[pid][2] for pid in live)


def stop_tree(proc, known):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        # The leader can exit before the first poll while its group remains alive.
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
        live, _ = tracked_processes(proc.pid, known)
        for pid in sorted(live, reverse=True):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        if sig == signal.SIGTERM:
            time.sleep(2)


def verify_environment(cfg):
    expected = Path(cfg['python_executable']).resolve()
    if Path(sys.executable).resolve() != expected or Path(sys.prefix).resolve() != expected.parent.parent:
        raise RuntimeError(f'Use Conda {cfg["conda_env"]} with {expected}; running {sys.executable}, prefix {sys.prefix}')


def execute(mode, cfg, config_path, seconds, slot_id, state_path):
    storage = Path(cfg['storage_root'])
    run_dir = storage / 'runs' / (dt.datetime.now(ZoneInfo(cfg['timezone'])).strftime('%Y%m%dT%H%M%S') + '-' + mode + '-' + uuid.uuid4().hex[:6])
    run_dir.mkdir(parents=True)
    now = dt.datetime.now(dt.timezone.utc)
    context = {
        'mode': mode, 'project_root': str(ROOT), 'config': str(config_path),
        'storage_root': str(storage), 'run_dir': str(run_dir),
        'python_executable': cfg['python_executable'], 'conda_env': cfg['conda_env'],
        'stop_by': (now + dt.timedelta(seconds=seconds - min(60, seconds // 5))).isoformat(),
        'cpu_total_limit': cfg['cpu_limit'], 'memory_gib_limit': cfg['memory_gib'],
        'memory_watchdog_stop_gib': cfg['memory_stop_gib'], 'gpu_ids': cfg['gpu_ids'],
        'publication_requires_review': True, 'new_paid_resources_authorized': False,
        'one_submission_per_shanghai_date': True,
    }
    write_json(run_dir / 'context.json', context)
    prompt = (ROOT / 'automation' / 'prompts' / (mode + '.md')).read_text()
    prompt += '\n\nRuntime context (authoritative for this invocation):\n' + json.dumps(context, ensure_ascii=False, indent=2)
    prompt += '\nThe user approved this bounded recurring workflow, local changes and daily improved submissions. Honor AGENTS.md and the skill. Read stop_by and leave a checkpoint before the deadline. Do not change schedules, limits, security settings, or publish anything. Never start detached workers. No new paid resources.\n'
    cmd = [cfg['codex_executable'], 'exec', '--approve-for-me', '--ephemeral', '--add-dir', str(storage), '-C', str(ROOT), '--json', '--color', 'never', '--output-last-message', str(run_dir / 'report.md'), '-']
    env = os.environ.copy()
    transport = storage / 'runtime' / 'transport-env.json'
    if transport.exists():
        allowed = {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'NODE_USE_ENV_PROXY'}
        env.update({k: v for k, v in json.loads(transport.read_text()).items() if k in allowed and isinstance(v, str)})
    env.update({'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1', 'CUDA_VISIBLE_DEVICES': ','.join(map(str, cfg['gpu_ids'])), 'VQCC_STORAGE_ROOT': str(storage), 'VQCC_CONFIG': str(config_path), 'PYTHONUNBUFFERED': '1'})
    cpus = sorted(os.sched_getaffinity(0))[:cfg['cpu_limit']]
    def child_setup():
        os.sched_setaffinity(0, cpus)
        # A killed supervisor must not leave the primary agent running indefinitely.
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)
    result = {'slot': slot_id, 'mode': mode, 'run_dir': str(run_dir), 'status': 'starting', 'started_at': now.isoformat(), 'cpu_affinity': cpus, 'memory_enforcement': 'aggregate RSS watchdog; no writable child cgroup'}
    write_json(state_path, result)
    started = time.monotonic()
    known = {}
    stopped = threading.Event()
    if ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError('Cannot enable Linux child subreaper for bounded process cleanup')
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=True, preexec_fn=child_setup)
    result.update(status='running', pid=proc.pid)
    write_json(state_path, result)
    def reader(stream, path, structured):
        with path.open('w') as log:
            for line in stream:
                log.write((json.dumps(event_summary(line), ensure_ascii=False) if structured else redact(line.rstrip())[:4000]) + '\n')
                log.flush()
    readers = [threading.Thread(target=reader, args=(proc.stdout, run_dir / 'events.jsonl', True), daemon=True), threading.Thread(target=reader, args=(proc.stderr, run_dir / 'stderr.log', False), daemon=True)]
    for reader_thread in readers:
        reader_thread.start()
    proc.stdin.write(prompt)
    proc.stdin.close()
    peak = 0
    stop_reason = None
    old_handlers = {}
    def interrupted(signum, frame):
        stopped.set()
    for sig in (signal.SIGTERM, signal.SIGINT):
        old_handlers[sig] = signal.signal(sig, interrupted)
    try:
        while proc.poll() is None:
            _, memory = tracked_processes(proc.pid, known)
            peak = max(peak, memory)
            if stopped.is_set():
                stop_reason = 'interrupted'
            elif time.monotonic() - started > seconds:
                stop_reason = 'time_budget'
            elif memory >= cfg['memory_stop_gib'] * GIB:
                stop_reason = 'memory_budget'
            elif shutil.disk_usage(storage).free < cfg['min_free_gib'] * GIB:
                stop_reason = 'disk_reserve'
            if stop_reason:
                stop_tree(proc, known)
                break
            time.sleep(0.5)
        proc.wait(timeout=10)
    finally:
        # Also clean any remaining detached descendants discovered during monitoring.
        stop_tree(proc, known)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    for reader_thread in readers:
        reader_thread.join(timeout=5)
    report = run_dir / 'report.md'
    if report.exists():
        report.write_text(redact(report.read_text()))
    result.update(status='completed' if proc.returncode == 0 and not stop_reason else 'failed', exit_code=proc.returncode, stop_reason=stop_reason, peak_sum_rss_gib=round(peak / GIB, 3), elapsed_seconds=round(time.monotonic() - started, 1), finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
    write_json(state_path, result)
    write_json(run_dir / 'result.json', result)
    return result


def run_daemon(cfg, config_path):
    """Own only this project's ticks. No global cron/service configuration."""
    runtime = Path(cfg['storage_root']) / 'runtime'
    stopped = threading.Event()
    tick = None
    def stop(signum, frame):
        stopped.set()
        if tick is not None and tick.poll() is None:
            tick.terminate()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    with (runtime / 'daemon.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        status = {'pid': os.getpid(), 'pid_start': proc_table()[os.getpid()][1], 'status': 'running', 'project_root': str(ROOT), 'config': str(config_path), 'started_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        write_json(runtime / 'daemon.json', status)
        while not stopped.is_set():
            now = dt.datetime.now(dt.timezone.utc)
            if now >= dt.datetime.fromisoformat(cfg['deadline']):
                status['status'] = 'expired'
                break
            status['heartbeat'] = now.isoformat()
            write_json(runtime / 'daemon.json', status)
            # The daemon itself was launched in the verified Conda interpreter.
            tick = subprocess.Popen([sys.executable, str(ROOT / 'automation/runner.py'), '--config', str(config_path), 'tick'], cwd=ROOT, preexec_fn=lambda: ctypes.CDLL(None).prctl(1, signal.SIGTERM))
            while tick.poll() is None:
                if stopped.wait(1):
                    tick.terminate()
                    try:
                        tick.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        known = {}
                        tracked_processes(tick.pid, known)
                        for pid in known:
                            try:
                                os.kill(pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                    break
            tick = None
            stopped.wait(max(1, 60 - time.time() % 60))
        if status['status'] != 'expired':
            status['status'] = 'stopped'
        status['stopped_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_json(runtime / 'daemon.json', status)
    return 0


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('VQCC_CONFIG', ROOT / 'automation/config.json')))
    parser.add_argument('mode', choices=['daemon', 'tick', 'status', 'dry-run', 'smoke', 'optimize', 'submit', 'reconcile'])
    parser.add_argument('--seconds', type=int)
    args = parser.parse_args()
    cfg = load_config(args.config)
    verify_environment(cfg)
    storage = Path(cfg['storage_root'])
    if not storage.is_dir():
        raise RuntimeError('Storage missing; provision it first. Do not silently write experiments to the system disk.')
    now = dt.datetime.now(ZoneInfo(cfg['timezone']))
    slot = select_slot(cfg, now)
    runtime = storage / 'runtime'
    runtime.mkdir(exist_ok=True)
    if args.mode == 'daemon':
        return run_daemon(cfg, args.config.resolve())
    if args.mode in ('dry-run', 'status'):
        states = []
        for path in sorted((runtime / 'slots').glob('*.json'))[-12:]:
            states.append(json.loads(path.read_text()))
        daemon = json.loads((runtime / 'daemon.json').read_text()) if (runtime / 'daemon.json').exists() else None
        if daemon:
            observed = proc_table().get(daemon['pid'])
            daemon['process_alive'] = observed is not None and observed[1] == daemon['pid_start']
        result = {'now': now.isoformat(), 'timezone': cfg['timezone'], 'eligible_slot': slot, 'config': str(args.config.resolve()), 'storage_free_gib': round(shutil.disk_usage(storage).free / GIB, 1), 'cpu_limit': cfg['cpu_limit'], 'memory_watchdog_gib': cfg['memory_stop_gib'], 'deadline': cfg['deadline'], 'paused': (runtime / 'PAUSED').exists(), 'daemon': daemon, 'recent_runs': states}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.mode == 'tick' and ((runtime / 'PAUSED').exists() or slot is None):
        return 0
    if args.mode != 'smoke' and now >= dt.datetime.fromisoformat(cfg['deadline']):
        print(json.dumps({'status': 'expired'}))
        return 0
    with (runtime / 'agent.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if args.mode != 'tick':
                print(json.dumps({'status': 'busy'}))
            return 0
        if args.mode == 'tick':
            slot_id, mode, seconds = slot
            state_path = runtime / 'slots' / (slot_id + '.json')
            if state_path.exists():
                return 0
        else:
            mode = args.mode
            seconds = args.seconds or (300 if mode == 'smoke' else cfg['submit_timeout_seconds'] if mode == 'submit' else cfg['reconcile_timeout_seconds'] if mode == 'reconcile' else cfg['max_agent_seconds'])
            slot_id = 'manual-' + now.strftime('%Y%m%dT%H%M%S') + '-' + mode
            state_path = runtime / 'slots' / (slot_id + '.json')
        if not 30 <= seconds <= cfg['max_agent_seconds']:
            raise ValueError('Run duration must be 30 seconds through the configured maximum')
        if shutil.disk_usage(storage).free < cfg['min_free_gib'] * GIB:
            raise RuntimeError('Insufficient storage reserve')
        result = execute(mode, cfg, args.config.resolve(), seconds, slot_id, state_path)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'status': 'error', 'error': redact(str(exc))}), file=sys.stderr)
        sys.exit(1)
