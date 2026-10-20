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

## Next gate: CI and GitOps integration

- Prepare a dedicated trusted Linux build host and pin Jenkins LTS/plugin versions.
- Ensure the SCM branch contains this implementation before configuring its Jenkinsfile.
- Configure the separate environment repository, restricted bot credentials,
  verified SSH host keys, branch policy, and a mutually reachable TLS registry.
- Run the actual Jenkins test/scan/publish/promotion job and failure paths.
- Install Argo CD and delegate the environment directory to it; stop manual applies
  to workloads after that ownership handoff.
- Verify good and faulty releases through Git commits and reconciliation, including
  restart behavior and the distinction between desired candidate and serving stable.

## Following milestones from the assessment

1. Reproducible Ubuntu/k3s provisioning, TLS registry, least-privilege namespaces,
   staging environment, checksums/digests for infrastructure dependencies.
2. Post-promotion analysis/retention semantics and explicit failed recovery handling.
3. FastAPI + PostgreSQL migrations for projects, environments, builds, artifacts,
   releases, analysis, recovery, and audit evidence.
4. Signed callbacks, durable deduplication, server-side roles, promotion serialization,
   optimistic concurrency, restart reconciliation, bounded notification retries.
5. React onboarding, release history, and recovery evidence screens.
6. Persistent Prometheus/Grafana/Alertmanager, local notification receiver, backup/restore.
7. Repeated failure experiments and fresh-machine reproduction; publish measured
   p50/p95 timings, trial counts, false positives, availability, and resource use.

Five user interviews, team capacity confirmation, a second-user pilot, and the
supervisor's acceptance of blue/green as an extension require human participation.
Retain the rolling baseline for the original rolling-update requirement.
