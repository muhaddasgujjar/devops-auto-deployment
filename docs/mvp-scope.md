# Milestone 1 scope and acceptance baseline

Date: 3 November 2026. This is the engineering baseline selected from the assessment; team capacity, supervisor sign-off, and customer interviews are unconfirmed.

## Target and supported contract

One trusted team, one Linux lab cluster, one Git provider (GitHub integration selected), Jenkins CI, a local OCI registry, separate environment Git, Argo CD, Argo Rollouts, and Prometheus. Develop the product API/UI only after the engines have measurable evidence. Initial workloads are stateless HTTP containers with health/readiness endpoints. Support rolling updates as the requirement baseline; progressive delivery is an explicit extension.

Use an existing WSL/Linux Docker runtime for lightweight checks on this 8 GB Windows host. Do not add the complete platform to the host concurrently. Prefer existing university hardware for the later shared lab. No new paid subscription is required by this baseline. A single local cluster is not HA.

Not in this MVP: arbitrary untrusted builds, multi-tenant SaaS, production SLAs, multi-cluster deployment, database rollback, and unattended infrastructure incident remediation. No guarantee of instant recovery or zero downtime.

## Measurable contracts

| ID | Acceptance | Evidence and boundary |
|---|---|---|
| FND-01 | Healthy sample returns 200 for work, health, and readiness, and exposes revision identity | Native HTTP tests; real container smoke check |
| FND-02 | Error revision returns work HTTP 500 while both probes pass | Demonstrates why process probes alone miss bad releases |
| FND-03 | Unready revision returns readiness 503 but liveness 200 | Readiness check; does not claim a crash-loop experiment |
| FND-04 | Latency mode adds a configured delay and exposes duration histogram | Native timing and cumulative bucket tests |
| FND-05 | Probe, scrape, and unknown-path requests do not inflate work counts | Concurrent HTTP counter test |
| FND-06 | Container runs as non-root, on a read-only root, and stops cleanly with SIGTERM | Actual Docker run and exit code |
| FND-07 | Kubernetes template has explicit resources, probes, and a rolling-update strategy | Live manual deployment when runtime permits; not automated recovery |
| CI-01 | Failed application tests never publish a desired deployment revision | Later real Jenkins failure trial |
| CD-01 | Healthy commit builds an image, publishes a digest and config commit, and reconciles through Argo CD | Later end-to-end correlation; CI must not directly mutate the owned workload |
| REC-01 | Faulty candidate is rejected using candidate-specific analysis while stable serving is observed independently | Later repeated controller trials, with traffic count and metrics freshness recorded |
| REC-02 | Missing/stale telemetry cannot automatically pass promotion | Later explicit no-data/outage trials |
| STATE-01 | Duplicate/stale events and observer restarts do not create conflicting releases | Later API/database milestone |

## Performance experiment

The sample's work endpoint is `/api/work`. Mode and revision are fixed at startup. A fault changes the candidate pod template/configuration; do not describe a mode switch as a new application source commit. For CI/source regression trials, use distinct source commits and image digests as well.

Proposed release policy for later validation: minimum 100 candidate requests in 60 seconds; candidate 5xx ratio >5% on three consecutive evaluations; 120-second readiness deadline. These are initial lab parameters, not universal production thresholds. Empty/NaN/stale samples pause the release. Measure actual detection/recovery times before setting a bound. Retain stable image and config revisions.

Record queue wait, build/test/package, image-ready to candidate-ready, observation duration, and stable-service recovery separately. The proposed 180-second warm-cache target ends at initial deployment and excludes no time silently. Publish cold-cache results separately. Compare manual recovery, rolling probes only, and metric-gated release under the same load/hardware.

## Human validation still required

Five interviews and a second-user installation pilot remain open. No customer demand, team availability, or supervisor acceptance is inferred from generated documents. Use `docs/user-research.md` to collect results. Do not send interview requests automatically.
