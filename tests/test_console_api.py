"""HTTP workflows against isolated state; never invokes models or official verification."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from automation.jobs import Jobs
from web.backend.app import create_app

ROOT = Path(__file__).resolve().parents[1]


class ConsoleApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storage = self.root / 'store'
        self.storage.mkdir()
        cfg = json.loads((ROOT / 'automation/config.json').read_text())
        cfg.update(storage_root=str(self.storage), min_free_gib=0, deadline='2099-01-01T00:00:00+08:00')
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps(cfg))
        Jobs(self.config, initialize=True)
        self.key = self.root / 'key'
        self.key.write_text('fixture-session-key')
        self.app = create_app(self.config, key_path=self.key)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8765')
        login = self.client.post('/api/v1/session', json={'key': 'fixture-session-key'})
        self.csrf = login.json()['csrf_token']
        self.headers = {'X-CSRF-Token': self.csrf, 'Idempotency-Key': 'fixture-create'}
        self.body = {'kind': 'local_experiment', 'task': 'dqi', 'parameters': {'stack_cap': 1},
                     'hypothesis': 'HTTP integration fixture', 'max_seconds': 30}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_login_csrf_host_and_logout(self):
        stranger = TestClient(self.app, base_url='http://127.0.0.1:8765')
        for path in ('overview', 'events', 'artifacts/no-such-report'):
            self.assertEqual(stranger.get('/api/v1/' + path).status_code, 401)
        invalid_login = stranger.post('/api/v1/session', json={'key': '不是控制台密钥'})
        self.assertEqual(invalid_login.status_code, 401)
        self.assertEqual(invalid_login.json()['code'], 'INVALID_SESSION_KEY')
        self.assertEqual(self.client.post('/api/v1/jobs', json=self.body).status_code, 403)
        bad_origin = {**self.headers, 'Origin': 'https://unrelated.example'}
        self.assertEqual(self.client.post('/api/v1/jobs', json=self.body, headers=bad_origin).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/overview', headers={'Host': 'unrelated.example'}).status_code, 400)
        self.assertEqual(self.client.delete('/api/v1/session', headers=self.headers).status_code, 204)
        self.assertEqual(self.client.get('/api/v1/overview').status_code, 401)
        stranger.close()

    def test_concurrent_idempotency_and_conflict(self):
        def create(_):
            return self.client.post('/api/v1/jobs', json=self.body, headers=self.headers)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(create, range(2)))
        self.assertEqual([r.status_code for r in responses], [202, 202])
        self.assertEqual(responses[0].json()['job_id'], responses[1].json()['job_id'])
        self.assertEqual(len(self.client.get('/api/v1/jobs').json()['data']['items']), 1)
        conflict = self.client.post('/api/v1/jobs', json={**self.body, 'max_seconds': 60}, headers=self.headers)
        self.assertEqual(conflict.status_code, 409)

    def test_preview_queue_cancel_and_no_model_calls(self):
        preview = self.client.post('/api/v1/jobs/preview', json=self.body, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()['data']['request']['validate'])
        self.assertEqual(self.client.get('/api/v1/jobs').json()['data']['items'], [])
        response = self.client.post('/api/v1/jobs', json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()['job_id']
        job = self.client.get('/api/v1/jobs/' + job_id).json()['data']
        self.assertTrue(job['validate'])
        cancel = self.client.post('/api/v1/jobs/' + job_id + '/cancel-queued',
                                  json={'expected_state': job['state'], 'revision': job['revision']},
                                  headers={**self.headers, 'Idempotency-Key': 'fixture-cancel'})
        self.assertEqual(cancel.status_code, 200, cancel.text)
        self.assertEqual(self.client.get('/api/v1/jobs/' + job_id).json()['data']['state'], 'cancelled')
        self.assertFalse((self.storage / 'runs').exists())
        self.assertEqual(self.app.state.jobs.usage()['reserved'], 0)

    def test_official_validation_cannot_be_disabled(self):
        for endpoint in ('/api/v1/jobs/preview', '/api/v1/jobs'):
            with self.subTest(endpoint=endpoint):
                result = self.client.post(endpoint, json={**self.body, 'validate': False}, headers=self.headers)
                self.assertEqual(result.status_code, 422, result.text)
                self.assertIn('validate', result.json()['field_errors'])
        self.assertEqual(self.client.get('/api/v1/jobs').json()['data']['items'], [])

    def test_unknown_and_joint_parameters_rejected(self):
        bad = self.client.post('/api/v1/jobs', json={**self.body, 'command': 'anything'}, headers=self.headers)
        self.assertEqual(bad.status_code, 422)
        body = {**self.body, 'task': 'invsqrt', 'parameters': {'delta_bits': 18, 'coef_bits': 17}}
        bad = self.client.post('/api/v1/jobs/preview', json=body, headers=self.headers)
        self.assertEqual(bad.status_code, 422, bad.text)

    def test_readonly_instance_cannot_enqueue(self):
        app = create_app(self.config, read_only=True, key_path=self.key)
        with TestClient(app, base_url='http://127.0.0.1:8765') as client:
            csrf = client.post('/api/v1/session', json={'key': 'fixture-session-key'}).json()['csrf_token']
            headers = {**self.headers, 'X-CSRF-Token': csrf}
            self.assertEqual(client.post('/api/v1/jobs', json=self.body, headers=headers).status_code, 409)
            self.assertEqual(client.post('/api/v1/jobs/preview', json=self.body, headers=headers).status_code, 200)

    def test_openapi_and_config_revision_conflict(self):
        schema = self.client.get('/api/v1/openapi.json').json()
        self.assertIn('/api/v1/jobs', schema['paths'])
        self.assertIn('/api/v1/tasks/history', schema['paths'])
        current = self.client.get('/api/v1/config')
        self.assertEqual(current.status_code, 200, current.text)
        current = current.json()['data']
        body = {'config': {**current['config'], 'daily_model_limit': 7}, 'expected_revision': current['revision']}
        result = self.client.post('/api/v1/config/revisions', json=body, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        body['config']['daily_model_limit'] = 8
        result = self.client.post('/api/v1/config/revisions', json=body,
                                  headers={**self.headers, 'Idempotency-Key': 'second-config'})
        self.assertEqual(result.status_code, 409, result.text)

    def test_task_history_endpoint_filters_and_wraps_empty_history(self):
        all_tasks = self.client.get('/api/v1/tasks/history')
        self.assertEqual(all_tasks.status_code, 200, all_tasks.text)
        payload = all_tasks.json()
        self.assertEqual([item['task'] for item in payload['data']['items']],
                         ['dqi', 'invsqrt', 'dfthcsos'])
        self.assertIn('revision', payload)
        selected = self.client.get('/api/v1/tasks/history?task=invsqrt')
        self.assertEqual([item['task'] for item in selected.json()['data']['items']], ['invsqrt'])
        invalid = self.client.get('/api/v1/tasks/history?task=unknown')
        self.assertEqual(invalid.status_code, 422)


if __name__ == '__main__':
    unittest.main()
