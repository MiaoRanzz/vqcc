"""Concurrent validations: bounded verifier slots and a global lock left free meanwhile."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parent))

from pipeline import Pipeline  # noqa: E402


class ValidationSlotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='vqcc-slots-')
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        config = base / 'config.json'
        config.write_text(json.dumps({'storage_root': str(base / 'artifacts'), 'deadline': '2099-01-01T00:00:00+08:00',
                                      'cpu_limit': 20, 'validation_parallelism': 2}))
        self.pipeline = Pipeline(config)
        self.other = Pipeline(config)

    def test_slots_bound_concurrency_and_split_workers(self):
        acquired, release = [], threading.Event()
        def hold():
            with Pipeline(self.pipeline.config_path).validation_slot() as workers:
                acquired.append(workers)
                release.wait(10)
        threads = [threading.Thread(target=hold) for _ in range(3)]
        for thread in threads:
            thread.start()
        for _ in range(50):
            if len(acquired) >= 2:
                break
            threading.Event().wait(0.1)
        threading.Event().wait(0.5)
        self.assertEqual(acquired, [10, 10])
        release.set()
        for thread in threads:
            thread.join(10)
        self.assertEqual(acquired, [10, 10, 10])

    def test_global_lock_is_free_while_a_verifier_slot_is_held(self):
        with self.pipeline.validation_slot():
            done = threading.Event()
            def state_update():
                with self.other.locked():
                    done.set()
            thread = threading.Thread(target=state_update)
            thread.start()
            self.assertTrue(done.wait(5))
            thread.join()

    def test_default_keeps_previous_single_slot_worker_count(self):
        self.pipeline.config.pop('validation_parallelism')
        with self.pipeline.validation_slot() as workers:
            self.assertEqual(workers, 16)


if __name__ == '__main__':
    unittest.main()
