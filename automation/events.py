"""Append-only structured run events, complete-line cursors, and resource samples."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid


def now_string():
    return datetime.now(timezone.utc).isoformat()


def emit(run_dir, event_type, *, job_id=None, run_id=None, stage=None, message=None, **details):
    event = {'event_id': uuid.uuid4().hex, 'at': now_string(), 'type': event_type,
             'job_id': job_id, 'run_id': run_id or Path(run_dir).name,
             'stage': stage, 'message': message, 'progress': None, **details}
    with (Path(run_dir) / 'timeline.jsonl').open('a') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        stream.flush()
    return event


def complete_lines(path, offset=0):
    """Return only committed JSONL lines and their next byte cursor."""
    path = Path(path)
    if not path.exists():
        return [], 0
    with path.open('rb') as stream:
        if offset > path.stat().st_size:
            offset = 0
        stream.seek(offset)
        records = []
        while line := stream.readline():
            if not line.endswith(b'\n'):
                break
            records.append(json.loads(line))
            offset = stream.tell()
    return records, offset


def cpu_seconds(pids):
    total = 0
    for pid in pids:
        try:
            values = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            total += int(values[11]) + int(values[12])
        except FileNotFoundError:
            continue
    return total / os.sysconf('SC_CLK_TCK')
