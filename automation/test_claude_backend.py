"""Claude Code backend: command shape, stream-json summaries and a fake-agent process run."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'automation'))

from model_config import agent_command, imported_model, model_arguments, session_free_environment  # noqa: E402
from runner import claude_report, event_summary  # noqa: E402

BASE_CONFIG = json.loads((ROOT / 'automation/config.json').read_text())
JOB = {'model': 'opus', 'reasoning': 'ultra', 'service_tier': 'priority'}


class ClaudeCommandTests(unittest.TestCase):
    def test_codex_remains_default(self):
        cfg = {k: v for k, v in BASE_CONFIG.items() if k != 'agent_backend'}
        command = agent_command(cfg, JOB, '/storage', '/run')
        self.assertEqual(command[:2], [cfg['codex_executable'], 'exec'])
        self.assertEqual(command[-1], '-')

    def test_claude_command_is_headless_and_bounded_to_storage(self):
        cfg = dict(BASE_CONFIG, agent_backend='claude', claude_executable='/bin/claude')
        command = agent_command(cfg, JOB, '/storage', '/run')
        self.assertEqual(command[:2], ['/bin/claude', '-p'])
        self.assertIn('stream-json', command)
        self.assertIn('--no-session-persistence', command)
        self.assertEqual(command[command.index('--add-dir') + 1], '/storage')
        self.assertEqual(command[command.index('--permission-mode') + 1], 'bypassPermissions')
        self.assertEqual(model_arguments(JOB, 'claude'), ['--model', 'opus', '--effort', 'max'])

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(ValueError):
            agent_command(dict(BASE_CONFIG, agent_backend='other'), JOB, '/s', '/r')

    def test_claude_defaults_come_from_project_config(self):
        cfg = dict(BASE_CONFIG, agent_backend='claude', claude_model='sonnet', claude_reasoning='medium')
        self.assertEqual(imported_model(cfg), {'model': 'sonnet', 'reasoning': 'medium', 'service_tier': 'default'})

    def test_interactive_session_variables_are_dropped(self):
        env = session_free_environment({'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'x', 'CLAUDE_CODE_ENTRYPOINT': 'cli',
                                        'CLAUDE_CODE_MESSAGING_TOKEN': 't', 'CODEX_THREAD': 'x', 'CODEX_HOME': '/c',
                                        'CLAUDE_CONFIG_DIR': '/cfg', 'ANTHROPIC_API_KEY': 'k', 'PATH': '/bin'})
        self.assertEqual(env, {'CODEX_HOME': '/c', 'CLAUDE_CONFIG_DIR': '/cfg', 'ANTHROPIC_API_KEY': 'k', 'PATH': '/bin'})


class StreamJsonSummaryTests(unittest.TestCase):
    def test_tool_inputs_and_results_are_not_persisted(self):
        tool = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'curl https://x?sig=SECRET'}}],
                                                  'usage': {'input_tokens': 5}}}
        summary = event_summary(json.dumps(tool))
        self.assertEqual(summary, {'type': 'assistant', 'item_type': 'tool_use', 'tool': 'Bash'})
        reply = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'access_token=SECRET'}]}}
        self.assertNotIn('SECRET', json.dumps(event_summary(json.dumps(reply))))

    def test_text_init_and_result(self):
        text = event_summary(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'see https://a/b?token=1'}]}}))
        self.assertEqual(text['text'], 'see https://a/b?[redacted]')
        init = event_summary(json.dumps({'type': 'system', 'subtype': 'init', 'model': 'claude-opus-5-5', 'tools': ['Bash']}))
        self.assertEqual(init, {'type': 'system', 'item_type': None, 'subtype': 'init', 'model': 'claude-opus-5-5'})
        raw = json.dumps({'type': 'result', 'subtype': 'success', 'result': 'done', 'is_error': False, 'num_turns': 3,
                          'total_cost_usd': 0.5, 'usage': {'input_tokens': 10, 'output_tokens': 2}})
        result = event_summary(raw)
        self.assertEqual(result['usage'], {'input_tokens': 10, 'output_tokens': 2})
        self.assertNotIn('result', result)
        self.assertEqual(claude_report(raw), 'done')
        self.assertIsNone(claude_report(json.dumps({'type': 'assistant'})))


@unittest.skipUnless(sys.platform == 'linux', 'Linux process supervision')
class ClaudeProcessTests(unittest.TestCase):
    def test_fake_claude_run_writes_report_and_events(self):
        with tempfile.TemporaryDirectory(prefix='vqcc-claude-test-') as temp:
            base = Path(temp)
            storage = base / 'storage'
            (storage / 'runtime').mkdir(parents=True)
            fake = base / 'fake-claude'
            seen = base / 'seen.json'
            fake.write_text(f'#!{sys.executable}\n' + textwrap.dedent(f"""
                import json,os,sys
                from pathlib import Path
                prompt = sys.stdin.read()
                Path({str(seen)!r}).write_text(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd(),
                    'claudecode': os.environ.get('CLAUDECODE'), 'has_prompt': 'Runtime context' in prompt}}))
                for event in ({{'type': 'system', 'subtype': 'init', 'model': 'fake'}},
                              {{'type': 'assistant', 'message': {{'content': [{{'type': 'text', 'text': 'working'}}]}}}},
                              {{'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'Fake report',
                                'usage': {{'input_tokens': 7, 'output_tokens': 1}}}}):
                    print(json.dumps(event), flush=True)
            """))
            fake.chmod(0o700)
            config = dict(BASE_CONFIG, storage_root=str(storage), python_executable=sys.executable, min_free_gib=0,
                          cpu_limit=1, memory_gib=1, memory_stop_gib=0.8, agent_backend='claude', claude_executable=str(fake))
            config_path = base / 'config.json'
            config_path.write_text(json.dumps(config))
            driver = textwrap.dedent(f"""
                import json,sys
                from pathlib import Path
                sys.path.insert(0, {str(ROOT / 'automation')!r})
                from runner import execute,load_config
                path=Path({str(config_path)!r})
                cfg=load_config(path)
                print(json.dumps(execute('smoke',cfg,path,10,'test-slot',Path(cfg['storage_root'])/'runtime'/'result.json')))
            """)
            env = {k: v for k, v in os.environ.items() if not k.startswith(('VQCC_', 'CODEX_'))}
            env.update(VQCC_ENV_PREFIX=sys.prefix, VQCC_CONDA_ENV='vqcc', PYTHONDONTWRITEBYTECODE='1', CLAUDECODE='1')
            run = subprocess.run([sys.executable, '-c', driver], env=env, cwd=base, capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(result['status'], 'completed')
            run_dir = Path(result['run_dir'])
            self.assertEqual((run_dir / 'report.md').read_text(), 'Fake report')
            events = [json.loads(line) for line in (run_dir / 'events.jsonl').read_text().splitlines()]
            self.assertEqual([event['type'] for event in events], ['system', 'assistant', 'result'])
            self.assertEqual(json.loads((run_dir / 'context.json').read_text())['agent_backend'], 'claude')
            observed = json.loads(seen.read_text())
            self.assertEqual(observed['cwd'], str(ROOT))
            self.assertIsNone(observed['claudecode'])
            self.assertTrue(observed['has_prompt'])
            self.assertEqual(observed['argv'][0], '-p')


if __name__ == '__main__':
    unittest.main()
