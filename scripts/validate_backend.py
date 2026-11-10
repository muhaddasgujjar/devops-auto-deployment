"""Run integration tests against a fresh actual PostgreSQL database, never SQLite."""
import json
import sys
import time
import unittest
from datetime import datetime, timezone

from scripts.render_release import ROOT


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'backend_tests'), pattern='test_*.py')
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': result.wasSuccessful(),
              'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'duration_seconds': round(time.monotonic() - started, 3),
              'scope': 'Fresh PostgreSQL migration, real evidence import, API auth/HMAC/limits, transactions, concurrency, ordering, restart and freshness',
              'failed_cases': [str(test) for test, _ in result.failures + result.errors]}
    (ROOT / 'docs/evidence/backend-tests.json').write_text(json.dumps(report, indent=2) + '\n')
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
