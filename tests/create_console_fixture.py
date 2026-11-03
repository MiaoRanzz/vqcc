"""Create an isolated browser fixture from small, existing metadata; never starts work."""
import argparse
import json
from pathlib import Path
import secrets
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from automation.jobs import Jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='A new directory, usually beneath /tmp')
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True)
    store = directory / 'store'
    store.mkdir()
    config = json.loads((ROOT / 'automation/config.json').read_text())
    source = Path(config['storage_root'])
    config.update(storage_root=str(store), min_free_gib=0, deadline='2099-01-01T00:00:00+08:00')
    path = directory / 'config.json'
    path.write_text(json.dumps(config))
    for name in ('state/pipeline.json', 'research/hypotheses.json', 'research/cursors.json'):
        target = store / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    state = json.loads((store / 'state/pipeline.json').read_text())
    ids = set(state['best'].values())
    for task in ('dqi', 'invsqrt', 'dfthcsos'):
        ids.add(f'baseline-20261029-{task}')
    for submission in state.get('submissions', {}).values():
        if submission.get('public_score') is not None:
            ids.update((submission.get('selected') or {}).values())
    for candidate_id in ids:
        origin = source / 'experiments' / candidate_id
        if not (origin / 'candidate.json').is_file():
            continue
        target = store / 'experiments' / candidate_id
        target.mkdir(parents=True)
        item = json.loads((origin / 'candidate.json').read_text())
        names = ['candidate.json', 'generation.json']
        if item.get('verification'):
            names.append(item['verification']['report'])
        for name in names:
            if (origin / name).is_file():
                shutil.copy2(origin / name, target / name)
    jobs = Jobs(path, initialize=True)
    with jobs.transaction() as control:
        control['jobs']['fixture-completed'] = {
            'job_id': 'fixture-completed', 'revision': 1,
            'kind': 'local_experiment', 'task': 'dqi', 'state': 'completed',
            'origin': 'fixture', 'created_at': '2026-10-29T16:00:00+08:00',
            'started_at': '2026-10-29T16:01:00+08:00',
            'finished_at': '2026-10-29T16:02:00+08:00',
            'run_id': None, 'max_seconds': 120,
            'hypothesis': '隔离浏览器验收所需的完成任务元数据',
            'candidate_ids': [], 'blocked_reason': None,
            'config_revision': control['active_revision'],
        }
    key = directory / 'session-key'
    key.write_text(secrets.token_urlsafe(32) + '\n')
    key.chmod(0o600)
    print(f'Fixture config: {path}\nSession key file: {key}\nNo scheduler or computation was started.')


if __name__ == '__main__':
    main()
