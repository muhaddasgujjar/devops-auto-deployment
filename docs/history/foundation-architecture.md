# Foundation architecture decisions

Date: 3 November 2026.

## ADR-001: integrate established delivery engines

Select Jenkins for builds, an OCI registry for images, environment Git for desired configuration, Argo CD for synchronization, and Argo Rollouts for release decisions. A custom FastAPI/PostgreSQL service will hold product metadata and observations later. It does not replace the controllers. Keep Prometheus time-series data outside the product relational database.

Rationale: the team's original two-month target is incompatible with building and hardening a new CI scheduler and Kubernetes recovery controller simultaneously. No performance or compatibility result is inferred from choosing this stack.

## ADR-002: controlled workload with explicit faults

Use a small original Python sample, not a modified upstream PaaS. It has no runtime dependencies beyond Python's standard library. Healthy, errors, latency, and unready modes are fixed at startup. Application errors deliberately leave readiness/liveness healthy, allowing later experiments to distinguish application analysis from probe checks. The production platform API is separate future work.

Native runs bind loopback by default. The container binds its interface for Kubernetes networking and runs as UID/GID 10001. Work counters exclude probes and scrapes. No user-provided URL or command is executed.

## ADR-003: validate without adopting pre-existing workloads

The Windows checkout initially contained only the assessment and extraction scratch data, with no Git commits. Inspection found a separate trusted snapshot under `/opt/release-lab/source-snapshot` and pre-existing WSL Docker/k3d state. Those are external historical artifacts; this milestone does not replace them or claim their results.

Use the existing runtime for an isolated foundation check, with unique image name `release-foundation:milestone-1` and namespace `release-foundation`. Do not change the earlier `demo-dev` resources, environment Git repository, Jenkins configuration, portal database, or secrets. Reconcile source provenance before connecting a future CI job to this checkout.

## ADR-004: one Git checkout now, separate environment Git later

Keep source, tests, runbooks, and sanitized milestone evidence in this repository. Keep secrets, generated kubeconfigs, and raw build scratch files out of Git. A later GitOps milestone creates or explicitly adopts a separate environment repository after source provenance and permissions are checked. No remote was created, no credentials were requested, and no files were committed or pushed by this milestone.
