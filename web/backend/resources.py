"""Lightweight host telemetry, kept separate from supervisor task samples."""
from __future__ import annotations

from copy import deepcopy
import csv
from datetime import datetime, timezone
import io
from pathlib import Path
import shutil
import subprocess
import threading
import time

GIB = 1024 ** 3
ACTIVE = {'starting', 'running', 'cancel_requested', 'unknown'}


def normalize_task_sample(sample, current, *, now=None, max_age_seconds=15):
    """Project an actual supervisor sample without substituting whole-host usage."""
    sample = sample or {}
    result = {'scope': 'task', 'status': 'idle', 'reason': '当前没有受监督的计算任务',
              'observed_at': None, 'cpu_cores': None, 'rss_gib': None,
              'sample_age_seconds': None}
    if not current or current.get('state', current.get('status')) not in ACTIVE:
        return result
    cpu = sample.get('cpu_cores')
    if cpu is None:
        cpu = sample.get('cpu_equivalent_cores')
    rss = sample.get('rss_gib')
    if rss is None:
        rss = sample.get('sum_rss_gib')
    stamp = sample.get('at') or sample.get('observed_at') or sample.get('timestamp')
    result.update(cpu_cores=cpu, rss_gib=rss, observed_at=stamp)
    state = current.get('state', current.get('status'))
    if state == 'unknown':
        result.update(status='unconfirmed', reason='运行身份待核实；显示值仅代表最近一次任务采样')
        return result
    if not sample or cpu is None and rss is None:
        result.update(status='missing', reason='监督器尚未返回任务资源样本')
        return result
    if not stamp:
        result.update(status='unconfirmed', reason='历史样本未记录采样时间，无法确认是否为当前资源用量')
        return result
    try:
        sampled_at = datetime.fromisoformat(stamp)
        if sampled_at.tzinfo is None:
            result.update(status='unconfirmed', reason='采样时间未记录时区，无法确认样本新鲜度')
            return result
        age = max(0, ((now or datetime.now(timezone.utc)) - sampled_at).total_seconds())
    except (TypeError, ValueError):
        result.update(status='unconfirmed', reason='无法解析采样时间，显示最近记录值')
        return result
    result['sample_age_seconds'] = round(age, 1)
    if age > max_age_seconds:
        result.update(status='unconfirmed', reason=f'最近任务采样距今 {age:.0f} 秒，尚未收到新样本')
    else:
        result.update(status='observed', reason=None)
    return result


