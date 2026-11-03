"""Project model defaults; never writes global Codex or Claude Code settings."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MODEL_KINDS = {'optimize', 'smoke', 'submit', 'reconcile'}
AGENT_BACKENDS = {'codex', 'claude'}
# Claude Code accepts low..max; map the console's wider scale onto it.
CLAUDE_EFFORT = {'minimal': 'low', 'low': 'low', 'medium': 'medium', 'high': 'high',
                 'xhigh': 'xhigh', 'max': 'max', 'ultra': 'max'}
# Identity of an interactive agent session; a scheduled child must start its own.
SESSION_VARIABLES = {'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT', 'CLAUDE_AGENT_SDK_VERSION',
                     'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_EXECPATH', 'CLAUDE_CODE_SSE_PORT'}
SESSION_PREFIXES = ('CLAUDE_CODE_SESSION', 'CLAUDE_CODE_CHILD', 'CLAUDE_CODE_MESSAGING')


def agent_backend(config):
    backend = config.get('agent_backend', 'codex')
    if backend not in AGENT_BACKENDS:
        raise ValueError(f'Unknown agent_backend {backend!r}; expected one of {sorted(AGENT_BACKENDS)}')
    return backend


def _json_file(path):
    try:
        return json.loads(path.read_text()) if path.is_file() else {}
    except ValueError:
        return {}


def imported_model(config):
    if agent_backend(config) == 'claude':
        home = Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude'))
        combined = {}
        for path in (home / 'settings.json', ROOT / '.claude/settings.json', ROOT / '.claude/settings.local.json'):
            combined.update(_json_file(path))
        values = {'model': config.get('claude_model', combined.get('model', 'opus')),
                  'reasoning': config.get('claude_reasoning', combined.get('effortLevel', 'high'))}
        return {'model': values['model'], 'reasoning': values['reasoning'], 'service_tier': 'default'}
    path = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'config.toml'
    global_config = tomllib.loads(path.read_text()) if path.exists() else {}
    project_path = ROOT / '.codex/config.toml'
    project_config = tomllib.loads(project_path.read_text()) if project_path.exists() else {}
    combined = {**global_config, **project_config}
    profile = combined.get('profiles', {}).get(combined.get('profile'), {})
    values = {**combined, **profile, **config}
    return {
        'model': values.get('model'),
        'reasoning': values.get('reasoning', values.get('model_reasoning_effort', 'medium')),
        'service_tier': values.get('service_tier', 'default'),
    }


def generator_revision():
    digest = hashlib.sha256()
    for name in ('generate.py', 'dqi_adapter.py', 'dfthcsos_prefix.py'):
        path = ROOT / 'generators' / name
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def model_arguments(model, backend='codex'):
    if backend == 'claude':
        # Claude Code has no service tier switch; the console value is recorded only.
        return ['--model', model['model'], '--effort', CLAUDE_EFFORT.get(model['reasoning'], 'high')]
    return ['--model', model['model'], '-c', 'model_reasoning_effort=' + json.dumps(model['reasoning']),
            '-c', 'service_tier=' + json.dumps(model['service_tier'])]


def agent_command(cfg, job, storage, run_dir):
    """Non-interactive agent invocation reading the prompt from stdin."""
    backend = agent_backend(cfg)
    models = model_arguments(job, backend) if job else []
    if backend == 'claude':
        # stream-json carries no last-message file; runner writes report.md from the result event.
        return [cfg.get('claude_executable', 'claude'), '-p', '--output-format', 'stream-json', '--verbose',
                '--no-session-persistence', '--permission-mode', cfg.get('claude_permission_mode', 'bypassPermissions'),
                '--add-dir', str(storage)] + models
    return ([cfg['codex_executable'], 'exec', '--approve-for-me', '--ephemeral', '--add-dir', str(storage), '-C', str(ROOT),
             '--json', '--color', 'never', '--output-last-message', str(Path(run_dir) / 'report.md')] + models + ['-'])


def session_free_environment(environment):
    """Drop interactive Codex/Claude Code session identifiers; keep auth and config homes."""
    return {key: value for key, value in environment.items()
            if not (key.startswith('CODEX_') and key != 'CODEX_HOME')
            and key not in SESSION_VARIABLES and not key.startswith(SESSION_PREFIXES)}
