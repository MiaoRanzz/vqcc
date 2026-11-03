"""One incremental JSONL reader and bounded SSE replay buffer per Web instance."""
from collections import deque
import json
from pathlib import Path
import threading
import time
import uuid
from automation.runner import event_summary, redact


class EventFeed:
    def __init__(self, storage: Path, capacity=1000):
        self.storage = storage
        self.events = deque(maxlen=capacity)
        self.offsets = {}
        self.epoch = uuid.uuid4().hex[:10]
        self.sequence = 0
        self.lock = threading.Lock()
        self.last_scan = 0
        self.paths = []
        self.state_stamp = None

    def append(self, event):
        self.sequence += 1
        cursor = f'{self.epoch}:{self.sequence}'
        self.events.append((cursor, event))

    def poll(self):
        with self.lock:
            if time.monotonic() - self.last_scan >= 5:
                runs = self.storage / 'runs'
                self.paths = sorted(runs.glob('*/timeline.jsonl')) + sorted(runs.glob('*/events.jsonl'))
                self.last_scan = time.monotonic()
            state_path = self.storage / 'console/state.json'
            stamp = state_path.stat().st_mtime_ns if state_path.exists() else None
            if stamp != self.state_stamp:
                self.append({'type': 'state.changed'})
                self.state_stamp = stamp
            for path in self.paths:
                if not path.resolve().is_relative_to(self.storage.resolve() / 'runs'):
                    continue
                try:
                    stat = path.stat()
                    stream = path.open('rb')
                except FileNotFoundError:
                    continue
                identity, offset = self.offsets.get(path, (stat.st_ino, max(0, stat.st_size - 131072)))
                replaced = identity != stat.st_ino or stat.st_size < offset
                if replaced:
                    offset = 0
                if stat.st_size == offset:
                    stream.close()
                    continue
                with stream:
                    stream.seek(offset)
                    if path not in self.offsets and offset:
                        stream.readline()  # Drop only the first incomplete historical line.
                    while True:
                        start = stream.tell()
                        line = stream.readline()
                        if not line.endswith(b'\n'):
                            offset = start
                            break
                        offset = stream.tell()
                        try:
                            event = json.loads(line)
                        except (ValueError, UnicodeDecodeError):
                            continue
                        if path.name == 'events.jsonl':
                            # Only the runner's persisted summaries, never raw tool payloads.
                            event = {k: event[k] for k in ('type', 'at', 'usage', 'item_type', 'status', 'text') if k in event}
                        event['run_id'] = path.parent.name
                        self.append(json.loads(redact(json.dumps(event, ensure_ascii=False))))
                self.offsets[path] = (stat.st_ino, offset)

    def replay(self, cursor=None, run_id=None):
        self.poll()
        with self.lock:
            events = list(self.events)
            ids = [item[0] for item in events]
            resync = cursor is not None and cursor not in ids
            start = ids.index(cursor) + 1 if cursor in ids else 0
            selected = [(key, value) for key, value in events[start:]
                        if run_id is None or value.get('run_id') in (None, run_id)]
            # Advance even when the run filter excludes events.
            newest = ids[-1] if ids else None
            return selected, resync, newest
