import datetime as dt
import json
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

from runner import event_summary, proc_table, redact, select_slot


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((Path(__file__).parent / 'config.json').read_text())
        # Pin the earlier schedule; these cases test slot logic, not the current deployment.
        for key in ('submission_timezone', 'optimize_slot_minutes'):
            self.cfg.pop(key, None)
        self.cfg.update(submission_policy='daily_window', daily_submission_time='20:00', submit_window_minutes=45,
                        reconcile_time='20:55',
                        optimize_windows=[['00:10', '05:55'], ['06:10', '07:25'], ['09:10', '11:55'],
                                          ['12:10', '17:55'], ['18:10', '19:25']])

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
        cfg = {**self.cfg, 'optimize_windows': [['06:10', '11:55']]}
        _, _, seconds = select_slot(cfg, self.at('2027-01-21T07:00:00+08:00'))
        self.assertEqual(seconds, 59 * 60)

    def test_after_optimization_removes_fixed_submit_slot_but_keeps_daily_query(self):
        cfg = {**self.cfg, 'submission_policy': 'after_optimization'}
        self.assertIsNone(select_slot(cfg, self.at('2026-10-30T20:00:00+08:00')))
        self.assertEqual(select_slot(cfg, self.at('2026-10-30T20:55:00+08:00'))[1], 'reconcile')
        self.assertEqual(select_slot(cfg, self.at('2026-10-30T10:00:00+08:00'))[1], 'optimize')
        self.assertIsNone(select_slot(cfg, self.at('2027-01-21T07:59:00+08:00')))

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

    def test_twice_daily_windows_have_distinct_slots_and_boundaries(self):
        cfg = {**self.cfg, 'submission_policy': 'daily_windows',
               'daily_submission_times': ['08:00', '20:00']}
        for hour, utc in (('08', '00'), ('20', '12')):
            slot = select_slot(cfg, self.at(f'2026-10-30T{utc}:00:00+00:00'))
            self.assertEqual(slot[:2], (f'2026-10-30-submit-{hour}00', 'submit'))
            last = select_slot(cfg, self.at(f'2026-10-30T{hour}:44:59+08:00'))
            self.assertEqual(last[2], 1)
            after = select_slot(cfg, self.at(f'2026-10-30T{hour}:45:00+08:00'))
            self.assertTrue(after is None or after[1] != 'submit')
        self.assertIsNone(select_slot(cfg, self.at('2026-10-30T07:59:00+08:00')))
        self.assertIsNone(select_slot(cfg, self.at('2027-01-21T08:00:00+08:00')))

    def test_morning_optimization_budget_stops_before_upload(self):
        cfg = {**self.cfg, 'submission_policy': 'daily_windows',
               'daily_submission_times': ['08:00', '20:00'],
               'optimize_windows': [['06:10', '11:55']]}
        slot = select_slot(cfg, self.at('2026-10-30T06:10:00+08:00'))
        self.assertEqual(slot[1:], ('optimize', 75 * 60))
        self.assertIsNone(select_slot(cfg, self.at('2026-10-30T07:25:00+08:00')))

    def test_deployed_daily_utc_submission_and_relay_optimization(self):
        cfg = json.loads((Path(__file__).parent / 'config.json').read_text())
        # One submission at 23:40 UTC, inside the UTC quota day.
        self.assertEqual(select_slot(cfg, self.at('2026-11-03T23:40:00+00:00'))[:2], ('2026-11-04-submit-2340', 'submit'))
        self.assertEqual(select_slot(cfg, self.at('2026-11-03T23:59:00+00:00'))[2], 60)
        self.assertIsNone(select_slot(cfg, self.at('2026-11-03T23:10:00+00:00')))
        self.assertIsNone(select_slot(cfg, self.at('2026-11-04T07:00:00+08:00')))
        # A run before the upload stops at the 35 minute protection.
        _, mode, seconds = select_slot(cfg, self.at('2026-11-04T05:00:00+08:00'))
        self.assertEqual((mode, seconds), ('optimize', 2 * 3600 + 5 * 60))
        # Hourly relay slots; runs stop before reconciliation, which then yields back.
        self.assertEqual(select_slot(cfg, self.at('2026-11-04T08:30:00+08:00')), ('2026-11-04-optimize-0800', 'optimize', 20 * 60))
        self.assertIsNone(select_slot(cfg, self.at('2026-11-04T08:46:00+08:00')))
        self.assertEqual(select_slot(cfg, self.at('2026-11-04T09:10:00+08:00'))[:2], ('2026-11-04-reconcile', 'reconcile'))
        taken = lambda slot_id: slot_id == '2026-11-04-reconcile'
        self.assertIsNone(select_slot(cfg, self.at('2026-11-04T09:10:00+08:00'), taken))
        slot = select_slot(cfg, self.at('2026-11-04T09:20:00+08:00'), taken)
        self.assertEqual(slot, ('2026-11-04-optimize-0900', 'optimize', cfg['max_agent_seconds']))
        self.assertEqual(select_slot(cfg, self.at('2026-11-04T21:59:00+08:00'))[:2], ('2026-11-04-optimize-2100', 'optimize'))
        _, _, seconds = select_slot(cfg, self.at('2026-11-04T22:00:00+08:00'))
        self.assertEqual(seconds, 119 * 60)

    def test_proc_rss_reads_real_current_process(self):
        import os
        self.assertGreater(proc_table()[os.getpid()][2], 0)


if __name__ == '__main__':
    unittest.main()
