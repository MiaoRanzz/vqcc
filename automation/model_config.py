"""Project model defaults; never writes global Codex settings."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MODEL_KINDS = {'optimize', 'smoke', 'submit', 'reconcile'}


def imported_model(config):
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


def model_arguments(model):
    return ['--model', model['model'], '-c', 'model_reasoning_effort=' + json.dumps(model['reasoning']),
            '-c', 'service_tier=' + json.dumps(model['service_tier'])]
