"""Evidence-quality checks independent of Jenkins and Kubernetes clients."""
from datetime import datetime

MAX_SAMPLE_GAP_SECONDS = 10


def stable_sample_quality(rows):
    if len(rows) < 2:
        raise ValueError('At least two stable samples are required')
    gaps = [(datetime.fromisoformat(b['timestamp']) - datetime.fromisoformat(a['timestamp'])).total_seconds()
            for a, b in zip(rows, rows[1:])]
    # File order is causal: one client issues sequential requests. Wall clocks
    # may step backwards during WSL time correction; record that independently.
    max_gap = max(0, max(gaps))
    if max_gap > MAX_SAMPLE_GAP_SECONDS:
        raise ValueError(f'Stable observation interrupted: maximum sample gap {max_gap:.3f}s exceeds {MAX_SAMPLE_GAP_SECONDS}s')
    monotonic_gap = None
    if any('client_monotonic_seconds' in row for row in rows):
        if not all('client_monotonic_seconds' in row for row in rows):
            raise ValueError('Incomplete client monotonic timestamps')
        monotonic_gaps = [b['client_monotonic_seconds'] - a['client_monotonic_seconds']
                          for a, b in zip(rows, rows[1:])]
        monotonic_gap = max(monotonic_gaps)
        if any(x < 0 for x in monotonic_gaps) or monotonic_gap > MAX_SAMPLE_GAP_SECONDS:
            raise ValueError('Client monotonic timestamps show an interrupted or unordered observation')
    return {'max_wall_sample_gap_seconds': round(max_gap, 3),
            'wall_clock_reversals': sum(x < 0 for x in gaps),
            'max_monotonic_sample_gap_seconds': round(monotonic_gap, 3) if monotonic_gap is not None else None}
