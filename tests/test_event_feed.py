import json
from pathlib import Path
import tempfile
import unittest
from web.backend.event_feed import EventFeed


class EventFeedTests(unittest.TestCase):
    def test_removed_file_and_outside_symlink_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storage = root / 'store'
            directory = storage / 'runs/run-a'
            directory.mkdir(parents=True)
            outside = root / 'outside.jsonl'
            outside.write_text('{"type":"private"}\n')
            (directory / 'timeline.jsonl').symlink_to(outside)
            feed = EventFeed(storage)
            self.assertEqual(feed.replay()[0], [])
            missing = directory / 'events.jsonl'
            feed.paths.append(missing)
            self.assertEqual(feed.replay()[0], [])

    def test_partial_line_replay_and_rotation(self):
        with tempfile.TemporaryDirectory() as temp:
            storage = Path(temp)
            path = storage / 'runs/run-a/timeline.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text('{"type":"stage.started"}\n{"type":')
            feed = EventFeed(storage)
            first, reset, cursor = feed.replay()
            self.assertEqual(len(first), 1)
            self.assertFalse(reset)
            with path.open('a') as stream:
                stream.write('"stage.completed"}\n')
            second, reset, latest = feed.replay(cursor)
            self.assertEqual(len(second), 1)
            self.assertEqual(second[0][1]['type'], 'stage.completed')
            self.assertEqual(feed.replay(latest)[0], [])
            replacement = path.with_suffix('.tmp')
            replacement.write_text('{"type":"new"}\n')
            replacement.replace(path)
            self.assertEqual(feed.replay(latest)[0][0][1]['type'], 'new')
            self.assertTrue(feed.replay('lost-instance:1')[1])

    def test_legacy_events_do_not_leak_tools_or_signed_urls(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'runs/r/events.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'type': 'item.completed', 'arguments': {'secret': 'hidden'},
                                       'text': 'https://example.com/path?sig=private'}) + '\n')
            text = json.dumps(EventFeed(Path(temp)).replay()[0])
            self.assertNotIn('hidden', text)
            self.assertNotIn('sig=private', text)


if __name__ == '__main__':
    unittest.main()
