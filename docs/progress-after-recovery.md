# MVP progress after post-promotion recovery

10 November 2026. Accepted local MVP scope is approximately **80%** on the existing
weighted rubric. Milestone 7 adds seven points to the recovery workstream only;
its UI, Git, permission and test work is not counted again elsewhere. This is a
scope estimate, not a percentage of elapsed work or production readiness.

| Workstream | Weight | Earned | Remaining work |
|---|---:|---:|---|
| Scope/resource/user validation | 10 | 8 | Five interviews, second-user pilot and supervisor scope acceptance |
| Unified source | 5 | 5 | One merged project and preserved histories |
| Infrastructure/workload | 15 | 9 | TLS, isolated builds and fresh-machine reproduction |
| CI/supply chain | 15 | 11 | External SCM triggers/branch policy and untrusted PR isolation |
| GitOps delivery | 15 | 11 | Broader concurrent/restart delivery verification |
| Automated recovery | 15 | 15 | Local scoped MVP accepted; broader production integration remains outside this credit |
| Observability/alerts/persistence | 10 | 7 | Persistent dashboards, notification delivery and broader platform restore |
| Product API/database/UI | 10 | 10 | Local MVP accepted; new recovery-view visual review remains follow-up |
| Evaluation/handoff | 5 | 4 | Repeated distributions and independent machine reproduction |
| **Total** | **100** | **80** | **20 weighted points remain** |

[Milestone 7](milestones/07-post-promotion-recovery.md) records actual error and
latency recoveries through environment Git, worker restart safety, inconclusive
missing telemetry, durable actors and independent serving proof. Two earlier
clock-invalid attempts are retained and excluded. The clock conflict was fixed
before the fresh trials passed. These results cover an enrolled accepted target;
automatic enrollment of future target evidence remains later integration work.

## Priorities

1. **Finish the human prerequisites.** Conduct the planned interviews, second-user
   evaluation and supervisor scope decision. Use the real portal and recovery
   evidence. No responses or approvals have been invented.
2. **Milestone 8 on this laptop:** persistent monitoring, versioned alerts, a local
   notification receiver with durable retry/deduplication, and isolated platform
   restore. Add one component at a time within the measured memory budget.
3. **Then clone to the other machine:** recreate secrets and prove a clean install,
   isolated builds and TLS before external SCM integration. Keep one project.
4. **Complete evaluation:** repeat comparable scenarios and report all attempts,
   exclusions, resource use and timing distributions. Two functional trials do
   not supply a meaningful p50/p95 benchmark.

See [the concrete delivery plan](next-delivery-plan.md) for ordered deliverables
and acceptance checks. No paid cloud service is required for the planned local
work. Repository commits remain local; no external repository was published.
