# Milestone 7: recovery after promotion

Status: local functional acceptance passed on 10 November 2026. The weighted MVP
estimate is approximately **80%**; see [progress](../progress-after-recovery.md).

This milestone handles a release that passed candidate analysis and then became
unhealthy while serving users. A separate restricted worker detects sustained
errors or latency, selects an earlier accepted immutable image and publishes a
forward environment Git commit. Argo CD and Argo Rollouts reconcile that commit.
The worker cannot patch deployments, services or Rollouts.

The fixed policy requires three consecutive 30-second windows, at least 100
requests per window, two observed serving pods, fresh scrapes and either more
than 5% errors or P95 latency above 500 ms. Missing data is inconclusive. Closing
an incident requires the promoted target, coherent Git/controller/image identity,
three healthy windows and at least 100 matching successful verification requests.
The deadline is ten minutes; incidents remain failed after failure.

## Implementation and prerequisites

- Populated PostgreSQL migration rehearsal preserved existing records and IDs;
  the real database was upgraded only after that rehearsal passed.
- Incident, health-window and phase-event records have separate durable IDs,
  optimistic versions and restricted SQL grants. Restoring an old build creates
  a new deployment without rewriting its original acceptance record.
- The recovery process has its own API role, OS user, Kubernetes identity and
  repository-scoped SSH key. It receives no database, admin or HMAC credential.
- Git publication checks the expected parent, preserves unrelated configuration,
  records one incident marker and refuses to overwrite a concurrent publisher.
- Restart and uncertain publication reconcile retained events and the Git marker.
  The portal exposes incident history and evidence through read-only views.
- The demo has an opt-in ephemeral fault file for the separate root test injector.
  Ordinary HTTP clients cannot activate a fault.

See [the recovery runbook](../recovery.md) for the policy, credentials, migration,
service operation, trial commands and shutdown procedure.

## Retained failures

The first live error trial used origin build 18. The controller restored accepted
build 16, but the host wall clock jumped approximately 74 minutes during
verification. The durable incident correctly ended `failed/verification_timeout`;
that trial is excluded from successful functional acceptance and timing results.
Its raw directory is `output/recovery-error-20261110T124956Z`.

That investigation also exposed a reporting issue: a failed incident could block
later truthful observations of its already-published target. The API now records
the actual serving target while preserving the incident's terminal failure.
The worker additionally checks wall versus monotonic clock drift before Git
publication, and trial acceptance independently rejects clock discontinuities.

The next attempt, origin build 19, reached a genuinely recovered ledger state but
its client stream still had clock corrections. The independent observer rejected
the experiment. It remains excluded at `output/recovery-error-20261110T150929Z`.
Ubuntu's active NTP service conflicted with WSL host synchronization. The service
was stopped and disabled following Canonical's guidance, then a fresh clock
capture and both complete passing streams verified consistency. See the runbook
for the reversible change and [clock evidence](../evidence/recovery-clock-stability.json).

Backend build 9 blocked publication after an unexpected verification-test failure
alongside the intentional negative-gate failure. The complete 74-test host suite
and 16 repetitions of the affected test passed. This attempt is retained in
`output/backend-ci-trial-20261110T142946Z` and is not the accepted negative gate.

## Accepted results

Backend job 10 produced exactly the intentional failed test and blocked later
publication. Job 11 passed all **74** PostgreSQL/API/session/recovery/Git tests,
published its verified non-root runtime and reported zero HIGH/CRITICAL OS/Python
findings and zero HIGH/CRITICAL frontend findings. Both use reviewed source
`1718c24d32bdb922f0a1624b934dd3cb2d88db14`. The core/demo suite has **56** passing
tests; the frontend's **5** tests and build passed. Pinned schemas validated 32
resource documents. The installed portal and CI contain identical compiled assets.

| Scenario | Origin → target build | Detection | Fault → verified | Independent stable requests | Result |
|---|---|---:|---:|---:|---|
| Serving HTTP errors, telemetry gap and writer restart | 20 → 16 | 216.201 s | 577.203 s | 40,907 | Recovered |
| Serving latency above 500 ms | 21 → 16 | 94.852 s | 391.109 s | 20,304 | Recovered |

The error experiment includes a 123.959-second telemetry permission outage:
three unavailable windows produced zero incidents. A deliberate SIGKILL during
verification changed the writer PID, and there was exactly one recovery Git
commit. The latency experiment observed slow HTTP 200 responses rather than
classifying latency as HTTP failure. Both final client streams ended with 100
matching target HTTP 200 responses; the worker separately recorded 173 verified
matching requests for each incident. Original deployment acceptance was preserved.
All phase transitions joined to the dedicated recovery API actor in PostgreSQL.

Both recoveries restored the enrolled immutable image
`localhost:5001/release-demo@sha256:56c097a893ae7e05da7833afedd8c7e95242defdec4c702bf4774730ac3c75d4`.
The independent recorder checked raw artifact/source hashes, registry manifest
bytes, Git parentage, one incident marker, controller/image/serving identity,
actual fault samples, healthy traffic and durable phase actors. Their complete
wall/monotonic clock-offset spans were 0.048956 s and 0.010858 s, respectively.
These are two functional trials, not timing distributions or availability claims.

No-target, Git-unavailable, timeout, newer-release supersession, stale callbacks,
permission denial, competing Git publishers and uncertain publication replay were
tested separately against real disposable PostgreSQL databases and temporary Git
repositories. They are not represented as extra live Kubernetes fault trials.

## Evidence and limits

- [Independent recovery receipt](../evidence/recovery-acceptance.json): passing
  trials and the two retained failed/excluded attempts.
- [Backend CI](../evidence/backend-ci-acceptance.json) and
  [backend tests](../evidence/backend-tests.json): final source, gates and counts.
- [Migration](../evidence/recovery-migration.json),
  [target enrollment](../evidence/recovery-target-acceptance.json) and
  [actual permissions](../evidence/recovery-permissions.json): prerequisite proof.
- [Installed portal](../evidence/portal-service-acceptance.json) and
  [compiled bundle](../evidence/recovery-portal-build.json): authentication and
  packaged asset agreement. A new browser visual review of the extension remains open.
- [Closeout](../evidence/recovery-closeout.json): stopped owned services/containers,
  retained data/backup and matching installed/CI sources.

This is a manually started, local single-environment MVP. Targets are explicitly
enrolled from curated acceptance evidence; new successful CI builds are not
automatically enrolled. One-hour Kubernetes tokens require explicit refresh.
External SCM/PR isolation, TLS/remote operation, persistent monitoring,
notifications, repeated benchmarks and independent machine reproduction remain
open. See [the next delivery plan](../next-delivery-plan.md).
