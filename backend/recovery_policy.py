"""Fixed lab policy. Missing, stale or incomplete telemetry never means healthy."""
import math
from datetime import datetime, timezone

POLICY = {'id': 'post-promotion-v1', 'window_seconds': 30, 'consecutive_windows': 3,
          'minimum_requests': 100, 'maximum_error_ratio': .05, 'maximum_p95_seconds': .5,
          'expected_pods': 2, 'maximum_scrape_age_seconds': 15, 'maximum_sample_age_seconds': 90,
          'monitor_seconds': 3600, 'target_retention_seconds': 604800,
          'recovery_timeout_seconds': 600, 'cooldown_seconds': 300}


def as_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value


def measured(data):
    keys = ('requests', 'errors', 'p95_seconds', 'up_min', 'up_count', 'scrape_age_seconds')
    if any(type(data.get(k)) not in (int, float) or not math.isfinite(data[k]) for k in keys):
        return False
    return (data['requests'] >= POLICY['minimum_requests'] and 0 <= data['errors'] <= data['requests'] and
            data['p95_seconds'] >= 0 and data['up_min'] == 1 and data['up_count'] == POLICY['expected_pods'] and
            0 <= data['scrape_age_seconds'] <= POLICY['maximum_scrape_age_seconds'])


def verdict(data):
    if not measured(data):
        return 'inconclusive'
    return 'breach' if (data['errors'] / data['requests'] > POLICY['maximum_error_ratio'] or
                       data['p95_seconds'] > POLICY['maximum_p95_seconds']) else 'healthy'


def sustained(rows, expected, *, now=None):
    now = now or datetime.now(timezone.utc)
    rows = sorted(rows, key=lambda r: as_time(r['window_end']))[-POLICY['consecutive_windows']:]
    if len(rows) != POLICY['consecutive_windows']:
        return False
    ends = [as_time(r['window_end']) for r in rows]
    return (0 <= (now - ends[-1]).total_seconds() <= POLICY['maximum_sample_age_seconds'] and
            all((b - a).total_seconds() == POLICY['window_seconds'] for a, b in zip(ends, ends[1:])) and
            all(r['quality'] == 'measured' and verdict(r['data']) == expected for r in rows))
