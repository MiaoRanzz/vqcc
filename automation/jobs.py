"""Persistent console queue and control transactions for the existing runner.

The short control lock owns queue/config/budget decisions. The runner's existing
agent.lock owns execution. HTTP never takes the pipeline's verification lock.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import uuid
from zoneinfo import ZoneInfo

try:
    from .model_config import MODEL_KINDS, generator_revision, imported_model
    from .events import now_string
except ImportError:
    from model_config import MODEL_KINDS, generator_revision, imported_model
    from events import now_string

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3
ACTIVE = {'starting', 'running', 'cancel_requested', 'unknown'}
QUEUED = {'queued', 'blocked'}
LOCAL_KINDS = {'local_experiment', 'local_validate', 'local_promote', 'prepare_preview'}
CONFIG_FIELDS = {'model', 'reasoning', 'service_tier', 'daily_model_limit', 'reserve_submit',
                 'reserve_reconcile', 'max_agent_seconds', 'cpu_limit', 'memory_gib',
                 'memory_stop_gib', 'gpu_ids', 'min_free_gib'}
PARAMETERS = {
    'dqi': {'stack_cap': (1, 1, 35)},
    'invsqrt': {'delta_bits': (14, 2, 20), 'coef_bits': (17, 3, 30),
                'square_bits': (28, 3, 40), 'product_bits': (28, 3, 40), 'result_bits': (29, 3, 40)},
    'dfthcsos': {'brot': (12, 1, 30), 'source_brot': (12, 1, 30), 'batch_size': (8, 1, 75),
                 'prefix_bits': (0, 0, 20)},
}


class ControlError(RuntimeError):
    def __init__(self, code, message, status=409, field_errors=None, current_revision=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.field_errors, self.current_revision = field_errors or {}, current_revision


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    with tmp.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else int(fields[19])
    except FileNotFoundError:
        return None


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]+', value) is not None


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class Jobs:
    def __init__(self, config_path, initialize=False, clock=None):
        self.config_path = Path(config_path).resolve()
        self.base = json.loads(self.config_path.read_text())
        self.storage = Path(os.environ.get('VQCC_STORAGE_ROOT', self.base['storage_root']))
        self.directory = self.storage / 'console'
        self.path = self.directory / 'state.json'
        self.clock = clock or (lambda: datetime.now(ZoneInfo(self.base['timezone'])))
        self._schema = None
        self._defaults = None
        self._dataset_cache = None
        if initialize:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self.transaction() as state:
                pass

    def now(self):
        return self.clock().astimezone(ZoneInfo(self.base['timezone']))

    def defaults(self):
        if self._defaults is not None:
            return dict(self._defaults)
        values = {key: self.base[key] for key in CONFIG_FIELDS if key in self.base}
        values.update(imported_model(self.base))
        values.update(daily_model_limit=self.base.get('daily_model_limit', 6),
                      reserve_submit=self.base.get('reserve_submit', 1),
                      reserve_reconcile=self.base.get('reserve_reconcile', 1))
        self._defaults = dict(values)
        return values

    def initial(self):
        stamp = now_string()
        reservations = {}
        # Import only known top-level startup evidence, once, without inventing usage.
        for path in sorted((self.storage / 'runtime/slots').glob('*.json')):
            item = json.loads(path.read_text())
            if not item.get('started_at') or item.get('mode') not in MODEL_KINDS:
                continue
            run = item.get('run_dir', path.stem)
            day = datetime.fromisoformat(item['started_at']).astimezone(ZoneInfo(self.base['timezone'])).date().isoformat()
            reservations[run] = {'job_id': None, 'kind': item['mode'], 'budget_date': day,
                                 'reserved_at': item['started_at'], 'started_at': item['started_at'],
                                 'imported': True, 'run_id': Path(run).name}
        return {'schema_version': 1, 'revision': 1, 'updated_at': stamp,
                'active_revision': 1, 'configs': [{'revision': 1, 'created_at': stamp, 'config': self.defaults()}],
                'scheduler': {'paused': (self.storage / 'runtime/PAUSED').exists(), 'dispatch_enabled': True},
                'jobs': {}, 'operations': {}, 'reservations': reservations, 'slots': {}}

    def snapshot(self):
        return json.loads(self.path.read_text()) if self.path.exists() else self.initial()

    @contextmanager
    def transaction(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / 'control.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            state = self.snapshot()
            before = fingerprint(state)
            yield state
            if not self.path.exists() or fingerprint(state) != before:
                state['revision'] += 1
                state['updated_at'] = now_string()
                atomic_json(self.path, state)

    def _active_config(self, state):
        return next(item['config'] for item in state['configs'] if item['revision'] == state['active_revision'])

    def _operation(self, state, key, action, body, execute):
        if not key or len(key) > 200:
            raise ControlError('INVALID_PARAMETERS', '需要幂等操作 ID', 422)
        digest = fingerprint({'action': action, 'body': body})
        prior = state['operations'].get(key)
        if prior:
            if prior['fingerprint'] != digest:
                raise ControlError('STATE_CONFLICT', '相同幂等键的请求内容不同')
            return prior['result']
        result = execute()
        result = {**result, 'operation_id': 'op_' + uuid.uuid4().hex, 'observed_at': now_string()}
        state['operations'][key] = {'fingerprint': digest, 'action': action, 'at': now_string(), 'result': result}
        return result

    def dataset(self):
        path = ROOT / 'sample_submission/dfthcsos/submission.npz'
        if not path.exists():
            return None
        stat = path.stat()
        identity = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        if self._dataset_cache and self._dataset_cache[0] == identity:
            return dict(self._dataset_cache[1])
        import numpy as np
        with np.load(path, allow_pickle=False) as data:
            shape = data['angle_words'].shape
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        dataset = {'id': 'official-reference', 'name': '官方参考分解', 'num_bits': (shape[0] - 1).bit_length(),
                   'source_brot': 12, 'sha256': digest}
        self._dataset_cache = (identity, dataset)
        return dict(dataset)

    def parameter_schemas(self):
        revision = generator_revision()
        dataset = self.dataset()
        if self._schema is None or self._schema['generator_revision'] != revision or self._schema['datasets'] != ([dataset] if dataset else []):
            tasks = {task: {'fields': {key: {'type': 'integer', 'default': default,
                                           'minimum': low, 'maximum': high}
                                      for key, (default, low, high) in values.items()}}
                     for task, values in PARAMETERS.items()}
            tasks['invsqrt']['constraints'] = ['delta_bits < coef_bits']
            tasks['dfthcsos']['constraints'] = ['prefix_bits = 0 或 2..num_bits', 'ANGLE 工作位总数 <= 128', 'source_brot 与数据源一致']
            if dataset:
                tasks['dfthcsos']['fields']['prefix_bits']['maximum'] = dataset['num_bits']
            self._schema = {'schema_version': 1, 'generator_revision': revision, 'tasks': tasks,
                            'datasets': [dataset] if dataset else [],
                            'model_support': {'status': 'unconfirmed', 'message': '使用项目请求配置；账户可用性在 CLI 启动时确认，不自动替换模型。'}}
        return self._schema

    def normalize_request(self, request, config=None):
        config = config or self._active_config(self.snapshot())
        allowed = {'kind', 'task', 'parent_candidate_id', 'parameters', 'dataset_id', 'hypothesis',
                   'max_seconds', 'validate', 'model', 'reasoning', 'service_tier', 'research_id',
                   'candidate_id', 'robustness', 'allow_subagents', 'generator_revision'}
        unknown = set(request) - allowed
        if unknown:
            raise ControlError('INVALID_PARAMETERS', '未知字段: ' + ', '.join(sorted(unknown)), 422)
        result = dict(request)
        kind = result.get('kind')
        if kind not in MODEL_KINDS | LOCAL_KINDS:
            raise ControlError('INVALID_PARAMETERS', '不支持的作业类型', 422)
        seconds = result.setdefault('max_seconds', min(1200, config['max_agent_seconds']))
        if type(seconds) is not int or not 30 <= seconds <= config['max_agent_seconds']:
            raise ControlError('INVALID_PARAMETERS', '运行时长需为 30 秒至当前单次上限', 422, {'max_seconds': '超出范围'})
        for key in ('candidate_id', 'parent_candidate_id', 'research_id'):
            if result.get(key) is not None and not identifier(result[key]):
                raise ControlError('INVALID_PARAMETERS', f'{key} 不是有效 ID', 422)
        task = result.get('task')
        if task not in PARAMETERS and task not in (None, 'auto'):
            raise ControlError('INVALID_PARAMETERS', '未知题目', 422)
        for key in ('validate', 'robustness', 'allow_subagents'):
            if key in result and type(result[key]) is not bool:
                raise ControlError('INVALID_PARAMETERS', f'{key} 必须是布尔值', 422)
        if kind == 'local_experiment':
            if result.get('validate') is False:
                raise ControlError('INVALID_PARAMETERS', '可行优化必须完成官方验证，不能仅生成与初筛',
                                   422, {'validate': '完整官方验证不可关闭'})
            result['validate'] = True
            if task not in PARAMETERS:
                raise ControlError('INVALID_PARAMETERS', '请选择实验题目', 422)
            schema = self.parameter_schemas()
            supplied = result.get('parameters', {})
            if not isinstance(supplied, dict) or set(supplied) - set(PARAMETERS[task]):
                raise ControlError('INVALID_PARAMETERS', '未知生成参数', 422)
            params = {}
            for key, field in schema['tasks'][task]['fields'].items():
                value = supplied.get(key, field['default'])
                if type(value) is not int or not field['minimum'] <= value <= field['maximum']:
                    raise ControlError('INVALID_PARAMETERS', f'{key} 超出允许范围', 422, {key: '超出范围'})
                params[key] = value
            if task == 'invsqrt' and params['delta_bits'] >= params['coef_bits']:
                raise ControlError('INVALID_PARAMETERS', 'delta_bits 必须小于 coef_bits', 422)
            if task == 'dfthcsos':
                dataset_id = result.setdefault('dataset_id', 'official-reference')
                datasets = {item['id']: item for item in schema['datasets']}
                if dataset_id not in datasets:
                    raise ControlError('INVALID_PARAMETERS', '数据集未注册', 422)
                dataset = datasets[dataset_id]
                n, p = dataset['num_bits'], params['prefix_bits']
                if p == 1 or params['source_brot'] != dataset['source_brot']:
                    raise ControlError('INVALID_PARAMETERS', 'prefix_bits 必须为 0 或至少 2；source_brot 须匹配来源', 422)
                width = n + params['brot'] * params['batch_size'] + (1 + max(p - 2, n - p) if p else n - 1)
                if width > 128:
                    raise ControlError('INVALID_PARAMETERS', f'ANGLE 需要 {width} qubits，超过 128', 422)
                result['dataset_sha256'] = dataset['sha256']
            result['parameters'] = params
            if not result.get('parent_candidate_id'):
                result['parent_candidate_id'] = self._pipeline_state().get('best', {}).get(task)
            if not isinstance(result.get('hypothesis'), str) or not result['hypothesis'].strip():
                raise ControlError('INVALID_PARAMETERS', '请填写实验假设', 422)
            supplied_revision = result.get('generator_revision')
            if supplied_revision and supplied_revision != schema['generator_revision']:
                raise ControlError('STATE_CONFLICT', '生成器已变化，请重新预检')
            result.update(generator_revision=schema['generator_revision'], schema_version=1)
        if kind in {'local_validate', 'local_promote'} and not result.get('candidate_id'):
            raise ControlError('INVALID_PARAMETERS', '请指定候选 ID', 422)
        for key in ('candidate_id', 'parent_candidate_id'):
            if result.get(key):
                path = self.storage / 'experiments' / result[key] / 'candidate.json'
                if not path.exists():
                    raise ControlError('INVALID_PARAMETERS', '候选不存在', 422)
                candidate = json.loads(path.read_text())
                if task in PARAMETERS and candidate['task'] != task:
                    raise ControlError('INVALID_PARAMETERS', '候选与题目不匹配', 422)
                if key == 'candidate_id':
                    result['task'] = candidate['task']
        if result.get('robustness') and result.get('task') != 'dqi':
            raise ControlError('INVALID_PARAMETERS', '仅 DQI 支持独立随机复核', 422)
        if kind in MODEL_KINDS:
            for key in ('model', 'reasoning', 'service_tier'):
                result[key] = result.get(key) or config[key]
            if not isinstance(result['model'], str) or not result['model'].strip():
                raise ControlError('CAPABILITY_UNAVAILABLE', '未配置模型，请先设置项目模型', 422)
            if result['reasoning'] not in {'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}:
                raise ControlError('INVALID_PARAMETERS', '未知推理强度', 422)
            if result['service_tier'] not in {'default', 'priority', 'flex'}:
                raise ControlError('INVALID_PARAMETERS', '未知服务档位', 422)
        return result

    def usage(self, date=None, state=None):
        state = state or self.snapshot()
        date = date or self.now().date().isoformat()
        values = [item for item in state['reservations'].values() if item['budget_date'] == date and not item.get('released_at')]
        cfg = self._active_config(state)
        return {'date': date, 'reserved': len(values), 'started': sum(bool(item.get('started_at')) for item in values),
                'available': max(0, cfg['daily_model_limit'] - len(values)), 'limit': cfg['daily_model_limit'],
                'reserve_submit': cfg['reserve_submit'], 'reserve_reconcile': cfg['reserve_reconcile'],
                'reservations': values, 'tokens': None, 'coverage': '已知顶层启动证据；token 未完整统计，次数不是费用或 token 硬上限'}

    def _budget_reason(self, job, state):
        if job['kind'] not in MODEL_KINDS:
            return None
        usage = self.usage(state=state)
        cfg = self._active_config(state)
        values = usage['reservations']
        protected = sum(max(0, cfg['reserve_' + mode] - sum(item['kind'] == mode for item in values))
                        for mode in ('submit', 'reconcile') if job['kind'] != mode)
        if len(values) + 1 > cfg['daily_model_limit'] - protected:
            return 'DAILY_MODEL_BUDGET_EXHAUSTED'
        return None

    def _pipeline_state(self):
        path = self.storage / 'state/pipeline.json'
        return json.loads(path.read_text()) if path.exists() else {'best': {}, 'submissions': {}}

    def submission_precheck(self):
        try:
            from .submission_policy import submission_skip_reason
        except ImportError:
            from submission_policy import submission_skip_reason
        state = self._pipeline_state()
        ledger_reason = submission_skip_reason(state, None, self.base, self.now())
        if ledger_reason:
            return 'SUBMISSION_NEEDS_RECONCILIATION' if ledger_reason == 'previous_submission_needs_reconciliation' else ledger_reason.upper()
        costs = {}
        for task, cid in state.get('best', {}).items():
            candidate_path = self.storage / 'experiments' / cid / 'candidate.json'
            if not candidate_path.exists():
                return 'EVIDENCE_STALE'
            candidate = json.loads(candidate_path.read_text())
            record = candidate.get('verification')
            if not record:
                return 'EVIDENCE_STALE'
            report_path = candidate_path.parent / record['report']
            if not report_path.exists():
                return 'EVIDENCE_STALE'
            costs[task] = json.loads(report_path.read_text()).get('score')
        previous = state.get('last_submitted_costs')
        if set(costs) != set(PARAMETERS) or not previous or any(not costs[t] for t in PARAMETERS):
            return 'EVIDENCE_STALE'
        reason = submission_skip_reason(state, costs, self.base, self.now())
        return reason.upper() if reason else None

    def _window_reason(self, job, state):
        now = self.now()
        deadline = datetime.fromisoformat(self.base['deadline'])
        if now + timedelta(seconds=job['max_seconds'] + 10) > deadline:
            return 'DEADLINE'
        if self.base.get('submission_policy') == 'after_optimization':
            return None
        if self.base.get('submission_policy') == 'daily_windows':
            try:
                from .submission_policy import submission_windows
            except ImportError:
                from submission_policy import submission_windows
            windows = submission_windows(self.base, now)
            if job['kind'] == 'submit':
                return None if any(start <= now < end for start, end in windows) else 'SUBMISSION_WINDOW'
            if job['kind'] == 'reconcile':
                return None
            end = now + timedelta(seconds=job['max_seconds'] + 10)
            pending = any(s['status'] in {'upload_started', 'submitted', 'score_unknown'}
                          for s in self._pipeline_state().get('submissions', {}).values())
            # Include adjacent dates so overnight jobs cannot occupy the next
            # morning's submission window, or a window crossing midnight.
            for offset in (-1, 0, 1):
                date = now + timedelta(days=offset)
                protected = [(start - timedelta(minutes=35), finish)
                             for start, finish in submission_windows(self.base, date)]
                hour, minute = map(int, self.base['reconcile_time'].split(':'))
                reconcile_at = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                completed = any(j['kind'] == 'reconcile' and j['state'] in {'completed', 'failed', 'cancelled', 'timed_out', 'resource_stopped'}
                                and j.get('budget_date') == date.date().isoformat() for j in state['jobs'].values())
                reconcile_end = reconcile_at + timedelta(seconds=self.base['reconcile_timeout_seconds'])
                if pending and not completed:
                    reconcile_end = max(reconcile_end, reconcile_at + timedelta(hours=2))
                protected.append((reconcile_at - timedelta(minutes=10), reconcile_end))
                if any(now < finish and end > start for start, finish in protected):
                    return 'PROTECTED_WINDOW'
            return None
        def at(value):
            hour, minute = map(int, value.split(':'))
            return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        submit_at = at(self.base['daily_submission_time'])
        submit_end = submit_at + timedelta(minutes=self.base['submit_window_minutes'])
        reconcile_at = at(self.base['reconcile_time'])
        reconcile_last_start = reconcile_at + timedelta(hours=2)
        if job['kind'] == 'submit':
            return None if submit_at <= now < submit_end else 'SUBMISSION_WINDOW'
        if job['kind'] == 'reconcile':
            return None if reconcile_at <= now < reconcile_last_start else 'RECONCILE_WINDOW'
        protect_start = submit_at - timedelta(minutes=35)
        protect_end = reconcile_at + timedelta(seconds=self.base['reconcile_timeout_seconds'])
        completed_today = any(j['kind'] == 'reconcile' and j['state'] in {'completed', 'failed', 'cancelled', 'timed_out', 'resource_stopped'}
                              and j.get('budget_date') == now.date().isoformat() for j in state['jobs'].values())
        pending = any(s['status'] in {'upload_started', 'submitted', 'score_unknown'} for s in self._pipeline_state().get('submissions', {}).values())
        if pending and not completed_today:
            protect_end = max(protect_end, reconcile_last_start)
        end = now + timedelta(seconds=job['max_seconds'] + 10)
        if now < protect_end and end > protect_start:
            return 'PROTECTED_WINDOW'
        if now >= protect_end:
            tomorrow = protect_start + timedelta(days=1)
            if end > tomorrow:
                return 'PROTECTED_WINDOW'
        return None

    def _blocked_reason(self, job, state):
        cfg = self._active_config(state)
        frozen = job.get('config', cfg)
        if any(frozen[key] > cfg[key] for key in ('cpu_limit', 'memory_gib', 'memory_stop_gib')) or not set(frozen['gpu_ids']) <= set(cfg['gpu_ids']):
            return 'CONFIG_RESOURCE_LIMIT'
        if job['max_seconds'] > cfg['max_agent_seconds']:
            return 'CONFIG_DURATION_LIMIT'
        if not state['scheduler']['dispatch_enabled']:
            return 'SCHEDULER_STOPPED'
        if job.get('origin') == 'automatic' and state['scheduler']['paused']:
            return 'SCHEDULER_PAUSED'
        if job['kind'] == 'submit':
            reason = self.submission_precheck()
            if reason:
                return reason
        if job.get('generator_revision') and job['generator_revision'] != generator_revision():
            return 'GENERATOR_CHANGED'
        if job.get('dataset_sha256'):
            dataset = self.dataset()
            if dataset is None or dataset['sha256'] != job['dataset_sha256']:
                return 'DATASET_CHANGED'
        if shutil.disk_usage(self.storage).free < max(cfg['min_free_gib'], frozen['min_free_gib']) * GIB:
            return 'INSUFFICIENT_DISK'
        return self._window_reason(job, state) or self._budget_reason(job, state)

    def preview(self, request):
        state = self.snapshot()
        cfg = self._active_config(state)
        job = self.normalize_request(request, cfg)
        job.update(config=cfg, origin='manual')
        reason = self._blocked_reason(job, state)
        if not reason and any(item['state'] in ACTIVE for item in state['jobs'].values()):
            reason = 'WAITING_FOR_CURRENT_JOB'
        return {'request': {k: v for k, v in job.items() if k not in {'config', 'origin'}},
                'config_revision': state['active_revision'], 'calls_model': job['kind'] in MODEL_KINDS,
                'blocked_reason': reason, 'usage': self.usage(state=state),
                'max_seconds': job['max_seconds'], 'valid': True,
                'budget_rule': '开始前预留一次，启动后失败或取消仍计次数' if job['kind'] in MODEL_KINDS else '不调用模型，不占模型次数'}

    def enqueue(self, request, key, origin='manual', slot_id=None, expires_at=None, *, trigger_job_id=None, trigger_run_id=None):
        with self.transaction() as state:
            def create():
                cfg = self._active_config(state)
                job = self.normalize_request(request, cfg)
                commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
                jid = 'job_' + uuid.uuid4().hex
                job.update(job_id=jid, revision=1, origin=origin, state='queued', created_at=now_string(),
                           config_revision=state['active_revision'], config=dict(cfg), source_revision=commit,
                           slot_id=slot_id, expires_at=expires_at, run_id=None, started_at=None, finished_at=None,
                           trigger_job_id=trigger_job_id, trigger_run_id=trigger_run_id)
                reason = self._blocked_reason(job, state)
                job['blocked_reason'] = reason
                if reason:
                    job['state'] = 'blocked'
                state['jobs'][jid] = job
                if slot_id:
                    state['slots'][slot_id] = jid
                return {**job, 'status': job['state']}
            body = {'request': request, 'origin': origin, 'slot_id': slot_id}
            if trigger_job_id is not None or trigger_run_id is not None:
                body.update(trigger_job_id=trigger_job_id, trigger_run_id=trigger_run_id)
            return self._operation(state, key, 'enqueue', body, create)

    def _job(self, state, job_id, revision=None):
        if job_id not in state['jobs']:
            raise ControlError('NOT_FOUND', '作业不存在', 404)
        job = state['jobs'][job_id]
        if revision is not None and revision != job['revision']:
            raise ControlError('STATE_CONFLICT', '作业状态已变化，请刷新', current_revision=job['revision'])
        return job

    def cancel(self, job_id, expected_state, revision, key):
        with self.transaction() as state:
            def cancel():
                job = self._job(state, job_id, revision)
                if job['state'] not in QUEUED or job['state'] != expected_state:
                    raise ControlError('STATE_CONFLICT', '作业已启动，取消排队不会停止当前作业', current_revision=job['revision'])
                job.update(state='cancelled', finished_at=now_string(), blocked_reason=None, revision=job['revision'] + 1)
                return {**job, 'status': 'cancelled'}
            return self._operation(state, key, 'cancel', {'job_id': job_id, 'expected_state': expected_state, 'revision': revision}, cancel)

    def stop(self, job_id, run_id, revision, key):
        with self.transaction() as state:
            def stop():
                job = self._job(state, job_id, revision)
                if job.get('run_id') != run_id or job['state'] not in {'starting', 'running', 'cancel_requested'}:
                    raise ControlError('STATE_CONFLICT', '目标运行已变化或结束', current_revision=job['revision'])
                job.update(state='cancel_requested', stop_requested_at=now_string(), revision=job['revision'] + 1)
                return {**job, 'status': 'accepted'}
            return self._operation(state, key, 'stop', {'job_id': job_id, 'run_id': run_id, 'revision': revision}, stop)

    def config(self):
        state = self.snapshot()
        active = next((j['config_revision'] for j in state['jobs'].values() if j['state'] in ACTIVE), None)
        return {'revision': state['configs'][-1]['revision'], 'active_revision': state['active_revision'],
                'config': self._active_config(state), 'history': state['configs'], 'running_config_revision': active,
                'deployment': {**{key: self.base[key] for key in ('optimize_windows', 'daily_submission_time', 'submit_window_minutes', 'reconcile_time', 'deadline')},
                               'daily_submission_times': self.base.get('daily_submission_times', [self.base['daily_submission_time']]),
                               'submission_policy': self.base.get('submission_policy', 'daily_window'),
                               'max_daily_submissions': self.base.get('max_daily_submissions', 5 if self.base.get('submission_policy') == 'after_optimization' else 1),
                               'submission_quota_basis': self.base.get('submission_quota_basis', 'attempts'),
                               'submission_quota_timezone': self.base.get('submission_quota_timezone', self.base['timezone'])},
                'apply_status': 'applied' if state['active_revision'] == state['configs'][-1]['revision'] else 'pending_activation', 'next_saved_revision': state['configs'][-1]['revision']}

    def config_preview(self, values):
        state = self.snapshot()
        current = self._active_config(state)
        if not isinstance(values, dict) or set(values) - CONFIG_FIELDS:
            raise ControlError('INVALID_PARAMETERS', '包含不可在线修改的配置字段', 422)
        cfg = {**current, **values}
        for key in ('daily_model_limit', 'reserve_submit', 'reserve_reconcile', 'max_agent_seconds', 'cpu_limit'):
            if type(cfg[key]) is not int:
                raise ControlError('INVALID_PARAMETERS', f'{key} 必须是整数', 422)
        if not (0 <= cfg['reserve_submit'] and 0 <= cfg['reserve_reconcile'] and
                cfg['reserve_submit'] + cfg['reserve_reconcile'] <= cfg['daily_model_limit'] <= 100):
            raise ControlError('INVALID_PARAMETERS', '每日总次数必须覆盖提交与对账预留，且不超过 100', 422)
        for key in ('memory_gib', 'memory_stop_gib', 'min_free_gib'):
            if type(cfg[key]) not in (int, float) or not math.isfinite(cfg[key]):
                raise ControlError('INVALID_PARAMETERS', f'{key} 必须是有效数值', 422)
        if not (2 <= cfg['cpu_limit'] <= self.base['cpu_limit'] and
                0 < cfg['memory_stop_gib'] <= self.base['memory_stop_gib'] and
                cfg['memory_stop_gib'] < cfg['memory_gib'] <= self.base['memory_gib'] and
                30 <= cfg['max_agent_seconds'] <= self.base['max_agent_seconds'] and
                cfg['min_free_gib'] >= self.base['min_free_gib']):
            raise ControlError('INVALID_PARAMETERS', '资源或时长超出授权范围；CPU 至少保留 1 核用于控制台', 422)
        if not isinstance(cfg['gpu_ids'], list) or not set(cfg['gpu_ids']) <= set(self.base['gpu_ids']):
            raise ControlError('INVALID_PARAMETERS', 'GPU 不在授权设备范围', 422)
        if not isinstance(cfg['model'], str) or not cfg['model'].strip():
            raise ControlError('INVALID_PARAMETERS', '项目模型不能为空', 422)
        if cfg['reasoning'] not in {'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'} or cfg['service_tier'] not in {'default', 'priority', 'flex'}:
            raise ControlError('INVALID_PARAMETERS', '未知模型强度或服务档位', 422)
        return {'config': cfg, 'changes': [{'field': key, 'before': current[key], 'after': value} for key, value in cfg.items() if value != current[key]],
                'effective': '激活后用于新作业；排队及当前作业保留原快照，调度按最新上限复查', 'valid': True}

    def save_config(self, values, revision, key):
        with self.transaction() as state:
            def save():
                config = self.config_preview(values)['config']
                if revision != state['configs'][-1]['revision']:
                    raise ControlError('CONFIG_CONFLICT', '配置已有新版本，请重新预览', current_revision=state['configs'][-1]['revision'])
                item = {'revision': revision + 1, 'created_at': now_string(), 'config': config}
                state['configs'].append(item)
                return {**item, 'status': 'validated'}
            return self._operation(state, key, 'config.save', {'config': values, 'revision': revision}, save)

    def activate_config(self, version, revision, key):
        with self.transaction() as state:
            def activate():
                if revision != state['configs'][-1]['revision']:
                    raise ControlError('CONFIG_CONFLICT', '配置已有新版本', current_revision=state['configs'][-1]['revision'])
                if version not in {item['revision'] for item in state['configs']}:
                    raise ControlError('NOT_FOUND', '配置版本不存在', 404)
                if version != state['configs'][-1]['revision']:
                    raise ControlError('CONFIG_CONFLICT', '回滚需将历史配置复制为新版本再激活', current_revision=state['configs'][-1]['revision'])
                state['active_revision'] = version
                return {'status': 'applied', 'revision': revision, 'active_revision': version,
                        'message': '后续 dispatch 已采用该版本；已排队和当前任务使用其快照'}
            return self._operation(state, key, 'config.activate', {'version': version, 'revision': revision}, activate)

    config_view = config

    def scheduler(self, action, key):
        if action not in {'pause', 'resume', 'start', 'stop'}:
            raise ControlError('INVALID_PARAMETERS', '未知调度操作', 422)
        with self.transaction() as state:
            def change():
                scheduler = state['scheduler']
                runtime = self.storage / 'runtime'
                runtime.mkdir(exist_ok=True)
                if action == 'pause':
                    scheduler['paused'] = True
                    (runtime / 'PAUSED').touch()
                elif action == 'resume':
                    scheduler['paused'] = False
                    (runtime / 'PAUSED').unlink(missing_ok=True)
                elif action == 'stop':
                    if any(job['state'] in ACTIVE for job in state['jobs'].values()):
                        raise ControlError('STATE_CONFLICT', '存在活跃或待核实作业，请先处理当前任务')
                    with (runtime / 'agent.lock').open('a') as execution:
                        try:
                            fcntl.flock(execution, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            raise ControlError('STATE_CONFLICT', '监督器仍持有执行权，请先处理当前任务')
                        scheduler['dispatch_enabled'] = False
                        path = runtime / 'daemon.json'
                        identity = json.loads(path.read_text()) if path.exists() else None
                        if identity and identity.get('status') == 'running' and process_identity(identity['pid']) == identity['pid_start']:
                            os.kill(identity['pid'], signal.SIGTERM)
                else:
                    scheduler['dispatch_enabled'] = True
                    path = runtime / 'daemon.json'
                    identity = json.loads(path.read_text()) if path.exists() else None
                    alive = identity and identity.get('status') == 'running' and process_identity(identity['pid']) == identity['pid_start']
                    if not alive:
                        env = {k: v for k, v in os.environ.items() if not k.startswith('CODEX_') or k == 'CODEX_HOME'}
                        with (runtime / 'scheduler.log').open('a') as log:
                            subprocess.Popen([self.base['python_executable'], str(ROOT / 'automation/runner.py'),
                                              '--config', str(self.config_path), 'daemon'],
                                             cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                             start_new_session=True)
                scheduler['updated_at'] = now_string()
                return {**scheduler, 'status': 'accepted' if action in {'start', 'stop'} else 'applied'}
            return self._operation(state, key, 'scheduler.' + action, {}, change)

    def enqueue_slot(self, slot):
        if slot is None:
            return
        slot_id, mode, seconds = slot
        snapshot = self.snapshot()
        if snapshot['scheduler']['paused'] or not snapshot['scheduler']['dispatch_enabled']:
            return
        if slot_id in snapshot['slots'] or (self.storage / 'runtime/slots' / (slot_id + '.json')).exists():
            return
        seconds = min(seconds, self._active_config(snapshot)['max_agent_seconds'])
        # Keep the existing slot deadline, reserving time for process cleanup.
        expires = self.now() + timedelta(seconds=seconds)
        request = {'kind': mode, 'max_seconds': max(30, seconds - 10)}
        result = self.enqueue(request, 'slot:' + slot_id, origin='automatic', slot_id=slot_id, expires_at=expires.isoformat())
        atomic_json(self.storage / 'runtime/slots' / (slot_id + '.json'),
                    {'slot': slot_id, 'mode': mode, 'job_id': result['job_id'], 'status': 'queued', 'created_at': result['created_at']})

    def _enqueue_quota_carryover(self, sources):
        """Recheck yesterday's unsubmitted best once per platform quota day."""
        zone = ZoneInfo(self.base.get('submission_quota_timezone', 'UTC'))
        day = self.now().astimezone(zone).date()
        prior = [source for source in sources
                 if datetime.fromisoformat(source['finished_at']).astimezone(zone).date() < day]
        if not prior:
            return None
        state = self.snapshot()
        slot_id = day.isoformat() + '-submit-carryover'
        if slot_id in state['slots']:
            return None
        for job in state['jobs'].values():
            if job['kind'] != 'submit':
                continue
            if job['state'] in QUEUED | ACTIVE:
                return None
            stamp = job.get('started_at') or job.get('finished_at')
            if stamp and datetime.fromisoformat(stamp).astimezone(zone).date() == day:
                return None
        if self.submission_precheck():
            return None
        source = max(prior, key=lambda item: item['finished_at'])
        cfg = self._active_config(state)
        return self.enqueue(
            {'kind': 'submit', 'max_seconds': min(self.base['submit_timeout_seconds'], cfg['max_agent_seconds']),
             'hypothesis': '平台额度跨日恢复，优先提交此前尚未提交的已验证最佳；执行时重新准备当前最佳组合。'},
            'quota-carryover:' + day.isoformat(), origin='automatic', slot_id=slot_id,
            trigger_job_id=source['job_id'], trigger_run_id=source['run_id'])

    def enqueue_completed_optimizations(self):
        """Persist optimization followups in the existing queue; never run a second loop."""
        if self.base.get('submission_policy') not in {'after_optimization', 'daily_windows'}:
            return []
        snapshot = self.snapshot()
        if snapshot['scheduler']['paused'] or not snapshot['scheduler']['dispatch_enabled']:
            return []
        if self.now() >= datetime.fromisoformat(self.base['deadline']):
            return []
        if self.base.get('submission_policy') == 'daily_windows':
            return self._enqueue_upload_reconciliations()
        sources = [{'key': job['job_id'], 'job_id': job['job_id'], 'run_id': job['run_id'],
                    'finished_at': job['finished_at']}
                   for job in snapshot['jobs'].values()
                   if job['kind'] == 'optimize' and job['state'] == 'completed' and job.get('finished_at')]
        represented_runs = {job.get('run_id') for job in snapshot['jobs'].values()}
        legacy = []
        for path in (self.storage / 'runtime/slots').glob('*.json'):
            record = json.loads(path.read_text())
            if record.get('mode') != 'optimize' or record.get('status') != 'completed' or not record.get('finished_at'):
                continue
            run_id = record.get('run_id') or Path(record.get('run_dir', path.stem)).name
            if run_id not in represented_runs:
                legacy.append({'key': 'legacy:' + run_id, 'job_id': None, 'run_id': run_id,
                               'finished_at': record['finished_at']})
        # On migration, reconcile only the latest completed legacy optimization.
        if legacy:
            sources.append(max(legacy, key=lambda item: item['finished_at']))
        results = []
        for source in sorted(sources, key=lambda item: item['finished_at']):
            state = self.snapshot()
            if source['key'] in state.get('optimization_followups', {}):
                continue
            reason = self.submission_precheck()
            item = {**source, 'observed_at': now_string()}
            if reason in {'NO_IMPROVEMENT', 'ALREADY_ATTEMPTED_CANDIDATE', 'EVIDENCE_STALE'}:
                item.update(status='skipped', reason=reason)
            else:
                pending = next((job for job in state['jobs'].values()
                                if job['kind'] == 'submit' and job['state'] in QUEUED | ACTIVE), None)
                if pending:
                    item.update(status='linked', submission_job_id=pending['job_id'])
                else:
                    cfg = self._active_config(state)
                    request = {'kind': 'submit', 'max_seconds': min(self.base['submit_timeout_seconds'], cfg['max_agent_seconds']),
                               'hypothesis': '优化完成后检查当前已验证最佳；仅提交仍有效的新改进。'}
                    queued = self.enqueue(request, 'after-optimize:' + source['key'], origin='automatic',
                                          trigger_job_id=source['job_id'], trigger_run_id=source['run_id'])
                    item.update(status='queued', submission_job_id=queued['job_id'], reason=queued.get('blocked_reason'))
                    results.append(queued)
            with self.transaction() as state:
                state.setdefault('optimization_followups', {}).setdefault(source['key'], item)
                if source['job_id'] in state['jobs']:
                    state['jobs'][source['job_id']]['submission_followup'] = item
        carryover = self._enqueue_quota_carryover(sources)
        if carryover:
            results.append(carryover)
        return results + self._enqueue_upload_reconciliations()

    def _enqueue_upload_reconciliations(self):
        results = []
        # Each failed or uncertain upload gets its own one-shot query. A query
        # already running may have read history before this attempt happened.
        # Known IDs belong to normal grading reconciliation, not upload recovery.
        pipeline = self._pipeline_state()
        for token, submission in pipeline.get('submissions', {}).items():
            if submission.get('status') not in {'upload_started', 'submitted', 'score_unknown', 'rejected'} or submission.get('submission_id'):
                continue
            state = self.snapshot()
            if token in state.get('reconciliation_followups', {}):
                continue
            operation_key = 'reconcile-upload:' + token
            prior = state['operations'].get(operation_key)
            if prior:
                # Recover a crash after enqueue but before saving the followup.
                # Current config/trigger metadata may differ from that request.
                jid = prior['result']['job_id']
            else:
                recent = [job for job in state['jobs'].values() if job['kind'] == 'submit' and job.get('run_id')]
                trigger = max(recent, key=lambda job: job['created_at']) if recent else {}
                cfg = self._active_config(state)
                queued = self.enqueue({'kind': 'reconcile', 'max_seconds': min(self.base['reconcile_timeout_seconds'], cfg['max_agent_seconds']),
                                       'hypothesis': f'上传尝试 {token} 失败或结果未确认，自动对账一次：只读查询平台并登记回执；不得再次上传。'},
                                      operation_key, origin='automatic',
                                      trigger_job_id=trigger.get('job_id'), trigger_run_id=trigger.get('run_id'))
                jid = queued['job_id']
                results.append(queued)
            with self.transaction() as state:
                state.setdefault('reconciliation_followups', {}).setdefault(token, {'job_id': jid, 'observed_at': now_string()})
        return results

    def _recover(self, state):
        for job in state['jobs'].values():
            if job['state'] not in ACTIVE:
                continue
            result_path = self.storage / 'runs' / job['run_id'] / 'result.json'
            if result_path.exists():
                result = json.loads(result_path.read_text())
                if result.get('run_id') == job['run_id'] and result.get('job_id') == job['job_id']:
                    self._finish(state, job, result)
                    continue
            if process_identity(job.get('supervisor_pid')) != job.get('supervisor_start') or not job.get('supervisor_start'):
                if job['state'] != 'unknown':
                    job.update(state='unknown', blocked_reason='SUPERVISOR_IDENTITY_UNCONFIRMED', revision=job['revision'] + 1)

    def claim(self):
        """Caller must already own runtime/agent.lock. Reserve and persist before spawn."""
        with self.transaction() as state:
            self._recover(state)
            if any(job['state'] in ACTIVE for job in state['jobs'].values()):
                return None
            queue = [job for job in state['jobs'].values() if job['state'] in QUEUED]
            queue.sort(key=lambda j: (0 if j['kind'] in {'submit', 'reconcile'} else 2 if j['origin'] == 'automatic' else 1,
                                      j['created_at']))
            for job in queue:
                if job.get('expires_at') and self.now() >= datetime.fromisoformat(job['expires_at']):
                    job.update(state='cancelled', blocked_reason='SLOT_EXPIRED', finished_at=now_string(), revision=job['revision'] + 1)
                    continue
                if job.get('origin') == 'automatic' and job.get('expires_at'):
                    remaining = int((datetime.fromisoformat(job['expires_at']) - self.now()).total_seconds()) - 10
                    if remaining < 30:
                        job.update(state='cancelled', blocked_reason='SLOT_EXPIRED', finished_at=now_string(), revision=job['revision'] + 1)
                        continue
                    job.setdefault('requested_max_seconds', job['max_seconds'])
                    job['max_seconds'] = min(job['requested_max_seconds'], remaining)
                reason = self._blocked_reason(job, state)
                if reason:
                    if self.base.get('submission_policy', 'daily_window') != 'daily_window' and job['kind'] == 'submit' and reason in {'NO_IMPROVEMENT', 'ALREADY_ATTEMPTED_CANDIDATE'}:
                        job.update(state='cancelled', blocked_reason=reason, stop_reason=reason.lower(), finished_at=now_string(), revision=job['revision'] + 1)
                        continue
                    if reason != job['blocked_reason'] or job['state'] != 'blocked':
                        job.update(state='blocked', blocked_reason=reason, revision=job['revision'] + 1)
                    continue
                jid = job['job_id']
                run_id = self.now().strftime('%Y%m%dT%H%M%S') + '-' + job['kind'] + '-' + uuid.uuid4().hex[:6]
                job.update(state='starting', blocked_reason=None, run_id=run_id,
                           supervisor_pid=os.getpid(), supervisor_start=process_identity(os.getpid()),
                           revision=job['revision'] + 1)
                if job['kind'] in MODEL_KINDS:
                    day = self.now().date().isoformat()
                    job['budget_date'] = day
                    state['reservations'][jid] = {'job_id': jid, 'kind': job['kind'], 'budget_date': day,
                                                  'reserved_at': now_string(), 'started_at': None, 'run_id': run_id}
                return json.loads(json.dumps(job))
        return None

    def spawn(self, job_id, run_id, factory):
        """Only the owning supervisor calls this; HTTP can only request cancellation."""
        with self.transaction() as state:
            job = self._job(state, job_id)
            if job['run_id'] != run_id or job['state'] not in {'starting', 'cancel_requested'}:
                raise ControlError('STATE_CONFLICT', '运行启动身份不匹配')
            if job['state'] == 'cancel_requested':
                job.update(state='cancelled', finished_at=now_string(), revision=job['revision'] + 1)
                if job_id in state['reservations']:
                    state['reservations'][job_id]['released_at'] = now_string()
                # Persist cancellation before leaving the transaction.
                return None
            if job['kind'] in MODEL_KINDS:
                reservation = state['reservations'][job_id]
                today = self.now().date().isoformat()
                if reservation['budget_date'] != today:
                    reservation['released_at'] = now_string()
                    reason = self._budget_reason(job, state)
                    if reason:
                        job.update(state='blocked', blocked_reason=reason, run_id=None, revision=job['revision'] + 1)
                        return None
                    reservation.update(budget_date=today, reserved_at=now_string())
                    reservation.pop('released_at', None)
                    job['budget_date'] = today
            # Popen errors are the only failures that prove no child was created.
            try:
                process = factory()
            except OSError as error:
                job.update(state='failed', finished_at=now_string(), stop_reason='spawn_failed', revision=job['revision'] + 1)
                if job_id in state['reservations']:
                    state['reservations'][job_id]['released_at'] = now_string()
                return None
            job.update(state='running', pid=process.pid, pid_start=process_identity(process.pid),
                       started_at=now_string(), revision=job['revision'] + 1)
            if job_id in state['reservations']:
                state['reservations'][job_id]['started_at'] = job['started_at']
            return process

    def cancel_requested(self, job_id, run_id):
        job = self.snapshot()['jobs'][job_id]
        return job['run_id'] == run_id and job['state'] == 'cancel_requested'

    def _finish(self, state, job, result):
        stop = result.get('stop_reason')
        status = {'cancel_requested': 'cancelled', 'time_budget': 'timed_out', 'memory_budget': 'resource_stopped',
                  'disk_reserve': 'resource_stopped', 'interrupted': 'cancelled'}.get(stop, result['status'])
        job.update(state=status, finished_at=result.get('finished_at'), stop_reason=stop,
                   elapsed_seconds=result.get('elapsed_seconds'), peak_sum_rss_gib=result.get('peak_sum_rss_gib'),
                   revision=job['revision'] + 1, blocked_reason=None)
        link = self.storage / 'runs' / job['run_id'] / 'candidate-link.json'
        if link.exists():
            job['candidate_id'] = json.loads(link.read_text())['candidate_id']

    def finished(self, job_id, result):
        with self.transaction() as state:
            job = self._job(state, job_id)
            self._finish(state, job, result)
        self.enqueue_completed_optimizations()

    def dispatch(self):
        """Execute at most one eligible job; existing daemon remains the sole loop."""
        try:
            from .runner import execute
        except ImportError:
            from runner import execute
        with self.transaction() as state:
            self._recover(state)
        self.enqueue_completed_optimizations()
        job = self.claim()
        if job is None:
            return None
        run_dir = self.storage / 'runs' / job['run_id']
        run_dir.mkdir(parents=True)
        cfg = {**self.base, **job['config'], 'storage_root': str(self.storage)}
        # Reserve a core and host memory for API/sampling inside the aggregate budget.
        cfg['cpu_limit'] = max(1, cfg['cpu_limit'] - 1)
        cfg['memory_stop_gib'] = min(cfg['memory_stop_gib'], cfg['memory_gib'] - 0.25)
        config_path = run_dir / 'config.json'
        atomic_json(config_path, cfg)
        atomic_json(run_dir / 'job.json', job)
        state_path = self.storage / 'runtime/slots' / ((job.get('slot_id') or job['job_id']) + '.json')
        try:
            result = execute(job['kind'], cfg, config_path, job['max_seconds'],
                             job.get('slot_id') or job['job_id'], state_path,
                             job=job, controller=self)
        except Exception:
            # The persisted startup intent is deliberately not retried. Recovery
            # will inspect exact process/result identity before allowing more work.
            with self.transaction() as state:
                current = state['jobs'][job['job_id']]
                if current['state'] in ACTIVE:
                    current.update(state='unknown', blocked_reason='EXECUTION_OUTCOME_UNKNOWN', revision=current['revision'] + 1)
            raise
        if result is not None:
            self.finished(job['job_id'], result)
        return result
