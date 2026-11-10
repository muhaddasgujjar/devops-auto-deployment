# MVP progress after the real-data portal

10 November 2026. Current acceptance estimate: **approximately 73%** on the existing
weighted MVP rubric. The interface contributes three points in its existing
workstream; no other workstream receives duplicate credit for its packaging or
tests. This is accepted scope, not production readiness or elapsed effort.
Final acceptance evidence is recorded in [milestone 6](milestones/06-real-data-portal.md).

| Workstream | Weight | Earned | Remaining work |
|---|---:|---:|---|
| Scope/resource/user validation | 10 | 8 | Interviews, second-user pilot and supervisor scope approval |
| Unified source | 5 | 5 | One merged product/repository; history retained |
| Infrastructure/workload | 15 | 9 | TLS, isolated builds and fresh-machine reproduction |
| CI/supply chain | 15 | 11 | External SCM triggers/branch policy and untrusted PR isolation |
| GitOps delivery | 15 | 11 | Broader concurrent/restart delivery verification |
| Automated recovery | 15 | 8 | Post-promotion detection and Git-authoritative recovery |
| Observability/alerts/persistence | 10 | 7 | Persistent dashboards, notification delivery and broader restore |
| Product API/database/UI | 10 | 10 | Local MVP views and server-side sessions; SSO/multi-tenancy outside this MVP |
| Evaluation/handoff | 5 | 4 | Repeated distributions and independent machine reproduction |
| **Total** | **100** | **73** | **27 weighted points remain** |

The original proposal and newer PRD describe this same product. Earlier versions
remain historical references. Blue/green remains an extension alongside the
rolling baseline; acceptance of that scope still requires the supervisor.

## Next milestone: recovery after promotion

Complete this on the current laptop before moving to the other machine. Keep
one running release fault scenario at a time, with CI and cluster-heavy work
serialized. Do not expose a recovery button until the actuator and its failure
paths are verified.

1. **Define the policy first.** Specify the post-promotion observation window,
   sustained error/latency thresholds, minimum request count, stable retention
   and cooldown. Missing telemetry must become inconclusive. A recovery target
   must be an earlier accepted immutable digest with sufficient retained evidence.
   Separate candidate rejection, post-promotion incident and recovery outcome.
2. **Add durable incident/recovery state.** Migrate PostgreSQL with separate
   incident ID, trigger evidence, observed/target source and image identities,
   environment version, policy version and audit actor. Define the lifecycle
   proposed → applying → verifying → recovered / failed / superseded. Preserve
   immutable source events and append-only audit rules.
3. **Build one serialized Git writer.** Use narrowly scoped environment Git
   credentials in a separate process. Re-read the current desired Git commit and
   database version before writing; abort/supersede if a newer release wins.
   Publish a forward commit referencing the accepted digest. Argo CD and Rollouts
   retain deployment ownership. Do not patch live stable selectors directly.
4. **Verify actual recovery.** Correlate the recovery Git commit, Argo sync,
   Rollout generation, serving pod hash and candidate-specific telemetry. Require
   healthy client requests before closing the incident. Record failure with
   bounded attempts if Git, registry, controller or telemetry is unavailable.
   Restart/replay must not issue duplicate recovery commits or undo newer work.
5. **Run the acceptance matrix.** Promote healthy, then introduce a controlled
   post-promotion failure. Prove error and latency detection, successful recovery,
   telemetry loss, no accepted target, writer failure, recovery timeout, restart
   replay and a competing newer release. Retain failed trials and timings. This
   extends the existing pre-promotion protection instead of counting it again.
6. **Expose recorded outcomes.** Add incident timeline and target evidence to
   the portal only after server authorization and actuator gates pass. A manual
   retry, if added, needs an explicit role, optimistic version and audit record.

Definition of done: a real failed promoted release returns to a known accepted
digest through environment Git, with independent serving/HTTP proof and an
audited durable outcome; failure/concurrency trials cannot report false success.

## Early work that still needs people or another environment

The local code, database, session and packaging prerequisites are handled in
milestones 4–6. Human validation is still open: five interviews, a second-user
pilot and supervisor scope acceptance cannot be completed by code alone. The
portal now gives those users a concrete product to evaluate. Record their
feedback and acceptance before claiming these scope points.

After recovery, prioritize notifications/persistence, repeated experiments and
platform restore. Then clone this same repository to the other machine, recreate
secrets there and verify a clean install. GPU availability is useful only if a
later model workload needs it; RAM, CPU and Linux/container support are the main
requirements for this DevOps platform. No GPU workload is required for this MVP.
