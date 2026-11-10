# MVP progress after backend hardening

10 November 2026. **Approximately 70% complete**, using the same weighted MVP
scope rubric. This estimates accepted engineering scope, not production readiness
or elapsed effort. The project remains one merged repository/product.

| Workstream | Weight | Earned | Basis and remaining limits |
|---|---:|---:|---|
| Scope/resource/user validation | 10 | 8 | Solo/laptop plan established; human validation remains |
| Unified source | 5 | 5 | Histories and committed source provenance retained |
| Infrastructure/workload | 15 | 9 | Restricted database/OS/Kubernetes identities added; TLS/isolation/reproduction remain |
| CI/supply chain | 15 | 11 | Dedicated backend test/build/scan/SBOM/publish and negative gate verified; external SCM/PR isolation remains |
| GitOps delivery | 15 | 11 | Existing healthy/fault delivery retained; broader concurrency/restart work remains |
| Automated recovery | 15 | 8 | Pre-promotion protection works; post-promotion recovery remains open |
| Observability/alerts/persistence | 10 | 7 | Durable state plus supervised read-only collection/recovery verified; alerts/full dashboards remain |
| Product API/database/UI | 10 | 7 | Database/credential/API hardening added; real-data interface remains |
| Evaluation/handoff | 5 | 4 | Actual PostgreSQL/service/CI/restore checks; broader distributions/fresh machine remain |
| **Total** | **100** | **70** | **30 weighted points remain** |

The five-point increase is infrastructure permissions (+1), backend CI (+2),
supervised collection (+1) and backend hardening (+1). No UI, post-promotion
actuator, external webhook, remote deployment or other-machine migration is counted.

Current validation: 54 passing core/demo tests and 32 passing backend/worker tests.
The dedicated backend CI also passed those 32 tests, and its separate negative
trial intentionally failed one additional test. The old demo job still has its
own immutable 36-test application snapshot. Do not combine these into a claimed
new demo test count or production availability result.

See [milestone 5](milestones/05-backend-hardening.md) and
[the operating runbook](backend-hardening.md). The scoped token is explicitly
refreshed for later sessions; supervised services are not enabled at boot.

## Next sequence on this laptop

1. Build the authenticated real-data interface for desired vs serving release,
   build/scan/SBOM history, analysis/audit evidence, and stale/unavailable states.
   Use server-side permissions and avoid embedding operator secrets in the UI.
2. Implement post-promotion detection and serialized Git-authoritative recovery,
   including failed recovery and audit proof, before exposing recovery actions.
3. Add notifications, repeated experiments and broader backup/restore/reproduction.
4. Move to the other machine later for isolated builds, TLS/staging and larger
   evaluation, as requested. External Git/branch policy and human scope validation
   remain explicit dependencies; they do not block local interface work.
