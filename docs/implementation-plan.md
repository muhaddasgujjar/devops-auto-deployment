# Implementation backlog

## Delivered foundation

- Sample service: healthy, error, latency, and readiness faults; probes and metrics.
- Real HTTP tests including concurrent accounting and independent evidence capture.
- Non-root Dockerfile, constrained digest-only manifest renderer.
- Jenkins test/build/scan/push/GitOps pipeline template with serialized executions.
- Rolling-update baseline in a separate namespace.
- Blue/green templates, minimum traffic checks, candidate-specific error/latency analysis.
- Lean local bootstrap, scoped monitoring discovery, restricted Argo application template.

## Live lab gate

- Installed Ubuntu/WSL, Docker Engine, k3d, kubectl, Trivy, and a Linux venv.
- Installed k3s, Rollouts, and Prometheus; verified registry pulls and revision labels.
- Ran healthy promotion, HTTP-error rejection, latency rejection, missing traffic,
  telemetry outage, and a separate probes-only rolling-update comparison.
- Captured raw analysis, service selectors, source hashes, image digests, scans,
  SBOMs, and independent client observations.
- Replaced the vulnerable runtime with a digest-pinned minimal runtime that passes
  the high/critical scan gate without exclusions.
- Found a readiness deadline issue with retained ReplicaSets; the native-history
  cleanup workaround and its retest are documented in live validation.

See [the validation report](live-validation.md) for actual results and failed pilot
runs. These checks are a local experiment; repeated benchmark conditions and
formal availability/recovery distributions are still pending.

## Local CI and GitOps integration

The local implementation now supplies a bounded Jenkins controller and separate
trusted agent, a dedicated SSH environment repository with read/write keys, and
Argo CD Core reconciliation. Plugin versions/checksums, source polling, controlled
ownership handoff and GitOps trial evidence capture are implemented. See
[the integration runbook and acceptance record](ci-gitops.md).

Jenkins snapshot build 5 passed tests/scan/publish; Argo CD reconciled its separate
environment commit. After an interrupted observer caused inconclusive analysis,
explicit abort/retry recovery passed fresh analysis and promoted with 734 stable
observations and zero failures. This is local snapshot acceptance, not yet a
GitHub-polling or uninterrupted delivery acceptance run.

The subsequent `release-main` gate passed: build 1 was started by scheduled SCM
polling of GitHub main, passed tests/scan/publication and promoted automatically
with 2,845 stable observations and zero failures. Controlled error build 2 was
rejected by analysis with 754 stable observations and zero failures. See
[the GitHub-source acceptance record](scm-validation.md) for exact commits,
artifacts, causes and the remaining fault matrix.

## Completed local milestone: durable monitoring and evidence

Retained Prometheus PVCs, an immutable SQLite/SHA-256 evidence store, automatic
trial archival, and isolated backup/restore verification are implemented. See
[the persistence runbook](persistence.md) for live acceptance and storage scope.
The store is an operations CLI; it does not replace the planned PostgreSQL/API.

## Post-promotion monitoring and recovery

Serving-only post analysis, 600-second retention, a Git-backed release lease and
bounded recovery observer are implemented. Corrected healthy build 5 completed
both windows with 1,903 successful serving observations. Serving-fault build 6
passed preview but failed after promotion; automatic traffic and desired-state
recovery passed, with 278 expected candidate 500s over a 63.658-second observed
error window. See [the recovery acceptance record](post-promotion.md).
The separate denied-write fixture also passed: native rollback worked with the
Git observer paused, a denied restoration push remained failed across restart,
and explicit retry attempt 2 verified desired and serving state. New publication
is blocked throughout analysis/recovery; the legacy snapshot publisher is disabled.

## Next acceptance gates

1. Complete Jenkins-driven latency/readiness/missing-traffic/telemetry-outage
   acceptance and rebuild controller/agent from the complete locks. The earlier
   engine-only tests do not substitute for this GitOps matrix.
2. Build the FastAPI/PostgreSQL release model, migrations and durable event/audit
   processing, then roles, signed callbacks, idempotency and restart reconciliation.
3. Add React onboarding, release history and recovery evidence views.
4. Provision a separate Linux build host, TLS registry, staging environment,
   infrastructure digest locks, independent backups, Grafana/Alertmanager and
   notification delivery. These remain team deployment requirements.
5. Repeat fault experiments and reproduce on a fresh machine; report measured
   recovery distributions and resource use.

Five user interviews, team capacity confirmation, a second-user pilot, and the
supervisor's acceptance of blue/green as an extension require human participation.
Retain the rolling baseline for the original rolling-update requirement.
