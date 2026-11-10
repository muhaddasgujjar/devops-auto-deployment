# MVP progress after runtime rejection validation

10 November 2026. **Approximately 56% complete**, using the same weighted MVP
engineering rubric as the prior 50% CI assessment. This estimates accepted scope,
not elapsed effort or production readiness. The merged histories remain one
project; earlier 20%, 33% and 50% assessments are historical checkpoints.

| Workstream | Weight | Earned points | Basis and remaining limits |
|---|---:|---:|---|
| Scope/resource/user validation | 10 | 8 | Solo/laptop scope established; interviews and supervisor acceptance remain |
| Unified source | 5 | 5 | Histories merged and reviewed application source traceable through actual CI |
| Infrastructure/workload | 15 | 8 | Lean/full lifecycle works; TLS, isolation and other-machine reproduction remain |
| CI/supply chain | 15 | 9 | Tests, scan, SBOM, digest publication and failing-test boundary proven locally; external SCM/branch policy remains |
| GitOps delivery | 15 | 11 | Healthy and faulty candidates reconcile through exact environment commits; concurrency/restart/production cases remain |
| Automated recovery | 15 | 8 | Error, latency and readiness rejection plus missing-data promotion blocks verified; post-promotion recovery remains unimplemented |
| Observability/alerts/persistence | 10 | 4 | Candidate telemetry and checked evidence work; durable ingestion, alerts and dashboards remain |
| Product API/database/UI | 10 | 0 | Still to implement; plans and existing controller dashboards do not earn product credit |
| Evaluation/handoff | 5 | 3 | Integrated fault matrix, interruption exclusion and repeat retained; distributions and independent reproduction remain |
| **Total** | **100** | **56** | **44 weighted points remain** |

The six-point increase comes from integrated failure delivery (+1), runtime
protection evidence (+4), and evaluation (+1). It does not count the excluded
interrupted trial as successful or count pre-promotion rejection as post-promotion
rollback. The finite HTTP observations are not a production uptime guarantee.

See [milestone 3 and its acceptance boundary](milestones/03-runtime-failure-validation.md)
and `docs/evidence/runtime-failure-validation.json` for actual results, provenance,
sampling-quality limits and attempt history. The current project suite has 54
passing tests; each pinned application CI snapshot runs its own 36-test suite.

## Move forward on this laptop

The next priority is [durable release and evidence state](next-milestone-durable-state.md).
Complete the early contracts and PostgreSQL migrations first, import the existing
real evidence idempotently, then implement authenticated APIs, event deduplication,
concurrency checks and read-only restart reconciliation. Require actual PostgreSQL
and backup/restore evidence before calling that milestone complete.

Follow with a minimal real-data interface, then post-promotion detection and
Git-authoritative recovery with explicit failure handling. Local notifications,
repeated evaluation and independent installation follow. Keep resource-heavy
services serialized; defer the other-machine move as requested.

Human scope/supervisor validation and external Git/branch-policy/TLS choices are
open early-stage dependencies. Local implementation can continue while those
remain explicit gaps. No user interview, external webhook, remote push or
fresh-machine reproduction is claimed by this milestone.
