"""Submission eligibility shared by pipeline, queue and console projections."""
from datetime import datetime, time, timedelta
import math
from zoneinfo import ZoneInfo

ATTEMPTED = {'upload_started', 'submitted', 'score_unknown', 'scored', 'rejected', 'not_submitted'}
INFLIGHT = {'upload_started', 'submitted', 'score_unknown'}


def after_optimization(config):
    return config.get('submission_policy', 'daily_window') == 'after_optimization'


def submission_windows(config, now):
    """Configured submission intervals on the current calendar day of their zone.

    `submission_timezone` lets times be written in UTC; it defaults to the scheduler zone.
    """
    zone = config.get('submission_timezone', config.get('timezone', 'Asia/Shanghai'))
    local = now.astimezone(ZoneInfo(zone))
    times = (config.get('daily_submission_times', [])
             if config.get('submission_policy') == 'daily_windows'
             else [config.get('daily_submission_time', '20:00')])
    if not times or len(set(times)) != len(times):
        raise ValueError('Submission times must be a nonempty list without duplicates')
    starts = sorted(datetime.combine(local.date(), time.fromisoformat(value), local.tzinfo)
                    for value in times)
    duration = timedelta(minutes=config.get('submit_window_minutes', 45))
    if duration <= timedelta(0) or any(a + duration > b for a, b in zip(starts, starts[1:])):
        raise ValueError('Submission windows must be positive and nonoverlapping')
    return [(start, start + duration) for start in starts]


def _platform_quota(config):
    return config.get('submission_policy') in {'after_optimization', 'daily_windows'}


def submission_quota_date(item, config):
    zone = config.get('submission_quota_timezone', 'UTC') if _platform_quota(config) else config.get('timezone', 'Asia/Shanghai')
    if not _platform_quota(config):
        return item.get('date')
    if item.get('quota_timezone') == zone and item.get('quota_date'):
        return item['quota_date']
    receipt = item.get('receipt', {})
    stamp = item.get('reserved_at') or receipt.get('date') or receipt.get('submittedAt') or item.get('created_at')
    if stamp:
        return datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(ZoneInfo(zone)).date().isoformat()
    # Old date-only evidence remains readable; submit mode also checks remote quota.
    return item.get('date')


def successful_submission_id(item):
    value = item.get('submission_id')
    return value if type(value) is int and value > 0 else None


def submission_success_date(item, config):
    """Use the platform submission date, falling back to first ID observation."""
    receipt = item.get('receipt') or {}
    stamp = receipt.get('date') or receipt.get('submittedAt') or receipt.get('createdAt') or item.get('accepted_at')
    if stamp:
        zone = config.get('submission_quota_timezone', 'UTC') if _platform_quota(config) else config.get('timezone', 'Asia/Shanghai')
        return datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(ZoneInfo(zone)).date().isoformat()
    return submission_quota_date(item, config)


def submission_allowance(state, config, now):
    automatic = after_optimization(config)
    scheduled = config.get('submission_policy') == 'daily_windows'
    zone = config.get('submission_quota_timezone', 'UTC') if _platform_quota(config) else config.get('timezone', 'Asia/Shanghai')
    local = now.astimezone(ZoneInfo(zone))
    day = local.date().isoformat()
    limit = min(5, int(config.get('max_daily_submissions', 2 if scheduled else 5))) if _platform_quota(config) else 1
    attempts = sum(item.get('status') in ATTEMPTED and submission_quota_date(item, config) == day
                   for item in state.get('submissions', {}).values())
    successes = len({successful_submission_id(item) for item in state.get('submissions', {}).values()
                     if successful_submission_id(item) is not None and submission_success_date(item, config) == day})
    basis = config.get('submission_quota_basis', 'attempts')
    if basis not in {'attempts', 'successful_submissions'}:
        raise ValueError('Unknown submission quota basis')
    used = successes if basis == 'successful_submissions' else attempts
    before_deadline = now < datetime.fromisoformat(config['deadline'])
    windows = submission_windows(config, now)
    active = next(((start, end) for start, end in windows if start <= now < end), None)
    next_window = next((start for start, end in windows if now < end), windows[0][0] + timedelta(days=1))
    window_id = active[0].isoformat() if active else None
    window_attempts = 0
    if scheduled and active:
        for item in state.get('submissions', {}).values():
            if item.get('status') not in ATTEMPTED:
                continue
            stamp = item.get('reserved_at') or item.get('receipt', {}).get('date') or item.get('created_at')
            in_window = stamp and active[0] <= datetime.fromisoformat(stamp.replace('Z', '+00:00')) < active[1]
            window_attempts += bool(item.get('window_id') == window_id or in_window)
    return {'policy': config.get('submission_policy', 'daily_window'), 'daily_limit': limit,
            'quota_basis': basis, 'quota_used_today': used, 'successes_today': successes,
            'attempts_today': attempts, 'remaining_today': max(0, limit - used),
            'quota_date': day, 'quota_timezone': zone,
            'window_open': before_deadline and (automatic or active is not None),
            'window_id': window_id, 'window_attempts': window_attempts,
            'next_window': None if automatic or next_window >= datetime.fromisoformat(config['deadline']) else next_window.isoformat(),
            'resets_at': datetime.combine(local.date() + timedelta(days=1), time(), local.tzinfo).isoformat()}


def submission_skip_reason(state, costs, config, now):
    allowance = submission_allowance(state, config, now)
    if allowance['remaining_today'] == 0:
        return 'daily_submission_limit_reached' if _platform_quota(config) else 'already_attempted_today'
    if config.get('submission_policy') == 'daily_windows' and allowance['window_attempts']:
        return 'already_attempted_window'
    submissions = state.get('submissions', {}).values()
    if any(item.get('status') in INFLIGHT and not item.get('submission_id') for item in submissions):
        return 'previous_submission_needs_reconciliation'
    if _platform_quota(config) and state.get('best') and any(item.get('status') in ATTEMPTED and
                                           item.get('selected') == state.get('best') for item in submissions):
        return 'already_attempted_candidate'
    if costs is None:
        return None
    previous = state.get('last_submitted_costs')
    if previous is None or math.prod(previous[t] / costs[t] for t in ('dqi', 'invsqrt', 'dfthcsos')) ** (1 / 3) <= 1 + 1e-12:
        return 'no_improvement'
    return None
