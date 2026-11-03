"""Mandatory verification at the local worker boundary, without scientific runs."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import local_job
from pipeline import PipelineError


class LocalVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vqcc-local-validation-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        dataset = self.root / 'sample_submission/dfthcsos/submission.npz'
        dataset.parent.mkdir(parents=True)
        dataset.write_bytes(b'isolated dataset fixture')
        self.dataset_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
        self.pipeline = Mock()
        self.pipeline.create.return_value = {
            'id': 'candidate', 'output': str(self.root / 'candidate/output'),
        }
        self.pipeline.validate.return_value = {'id': 'candidate', 'status': 'PASS', 'cost': 100}
        for target, value in (('ROOT', self.root), ('Pipeline', Mock(return_value=self.pipeline)),
                              ('generator_revision', Mock(return_value='source-revision'))):
            context = patch.object(local_job, target, value)
            context.start()
            self.addCleanup(context.stop)

    def job(self, task='invsqrt', **extra):
        return {'job_id': 'job', 'kind': 'local_experiment', 'task': task,
                'generator_revision': 'source-revision', 'dataset_sha256': self.dataset_hash,
                'hypothesis': 'feasible candidate', 'parameters': {}, **extra}

    def test_every_generated_candidate_is_verified_even_for_legacy_jobs(self):
        for task in ('dqi', 'invsqrt', 'dfthcsos'):
            for index, flags in enumerate(({}, {'validate': False}, {'validate': True})):
                with self.subTest(task=task, flags=flags):
                    run_dir = self.root / f'{task}-{index}'
                    run_dir.mkdir()
                    self.pipeline.reset_mock()
                    with patch.object(local_job.subprocess, 'run') as generate:
                        def verify(cid):
                            generate.assert_called_once()
                            self.assertTrue(generate.call_args.kwargs['check'])
                            self.assertEqual(generate.call_args.args[0][2], task)
                            return {'id': cid, 'status': 'PASS', 'cost': 100}
                        self.pipeline.validate.side_effect = verify
                        result = local_job.run(self.job(task, **flags), self.root / 'config.json', run_dir)
                    self.pipeline.validate.assert_called_once_with('candidate')
                    self.assertEqual(result['status'], 'PASS')
                    self.assertEqual(json.loads((run_dir / 'operation-result.json').read_text()), result)
                    self.pipeline.promote.assert_not_called()

    def test_generation_failure_does_not_validate_missing_artifacts(self):
        run_dir = self.root / 'generation-failed'
        run_dir.mkdir()
        with patch.object(local_job.subprocess, 'run', side_effect=subprocess.CalledProcessError(2, ['generate'])):
            with self.assertRaises(subprocess.CalledProcessError):
                local_job.run(self.job(), self.root / 'config.json', run_dir)
        self.pipeline.validate.assert_not_called()
        self.assertFalse((run_dir / 'operation-result.json').exists())
        self.assertTrue((run_dir / 'candidate-link.json').exists())

    def test_official_failure_cannot_be_reported_as_generated_success(self):
        run_dir = self.root / 'verification-failed'
        run_dir.mkdir()
        self.pipeline.validate.side_effect = PipelineError('official verifier failed')
        with patch.object(local_job.subprocess, 'run'):
            with self.assertRaisesRegex(PipelineError, 'official verifier failed'):
                local_job.run(self.job(validate=False), self.root / 'config.json', run_dir)
        self.pipeline.validate.assert_called_once_with('candidate')
        self.assertFalse((run_dir / 'operation-result.json').exists())
        self.assertTrue((run_dir / 'candidate-link.json').exists())


if __name__ == '__main__':
    unittest.main()
