# MVP progress after CI/GitOps acceptance

10 November 2026. **Approximately 50% complete** by the existing weighted engineering rubric. This is a planning estimate for the MVP, not production readiness or a measurement of elapsed effort. The prior 33% score is retained as the dated pre-integration assessment.

| Workstream | Weight | Earned points | Basis and limits |
|---|---:|---:|---|
| Scope/resource/user validation | 10 | 8 | Scope and solo availability established; interviews/supervisor validation open |
| Unified source | 5 | 5 | Histories preserved; committed-source CI provenance demonstrated |
| Infrastructure/workload | 15 | 8 | Lean lifecycle and running workload verified; other-machine/TLS/reproduction work remains |
| CI/supply chain | 15 | 9 | Real tests, scan, SBOM, push and failed-test boundary proven; external SCM/branch policy still pending |
| GitOps delivery | 15 | 10 | Environment commit reconciled and healthy promotion verified; broader failure/concurrency/restart trials remain |
| Automated recovery | 15 | 4 | Integrated healthy analysis works; fresh fault/recovery cases and post-promotion handling remain |
| Observability/alerts/persistence | 10 | 4 | Serving revision telemetry and raw evidence work; durable ingestion, alerting and complete dashboards remain |
| Product API/database/UI | 10 | 0 | Not implemented in the merged source |
| Evaluation/handoff | 5 | 2 | Comparative failure evidence and one clean repeat retained; repeated distributions and independent reproduction remain |
| **Total** | **100** | **50** | **Approximately half remains** |

Acceptance references: `docs/evidence/ci-gitops-acceptance.json`, `docs/evidence/ci-negative-gate.json`, `docs/evidence/ci-attempt-history.json`, and `docs/milestones/02-ci-gitops.md`.

Next sequence on this laptop: fresh runtime rejection/recovery scenarios; durable FastAPI/PostgreSQL evidence and release state with deduplication/reconciliation; minimal real-data interface and roles; backup/restore and notifications. Serialize resource-heavy work. Clone onto the other machine later for larger infrastructure, isolated builds and broader evaluation.

No credit is awarded for a GPU, a database container alone, planned UI screens, or merely having a template. One clean trial does not erase previous failures or prove zero downtime.
