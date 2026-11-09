# Running review and gaps — 20 October 2026

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
| 1 | Jenkins and Argo CD are templates, not a connected delivery pipeline | Trusted Linux build host, separate environment Git repository and restricted credentials, TLS registry; a commit builds/scans/pushes and reconciles automatically |
| 2 | Evidence and telemetry are local and ephemeral | Durable release/evidence storage, persistent metrics, backup and restart recovery checks |
| 3 | Native-history workaround limits retained rollback history | Retest controller upgrade or upstream fix; post-promotion checks and an explicit recovery failure path |
| 4 | Custom API, database, portal, roles, callbacks and notifications are pending | Backend data model and authenticated release lifecycle after the engines are integrated |
| 5 | Current runs are finite local checks | Repeated fault trials, concurrency controls, fresh-machine reproduction and measured distributions |

The current 8 GiB Windows host is constrained. The review adds a CLI dashboard and
forwarding processes; it does not add Jenkins, PostgreSQL, or a full monitoring
stack. The next integration milestone needs the intended build host and repository
details. This running lab is suitable for demonstrating candidate analysis and
promotion; it does not yet demonstrate end-to-end GitOps or a finished product UI.
