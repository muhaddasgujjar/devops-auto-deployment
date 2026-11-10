"""Run integration tests against a fresh actual PostgreSQL database, never SQLite."""
import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone

from scripts.render_release import ROOT


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'backend_tests'), pattern='test_*.py')
    if os.environ.get('RELEASE_NEGATIVE_TEST') == 'true':
        def intentional_failure():
            unittest.TestCase().fail('Intentional backend CI test gate')
        suite.addTest(unittest.FunctionTestCase(intentional_failure))
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': result.wasSuccessful(),
              'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'duration_seconds': round(time.monotonic() - started, 3),
              'scope': 'Fresh PostgreSQL migration, API/session/HMAC/permissions, evidence, recovery policy/ledger, temporary Git CAS/replay, signal/worker bounds and observation ordering',
              'failed_cases': [str(test) for test, _ in result.failures + result.errors]}
    destination = os.environ.get('RELEASE_TEST_REPORT', str(ROOT / 'docs/evidence/backend-tests.json'))
    from pathlib import Path
    Path(destination).write_text(json.dumps(report, indent=2) + '\n')
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
