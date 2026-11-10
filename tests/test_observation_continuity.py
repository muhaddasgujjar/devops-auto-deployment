"""Do not count an interrupted client stream as a clean runtime observation."""
import unittest

from scripts.observation import stable_sample_quality


def samples(*timestamps):
    return [{'status': 200, 'timestamp': '2026-11-10T' + stamp + '+00:00'} for stamp in timestamps]


class ObservationContinuityTests(unittest.TestCase):
    def test_regular_client_samples_are_accepted(self):
        self.assertEqual(stable_sample_quality(samples('06:00:00.000', '06:00:00.220')),
                         {'max_wall_sample_gap_seconds': 0.22, 'wall_clock_reversals': 0,
                          'max_monotonic_sample_gap_seconds': None})

    def test_green_responses_do_not_hide_a_host_interruption(self):
        with self.assertRaisesRegex(ValueError, '538.000s'):
            stable_sample_quality(samples('06:00:00.000', '06:08:58.000'))

    def test_clock_correction_is_reported_separately_from_gaps(self):
        self.assertEqual(stable_sample_quality(samples('06:00:01.000', '06:00:00.000')),
                         {'max_wall_sample_gap_seconds': 0, 'wall_clock_reversals': 1,
                          'max_monotonic_sample_gap_seconds': None})

    def test_single_response_is_not_an_observation_stream(self):
        with self.assertRaises(ValueError):
            stable_sample_quality(samples('06:00:00.000'))

    def test_monotonic_timestamps_detect_gap_hidden_by_wall_clock_correction(self):
        rows = samples('06:00:00.000', '06:00:00.220')
        rows[0]['client_monotonic_seconds'], rows[1]['client_monotonic_seconds'] = 1, 539
        with self.assertRaisesRegex(ValueError, 'monotonic'):
            stable_sample_quality(rows)

    def test_monotonic_gaps_are_independent_of_backward_wall_clock_steps(self):
        rows = samples('06:00:01.000', '06:00:00.000')
        rows[0]['client_monotonic_seconds'], rows[1]['client_monotonic_seconds'] = 1, 1.25
        quality = stable_sample_quality(rows)
        self.assertEqual(quality['max_monotonic_sample_gap_seconds'], 0.25)
        self.assertEqual(quality['wall_clock_reversals'], 1)
