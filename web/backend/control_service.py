"""Small, durable research edits; execution policy is owned by automation.jobs."""
import fcntl
import hashlib
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone
from automation.jobs import ControlError, atomic_json


class ResearchControl:
    def __init__(self, storage):
        self.root = Path(storage) / 'console'

    def update(self, research_id, body, key):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / 'research.json'
        with (self.root / 'research.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(path.read_text()) if path.exists() else {'revision': 0, 'overrides': {}, 'operations': {}}
            fingerprint = hashlib.sha256(json.dumps([research_id, body], sort_keys=True).encode()).hexdigest()
            if key in state['operations']:
                operation = state['operations'][key]
                if operation['fingerprint'] != fingerprint:
                    raise ControlError('STATE_CONFLICT', '同一操作标识对应不同内容')
                return operation['result']
            if body['expected_revision'] != state['revision']:
                raise ControlError('CONFIG_CONFLICT', '研究记录已更新，请刷新后重试', current_revision=state['revision'])
            changes = {k: v for k, v in body.items() if k != 'expected_revision'}
            previous = state['overrides'].get(research_id, {})
            at = datetime.now(timezone.utc).isoformat()
            changes['history'] = previous.get('history', []) + [{'at': at, 'changes': changes.copy()}]
            state['overrides'][research_id] = changes
            state['revision'] += 1
            result = {'operation_id': 'op_' + uuid.uuid4().hex, 'id': research_id,
                      'revision': state['revision'], 'status': 'updated', 'observed_at': at}
            state['operations'][key] = {'fingerprint': fingerprint, 'result': result}
            atomic_json(path, state)
            return result
