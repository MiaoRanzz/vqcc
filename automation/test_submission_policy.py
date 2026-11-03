"""Daily success quota behavior; no network calls or competition verification."""
from datetime import datetime
import unittest

from submission_policy import submission_allowance, submission_skip_reason


class SuccessfulSubmissionQuotaTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            'submission_policy': 'daily_windows',
            'submission_quota_basis': 'successful_submissions',
            'max_daily_submissions': 3, 'submission_quota_timezone': 'UTC',
            'timezone': 'Asia/Shanghai', 'daily_submission_times': ['08:00', '20:00'],
            'submit_window_minutes': 45, 'deadline': '2099-01-01T00:00:00+08:00',
        }
        self.now = datetime.fromisoformat('2026-11-03T20:00:00+08:00')
        self.state = {'submissions': {}}

    def add(self, token, status, sid=None, **extra):
        self.state['submissions'][token] = {
            'status': status, 'submission_id': sid,
            'reserved_at': '2026-11-03T09:00:00+08:00', **extra,
        }

    def allowance(self):
        return submission_allowance(self.state, self.config, self.now)

    def test_failures_keep_attempt_history_without_consuming_success_limit(self):
        for status in ('upload_started', 'not_submitted', 'rejected', 'submitted', 'score_unknown'):
            self.add(status, status)
        self.add('prepared', 'prepared')
        quota = self.allowance()
        self.assertEqual(quota['attempts_today'], 5)
        self.assertEqual(quota['successes_today'], 0)
        self.assertEqual(quota['remaining_today'], 3)
        self.assertEqual(submission_skip_reason(self.state, None, self.config, self.now),
                         'previous_submission_needs_reconciliation')

    def test_three_distinct_ids_exhaust_quota_regardless_of_grading(self):
        for sid, status in enumerate(('score_unknown', 'scored', 'rejected'), start=101):
            self.add(status, status, sid)
        self.add('duplicate', 'submitted', 101)
        self.add('failed', 'not_submitted')
        self.assertEqual(self.allowance()['attempts_today'], 5)
        self.assertEqual(self.allowance()['successes_today'], 3)
        self.assertEqual(self.allowance()['quota_used_today'], 3)
        self.assertEqual(self.allowance()['remaining_today'], 0)
        self.assertEqual(submission_skip_reason(self.state, None, self.config, self.now),
                         'daily_submission_limit_reached')

    def test_invalid_ids_never_count_as_success(self):
        for index, sid in enumerate((None, 0, -1, True, '', '123', 1.5)):
            self.add(str(index), 'rejected', sid)
        self.assertEqual(self.allowance()['successes_today'], 0)
        self.assertEqual(self.allowance()['remaining_today'], 3)

    def test_old_policy_failures_do_not_consume_new_success_limit(self):
        self.add('old-success', 'score_unknown', 101, submission_policy='after_optimization')
        self.add('old-failure', 'not_submitted', submission_policy='after_optimization',
                 resolution={'quota_reservation_retained': True})
        self.assertEqual(self.allowance()['attempts_today'], 2)
        self.assertEqual(self.allowance()['successes_today'], 1)
        self.assertEqual(self.allowance()['remaining_today'], 2)
        self.assertIsNone(submission_skip_reason(self.state, None, self.config, self.now))

    def test_submission_date_wins_over_reservation_day_and_resets_at_utc_midnight(self):
        self.add('crossed-midnight', 'score_unknown', 101,
                 reserved_at='2026-11-03T07:59:00+08:00', quota_date='2026-11-02',
                 quota_timezone='UTC', receipt={'date': '2026-11-03T00:01:00Z'})
        self.add('id-only', 'score_unknown', 102,
                 reserved_at='2026-11-03T07:59:00+08:00', accepted_at='2026-11-03T08:02:00+08:00')
        self.assertEqual(self.allowance()['attempts_today'], 0)
        self.assertEqual(self.allowance()['successes_today'], 2)
        self.now = datetime.fromisoformat('2026-11-04T00:01:00+08:00')
        self.assertEqual(self.allowance()['remaining_today'], 1)
        self.now = datetime.fromisoformat('2026-11-04T08:00:00+08:00')
        self.assertEqual(self.allowance()['successes_today'], 0)
        self.assertEqual(self.allowance()['remaining_today'], 3)

    def test_failed_attempt_still_uses_its_window(self):
        self.add('failed', 'not_submitted', reserved_at='2026-11-03T20:00:00+08:00')
        self.assertEqual(self.allowance()['remaining_today'], 3)
        self.assertEqual(self.allowance()['window_attempts'], 1)
        self.assertEqual(submission_skip_reason(self.state, None, self.config, self.now),
                         'already_attempted_window')

    def test_historical_configs_keep_attempt_based_semantics(self):
        self.config.pop('submission_quota_basis')
        self.add('failed', 'not_submitted')
        self.assertEqual(self.allowance()['quota_basis'], 'attempts')
        self.assertEqual(self.allowance()['remaining_today'], 2)


if __name__ == '__main__':
    unittest.main()
