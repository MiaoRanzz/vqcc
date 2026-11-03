from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from web.backend.resources import ResourceMonitor, normalize_task_sample


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write_cpu(100, 900)
        (self.root / 'meminfo').write_text('MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\nMemFree: 1048576 kB\n')

    def write_cpu(self, user, idle):
        (self.root / 'stat').write_text(f'cpu {user} 0 0 {idle} 0 0 0 0 0 0\n' +
                                      '\n'.join(f'cpu{i} 0 0 0 0 0 0 0 0 0 0' for i in range(4)))

    def monitor(self, gpu_ids=(0, 1), **kwargs):
        return ResourceMonitor(self.root, gpu_ids, proc_root=self.root, **kwargs)

    def test_host_cpu_delta_and_memory_are_separate_from_task_usage(self):
        monitor = self.monitor(())
        self.write_cpu(140, 960)
        host = monitor.snapshot()
        self.assertEqual(host['scope'], 'host')
        self.assertEqual(host['cpu']['cores'], 1.6)
        self.assertEqual(host['cpu']['percent'], 40)
        self.assertEqual(host['memory']['used_gib'], 2)
        self.assertEqual(host['memory']['available_gib'], 6)
        self.assertEqual(host['gpu']['status'], 'unallocated')
        task = normalize_task_sample({}, None)
        self.assertEqual(task['status'], 'idle')
        self.assertIsNone(task['cpu_cores'])
        self.assertIsNone(task['rss_gib'])

    def test_first_cpu_sample_waits_for_delta(self):
        result = self.monitor(()).snapshot()['cpu']
        self.assertEqual(result['status'], 'warming_up')
        self.assertIsNone(result['cores'])
        self.assertIn('下一次', result['reason'])

    @patch('web.backend.resources.subprocess.run')
    def test_gpu_uses_assigned_devices_and_snapshot_is_cached(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '1, NVIDIA A100, 0, 4, 81920\n', '')
        monitor = self.monitor((1,))
        first = monitor.snapshot()
        self.assertEqual(first['gpu']['status'], 'available')
        self.assertEqual(first['gpu']['activity'], 'idle')
        self.assertEqual(first['gpu']['devices'][0]['memory_total_gib'], 80)
        args, kwargs = run.call_args
        self.assertEqual(args[0][1:3], ['-i', '1'])
        self.assertEqual(kwargs['timeout'], 2)
        first['gpu']['devices'].clear()
        self.assertEqual(len(monitor.snapshot()['gpu']['devices']), 1)
        self.assertEqual(run.call_count, 1)

    @patch('web.backend.resources.subprocess.run')
    def test_changed_gpu_assignment_invalidates_cache(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '0, A100, 3, 8, 81920\n', '')
        monitor = self.monitor((0,))
        self.assertEqual(monitor.snapshot()['gpu']['activity'], 'busy')
        self.assertEqual(monitor.snapshot(gpu_ids=[])['gpu']['status'], 'unallocated')
        self.assertEqual(run.call_count, 1)

    @patch('web.backend.resources.subprocess.run')
    def test_gpu_timeout_is_unknown_with_reason(self, run):
        run.side_effect = subprocess.TimeoutExpired('nvidia-smi', 2)
        gpu = self.monitor().snapshot()['gpu']
        self.assertEqual(gpu['status'], 'unavailable')
        self.assertEqual(gpu['devices'], [])
        self.assertIn('2 秒', gpu['reason'])

    @patch('web.backend.resources.subprocess.run')
    def test_gpu_driver_failure_is_visible(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, '', 'NVML driver unavailable')
        gpu = self.monitor().snapshot()['gpu']
        self.assertEqual(gpu['status'], 'unavailable')
        self.assertIn('NVML', gpu['reason'])

    @patch('web.backend.resources.subprocess.run')
    def test_unsupported_utilization_remains_unknown(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '0, GPU, [Not Supported], 4, 81920\n', '')
        gpu = self.monitor((0,)).snapshot()['gpu']
        self.assertIsNone(gpu['devices'][0]['utilization_percent'])
        self.assertEqual(gpu['activity'], 'unknown')

    @patch('web.backend.resources.subprocess.run')
    def test_missing_assigned_device_does_not_imply_all_devices_idle(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '0, GPU, 0, 4, 81920\n', '')
        gpu = self.monitor((0, 1)).snapshot()['gpu']
        self.assertEqual(gpu['activity'], 'unknown')
        self.assertIn('部分', gpu['reason'])

    def test_legacy_task_fields_and_stale_timestamp(self):
        now = datetime.now(timezone.utc)
        sample = {'cpu_equivalent_cores': 2.75, 'sum_rss_gib': 1.25, 'at': now.isoformat()}
        task = normalize_task_sample(sample, {'state': 'running'}, now=now)
        self.assertEqual(task['status'], 'observed')
        self.assertEqual(task['cpu_cores'], 2.75)
        self.assertEqual(task['rss_gib'], 1.25)
        stale = normalize_task_sample(sample, {'state': 'running'}, now=now + timedelta(seconds=30))
        self.assertEqual(stale['status'], 'unconfirmed')
        self.assertEqual(stale['cpu_cores'], 2.75)
        self.assertEqual(stale['sample_age_seconds'], 30)

    def test_missing_sample_and_unknown_process_do_not_fabricate_zero(self):
        task = normalize_task_sample({}, {'state': 'running'})
        self.assertEqual(task['status'], 'missing')
        self.assertIsNone(task['cpu_cores'])
        task = normalize_task_sample({'cpu_cores': 1}, {'state': 'unknown'})
        self.assertEqual(task['status'], 'unconfirmed')
        self.assertEqual(task['cpu_cores'], 1)
        self.assertIsNone(task['rss_gib'])

    def test_actual_zero_task_reading_is_preserved(self):
        sample = {'cpu_cores': 0, 'rss_gib': 0, 'at': datetime.now(timezone.utc).isoformat()}
        task = normalize_task_sample(sample, {'state': 'running'})
        self.assertEqual(task['status'], 'observed')
        self.assertEqual(task['cpu_cores'], 0)
        self.assertEqual(task['rss_gib'], 0)


if __name__ == '__main__':
    unittest.main()