class ResourceMonitor:
    """Sample on demand, with one cached snapshot shared by HTTP readers."""
    def __init__(self, storage, gpu_ids, *, cache_seconds=5, proc_root=Path('/proc')):
        self.storage = Path(storage)
        self.gpu_ids = tuple(gpu_ids)
        self.cache_seconds = cache_seconds
        self.proc_root = Path(proc_root)
        self._lock = threading.Lock()
        self._cached = None
        self._cached_at = 0.0
        self._cached_gpu_ids = None
        try:
            self._previous_cpu = self._cpu_times()
        except (OSError, ValueError):
            self._previous_cpu = None

    def _cpu_times(self):
        lines = (self.proc_root / 'stat').read_text().splitlines()
        # guest/guest_nice are already included in user/nice, so count only the first eight fields.
        values = [int(value) for value in lines[0].split()[1:9]]
        cores = sum(line.startswith('cpu') and line[3:4].isdigit() for line in lines)
        return sum(values), values[3] + values[4], cores

    def _cpu(self):
        try:
            total, idle, cores = self._cpu_times()
        except (OSError, ValueError) as exc:
            return {'status': 'unavailable', 'cores': None, 'total_cores': None,
                    'percent': None, 'reason': f'无法读取服务器 CPU 计数：{exc}'}
        previous = self._previous_cpu
        self._previous_cpu = (total, idle, cores)
        if previous is None or total <= previous[0]:
            return {'status': 'warming_up', 'cores': None, 'total_cores': cores,
                    'percent': None, 'reason': '正在建立 CPU 差分采样，下一次刷新显示利用率'}
        fraction = (total - previous[0] - idle + previous[1]) / (total - previous[0])
        return {'status': 'observed', 'cores': round(fraction * cores, 3),
                'total_cores': cores, 'percent': round(fraction * 100, 2), 'reason': None}

    def _memory(self):
        try:
            fields = {line.split(':', 1)[0]: int(line.split()[1]) * 1024
                      for line in (self.proc_root / 'meminfo').read_text().splitlines()}
            total, available = fields['MemTotal'], fields['MemAvailable']
        except (OSError, ValueError, KeyError) as exc:
            return {'status': 'unavailable', 'total_gib': None, 'available_gib': None,
                    'used_gib': None, 'reason': f'无法读取服务器内存信息：{exc}'}
        return {'status': 'observed', 'total_gib': round(total / GIB, 3),
                'available_gib': round(available / GIB, 3),
                'used_gib': round((total - available) / GIB, 3), 'reason': None}

    def _disk(self):
        try:
            disk = shutil.disk_usage(self.storage)
        except OSError as exc:
            return {'status': 'unavailable', 'total_gib': None, 'free_gib': None,
                    'used_gib': None, 'reason': f'无法读取数据盘空间：{exc}'}
        return {'status': 'observed', 'total_gib': round(disk.total / GIB, 3),
                'free_gib': round(disk.free / GIB, 3), 'used_gib': round(disk.used / GIB, 3),
                'reason': None}

    @staticmethod
    def _gpu(gpu_ids, observed_at):
        base = {'scope': 'device', 'observed_at': observed_at, 'allowed_ids': list(gpu_ids),
                'devices': [], 'activity': 'unknown'}
        if not gpu_ids:
            return {**base, 'status': 'unallocated', 'reason': '当前配置未分配 GPU'}
        command = ['nvidia-smi', '-i', ','.join(map(str, gpu_ids)),
                   '--query-gpu=index,name,utilization.gpu,memory.used,memory.total',
                   '--format=csv,noheader,nounits']
        try:
            response = subprocess.run(command, capture_output=True, text=True, timeout=2, check=False)
        except FileNotFoundError:
            return {**base, 'status': 'unavailable', 'reason': '服务器未安装 nvidia-smi'}
        except subprocess.TimeoutExpired:
            return {**base, 'status': 'unavailable', 'reason': 'nvidia-smi 查询超过 2 秒，等待下次采样'}
        except OSError as exc:
            return {**base, 'status': 'unavailable', 'reason': f'无法执行 nvidia-smi：{exc}'}
        if response.returncode != 0:
            reason = response.stderr.strip() or response.stdout.strip() or f'退出码 {response.returncode}'
            return {**base, 'status': 'unavailable', 'reason': 'nvidia-smi 查询失败：' + reason[:300]}

        def number(value, divisor=1):
            return None if value.strip() in {'N/A', '[N/A]', '[Not Supported]'} else round(float(value) / divisor, 3)

        devices = []
        try:
            for row in csv.reader(io.StringIO(response.stdout)):
                if not row:
                    continue
                index, name, utilization, used, total = row
                if int(index) not in gpu_ids:
                    continue
                devices.append({'index': int(index), 'name': name.strip(),
                                'utilization_percent': number(utilization),
                                'memory_used_gib': number(used, 1024),
                                'memory_total_gib': number(total, 1024)})
        except ValueError:
            return {**base, 'status': 'unavailable', 'reason': 'nvidia-smi 未返回可解析的设备指标'}
        if not devices:
            return {**base, 'status': 'unavailable', 'reason': 'nvidia-smi 没有返回已分配的 GPU'}
        utilization = [device['utilization_percent'] for device in devices]
        activity = 'unknown' if any(value is None for value in utilization) else 'busy' if any(utilization) else 'idle'
        complete = {device['index'] for device in devices} == set(gpu_ids)
        if not complete and activity == 'idle':
            activity = 'unknown'
        return {**base, 'status': 'available', 'devices': devices, 'activity': activity,
                'reason': None if complete else '部分已分配 GPU 未返回指标'}

    def snapshot(self, gpu_ids=None):
        """gpu_ids can follow an activated configuration without recreating the sampler."""
        allowed = self.gpu_ids if gpu_ids is None else tuple(gpu_ids)
        with self._lock:
            tick = time.monotonic()
            if self._cached is not None and allowed == self._cached_gpu_ids and tick - self._cached_at < self.cache_seconds:
                return deepcopy(self._cached)
            observed_at = datetime.now(timezone.utc).isoformat()
            self._cached = {'scope': 'host', 'observed_at': observed_at,
                            'cpu': self._cpu(), 'memory': self._memory(), 'disk': self._disk(),
                            'gpu': self._gpu(allowed, observed_at)}
            self._cached_at = tick
            self._cached_gpu_ids = allowed
            return deepcopy(self._cached)
