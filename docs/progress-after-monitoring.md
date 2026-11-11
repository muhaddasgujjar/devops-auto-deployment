# MVP progress after persistent monitoring

11 November 2026. Approximately **83%** of the scoped local MVP is accepted.
Milestone 8 adds three points only to observability/alerts/persistence. Its API,
UI, CI and restore work is not counted again in another workstream. This is a
weighted scope estimate, not a measure of production readiness or time remaining.

| Workstream | Weight | Earned | Remaining work |
|---|---:|---:|---|
| Scope/resource/user validation | 10 | 8 | Five interviews, second-user pilot and supervisor acceptance |
| Unified source | 5 | 5 | One merged project with both histories preserved |
| Infrastructure/workload | 15 | 9 | TLS, isolated builds and independent-machine reproduction |
| CI/supply chain | 15 | 11 | External SCM triggers/branch policy and untrusted PR isolation |
| GitOps delivery | 15 | 11 | Broader concurrent/restart delivery verification |
| Automated recovery | 15 | 15 | Scoped local MVP accepted; broader integration remains outside this credit |
| Observability/alerts/persistence | 10 | 10 | Local functional persistence, alerts, delivery and restore accepted |
| Product API/database/UI | 10 | 10 | Local MVP accepted; recovery/monitoring visual review remains open |
| Evaluation/handoff | 5 | 4 | Repeated distributions and independent-machine reproduction |
| **Total** | **100** | **83** | **17 weighted points remain** |

[Milestone 8](milestones/08-persistent-monitoring.md) records the actual passing
CI, native rule tests, monitoring fault/outage/replay trial and isolated restore.
No paid cloud service or external notification destination was introduced.

Complete the early human prerequisites first using the
[pilot and supervisor worksheet](pilot-and-scope-review.md) and
[interview plan](user-research.md). Browser visual acceptance is explicitly blocked,
not inferred from compilation or API checks. These require real observations;
no feedback or approval has been invented.

Next prepare one portable repository bundle and a fresh-machine checklist on
this laptop. No remote is configured, so there is currently no published clone
URL. Preserve private backups separately, inventory the other machine's CPU/RAM,
disk and Linux/container support, and recreate credentials there. A GPU does not
replace host RAM for this platform. Then reproduce installation and restore on
that machine before adding TLS, isolated builders and external SCM triggers.

Finally repeat comparable healthy/fault/recovery scenarios, retaining all attempts
and exclusions, before reporting timing distributions. One monitoring experiment
and the earlier functional recovery examples are not an availability benchmark.
See [the ordered delivery plan](next-delivery-plan.md).
