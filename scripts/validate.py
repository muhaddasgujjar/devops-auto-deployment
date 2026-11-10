"""Run the unified project tests and retain a new merge-specific receipt."""
import json
import platform
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
start = time.perf_counter()
result = unittest.TextTestRunner(verbosity=2).run(suite)
report = {
    "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    "python": platform.python_version(),
    "platform": platform.system(),
    "tests_run": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skipped": len(result.skipped),
    "duration_seconds": round(time.perf_counter() - start, 3),
    "passed": result.wasSuccessful(),
    "scope": "Canonical/foundation HTTP, rendering, temporary Git publication, lifecycle, runtime-decision and observation-continuity tests; live CI/runtime evidence is recorded separately",
    "cases": [str(test) for test, _ in result.failures + result.errors],
}
destination = root / "docs/evidence/merge-validation.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
sys.exit(0 if result.wasSuccessful() else 1)
