# MVP progress after durable state acceptance

Historical checkpoint; [the current hardening assessment](progress-after-hardening.md)
supersedes this score without creating a separate project.

10 November 2026. **Approximately 65% complete** under the same weighted MVP
engineering rubric. This estimates accepted scope, not production readiness,
elapsed effort or test pass rates. Both historical implementations remain one
merged project.

| Workstream | Weight | Earned | Basis and remaining limits |
|---|---:|---:|---|
| Scope/resource/user validation | 10 | 8 | Solo/laptop plan established; human validation remains |
| Unified source | 5 | 5 | Histories and reviewed source provenance retained |
| Infrastructure/workload | 15 | 8 | Local lifecycle works; isolation/TLS/other-machine reproduction remain |
| CI/supply chain | 15 | 9 | Demo pipeline proven; backend pipeline/external SCM remain |
| GitOps delivery | 15 | 11 | Healthy/fault delivery proven; broader concurrency/restart work remains |
| Automated recovery | 15 | 8 | Pre-promotion safeguards verified; post-promotion recovery open |
| Observability/alerts/persistence | 10 | 6 | Durable evidence/audit and read-only restart reconciliation work; alerts/full dashboards remain |
| Product API/database/UI | 10 | 6 | Authenticated API, PostgreSQL migrations/import/restore verified; UI and hardening remain |
| Evaluation/handoff | 5 | 4 | PostgreSQL concurrency, missed release and restore checked; broader distributions/fresh machine remain |
| **Total** | **100** | **65** | **35 weighted points remain** |

The nine-point increase is backend (+6), durable evidence/state (+2), and
evaluation (+1). No credit is awarded to a UI, backend CI, automatic external
callbacks, post-promotion recovery, production security or the other-machine move.
See [milestone 4](milestones/04-durable-state.md) and its committed receipts. The
project has 54 passing core/demo tests and 20 passing backend/PostgreSQL tests;
Jenkins's pinned application snapshot retains its separate 36-test suite.

## Move forward, earliest gaps first

1. Split PostgreSQL runtime/migration roles and test actual permissions. Add
   backend packaging, tests and dependency/image scanning in a dedicated CI path.
   Supervise read-only collection with bounded retries and explicit stale-state
   reporting. Keep CI-publication and controller-observation credentials distinct
   if adding producer hooks.
2. Build the real-data interface: desired vs serving state, release history,
   scan/SBOM references, analysis/audit evidence and stale/unavailable indicators.
   Authenticate using server-side roles and preserve controller ownership.
3. Add post-promotion detection and Git-authoritative recovery, with concurrency,
   failed recovery and audit proof, before exposing a recovery action.
4. Add notifications, repeated benchmarks, broader backups and independent
   reproduction. Move to the other machine after laptop work as requested.

Human interviews/supervisor acceptance, external repository/branch policy and TLS
choices remain explicit dependencies, without blocking reversible local work.
