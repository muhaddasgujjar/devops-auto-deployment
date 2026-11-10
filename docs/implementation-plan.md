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

## CI and GitOps integration: local acceptance complete

The merged source now passes local manual CI/GitOps acceptance and the integrated
runtime fault matrix. See [CI evidence](milestones/02-ci-gitops.md) and
[runtime evidence](milestones/03-runtime-failure-validation.md). The
[durable state gate](milestones/04-durable-state.md) and
[backend hardening gate](milestones/05-backend-hardening.md) also passed local
acceptance. The [real-data portal](milestones/06-real-data-portal.md) now adds
role-based sessions and evidence views. See [current priorities](progress-after-portal.md).

Remaining integration and production work:

- Prepare a dedicated trusted Linux build host and pin Jenkins LTS/plugin versions.
- Publish the reviewed implementation to the chosen external SCM branch before
  configuring its Jenkinsfile and webhook.
- Extend the existing restricted environment Git/SSH setup with external branch
  policy and a mutually reachable TLS registry.
- Exercise controller restart behavior and concurrent release delivery. Preserve
  the already verified distinction between desired candidate and serving stable.

## Following milestones in laptop-first order

The database roles, backend CI and supervised collection prerequisites are now
accepted locally. The remaining sequence is:

1. Post-promotion detection, retention, serialized Git-authoritative recovery and
   explicit failed recovery handling before exposing recovery actions in the UI.
2. Persistent Prometheus/Grafana/Alertmanager, local notification receiver, bounded
   delivery retries and broader platform backup/restore.
3. Other-machine reproduction, isolated builds, TLS registry, staging environment
   and infrastructure dependency verification.
4. Repeated failure experiments and fresh-machine reproduction; publish measured
   p50/p95 timings, trial counts, false positives, availability, and resource use.

Five user interviews, team capacity confirmation, a second-user pilot, and the
supervisor's acceptance of blue/green as an extension require human participation.
Retain the rolling baseline for the original rolling-update requirement.
