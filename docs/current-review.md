# Running review and gaps — updated 23 October 2026

Post-promotion monitoring and Git desired-state recovery now pass live checks.
Healthy build 5 passed both windows with all 1,903 requests successful. Serving
fault build 6 triggered automatic recovery after 278 injected 500s over a
63.658-second observed error window. A separate denied-write fixture verified
native rollback, a persistent failed recovery across restart, and successful
explicit retry attempt 2. See [recovery acceptance](post-promotion.md). The
current suite has 28 tests and 21 validated resource/config documents.

The current lab includes authenticated Jenkins, its separate trusted local
agent, a dedicated SSH environment Git repository and Argo CD Core. Snapshot
build 5 published a scanned artifact and environment commit; fresh analysis
promoted it after recovery from an interrupted observer, with 734 stable requests
and zero failures. This required operator abort/retry and does not yet prove an
uninterrupted GitHub polling delivery by itself. The later scheduled GitHub-source
build did promote automatically with 2,845 stable requests and zero failures;
controlled HTTP-error build 2 was rejected with all 754 stable requests successful.
See [SCM acceptance](scm-validation.md) and [CI setup](ci-gitops.md).

Prometheus now has retained storage; historical samples survived pod replacement
and an independent TSDB restore. The persistence milestone's 20-run evidence
backup/restore verified 278 file references; subsequent CI runs are also archived.
All 20 tests passed on Windows and
Linux; all 20 manifests/config documents passed schema checks. See
[persistence acceptance](persistence.md). The earlier review below remains the
record of the 20 October engine trials.

The existing Kubernetes lab is running for inspection. These interfaces show real
local workloads; the application itself is the small JSON demonstration service.

| View | Address | What to inspect |
|---|---|---|
| Sample application | http://localhost:8081/ | Healthy mode and the serving release revision |
| Argo Rollouts | http://localhost:3100/rollouts/ | `demo-dev` → `release-demo`, stable/candidate revisions and AnalysisRuns |
| Prometheus | http://localhost:9090/ | `up{job="demo-pods",namespace="demo-dev"}`; inspect revision labels |

From PowerShell, use `scripts/lab.ps1 -Action start`, then `-Action review`.
Use `-Action status` for the health report and `-Action stop` when finished.
Stopping preserves the lab. The browser forwards are supervised and reconnect to
the serving revision after promotion. Their short reconnect gap is not used as a
measurement of service availability. The native dashboard has local lab admin controls.

## Gaps fixed during this review

- Added browser access to the application, native Rollouts UI, and Prometheus.
  The pinned Rollouts CLI download is checked against its recorded SHA-256.
- Replaced the status command that could mask Kubernetes failures with checks of
  controllers, node pressure, live application behavior, and serving telemetry.
- Strengthened both candidate metrics: require exactly two discovered scrape
  targets and samples no older than 15 seconds. Previously, `min(up) == 1` could
  pass when a missing target disappeared from discovery. The expected target count
  matches this lab's two replicas; changing replica counts requires updating that
  analysis argument. Autoscaling is not implemented.

Live Prometheus expression checks are recorded in
`output/telemetry-guard-checks.json`. They use actual healthy samples, select one
of the two targets to reproduce the discovery blind spot, and evaluate one-minute
old samples to verify freshness rejection. They do not claim a real pod-loss trial.
The existing 12 tests and 18 pinned-schema validations pass. Fresh promotion
evidence is recorded separately from the earlier six-scenario experiments in
[live validation](live-validation.md).

The new healthy trial `output/trial-healthy-20261020T120742Z` promoted from
`56769885d9` to `64d7f7cb56` in approximately 150 seconds from trial start.
All 611 independent stable-service observations returned HTTP 200. The scanned
artifact has zero reported HIGH/CRITICAL findings and its SBOM is retained.
The application browser forward followed the new revision automatically;
closing and reopening all three interfaces also passed Windows HTTP checks.
These observations are one healthy trial under the stronger policy, not a rerun
of the entire fault suite. `output/current-health.json` records healthy controllers,
the serving response and both fresh targets. The lab and interfaces remain running
for this review.

## Remaining work, in priority order

| Priority | Gap | Next acceptance evidence |
|---|---|---|
| 1 | Scheduled GitHub delivery and HTTP-error rejection passed | Remaining Jenkins fault matrix, rebuild from locks and full-lifetime release serialization |
| 2 | Telemetry and evidence persist locally; backups remain on one machine | Independent-host storage and coverage for Git, Jenkins, registry, secrets and control plane |
| 3 | Native-history workaround limits retained rollback history | Retest controller upgrade or upstream fix; post-analysis, durable recovery and denied-write retry are now verified locally |
| 4 | Custom API, database, portal, roles, callbacks and notifications are pending | Backend data model and authenticated release lifecycle after the engines are integrated |
| 5 | Current runs are finite local checks | Repeated fault trials, concurrency controls, fresh-machine reproduction and measured distributions |

The current 8 GiB Windows host is constrained. Jenkins and Argo CD use bounded
local profiles; PostgreSQL and a full monitoring stack remain pending. The next
work is the remaining fault matrix and the product backend.
A separate build host and
TLS registry remain requirements for a team installation. The current browser
dashboard is the native Rollouts interface; the product portal is still pending.
