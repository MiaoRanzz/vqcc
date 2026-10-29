import datetime as dt
import json
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

from runner import event_summary, proc_table, redact, select_slot


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((Path(__file__).parent / 'config.json').read_text())

    def at(self, value):
        return dt.datetime.fromisoformat(value)

    def test_utc_host_maps_to_shanghai_submission_window(self):
        slot = select_slot(self.cfg, self.at('2026-10-30T12:00:00+00:00'))
        self.assertEqual(slot[:2], ('2026-10-30-submit', 'submit'))
        self.assertIsNone(select_slot(self.cfg, self.at('2026-10-30T11:59:00+00:00')))
        self.assertIsNone(select_slot(self.cfg, self.at('2026-10-30T12:45:00+00:00')))

    def test_last_optimization_cannot_run_through_submit(self):
        _, mode, budget = select_slot(self.cfg, self.at('2026-10-30T19:00:00+08:00'))
        self.assertEqual(mode, 'optimize')
        self.assertEqual(budget, 25 * 60)

    def test_deadline_and_no_backfill(self):
        self.assertIsNone(select_slot(self.cfg, self.at('2027-01-21T07:59:00+08:00')))
        self.assertIsNone(select_slot(self.cfg, self.at('2026-10-30T23:30:00+08:00')))
        _, _, seconds = select_slot(self.cfg, self.at('2027-01-21T07:00:00+08:00'))
        self.assertEqual(seconds, 59 * 60)

    def test_events_do_not_persist_upload_credentials(self):
        event = {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'tool': 'upload', 'arguments': {'token': 'secret'}, 'result': {'url': 'https://host/path?sig=secret'}}}
        text = json.dumps(event_summary(json.dumps(event)))
        self.assertNotIn('secret', text)
        self.assertNotIn('arguments', text)
        self.assertNotIn('sig=', redact('https://host/path?sig=secret'))
        self.assertNotIn('DUMMY_SECRET', redact('{"access_token":"DUMMY_SECRET"}'))
        self.assertNotIn('DUMMY_SECRET', redact("{'refresh_token': 'DUMMY_SECRET'}"))
        self.assertNotIn('DUMMY_SECRET', redact('{"Authorization": "Bearer DUMMY_SECRET"}'))
        self.assertNotIn('DUMMY_SECRET', redact('{"Authorization": "Basic DUMMY_SECRET"}'))

    def test_proc_rss_reads_real_current_process(self):
        import os
        self.assertGreater(proc_table()[os.getpid()][2], 0)


if __name__ == '__main__':
    unittest.main()
