# Milestone 1: engineering foundation

Delivered 3 November 2026. **Engineering foundation complete. Human validation and the full Week 1 acceptance gate remain open.** The implementation is a controlled sample workload, not a finished delivery platform.

## Delivered

- Scope, explicit exclusions, architecture decisions, and acceptance criteria tied to evidence.
- Original Python HTTP sample: healthy, HTTP-error, latency, and unready modes; identity, liveness/readiness, and Prometheus metrics.
- Digest-pinned Python container base; non-root execution and a read-only filesystem.
- Two-replica rolling-update Kubernetes baseline with probes, resources, and restricted pod security.
- Native tests, reusable Docker/Kubernetes verification scripts, and a local execution runbook.
- Environment inventory, actual test receipts, and a pending interview worksheet.

## Results

| Check | Actual result | Evidence |
|---|---|---|
| Native HTTP integration suite | 8 passed, 0 failures/errors | [Native receipt](../evidence/native-validation.json) |
| Real Docker healthy/error/unready scenarios | 3 passed; non-root/read-only flags; SIGTERM exit code 0 | [Container receipt](../evidence/container-validation.json) |
| Real Kubernetes manual baseline | 2 ready replicas; health/readiness/work/version/metrics returned 200 | [Cluster receipt](../evidence/kubernetes-validation.json) |
| Test resource cleanup | Temporary containers removed and dedicated namespace removed | Verification scripts and cluster receipt |
| Host inventory | About 8 GB RAM; Docker/kubectl/k3d available inside Ubuntu WSL | [Environment](../evidence/environment.json) |

The first Kubernetes attempt hit ServiceUnavailable while WSL/cluster services resumed. Waiting for API readiness while keeping WSL active resolved it; the next full check passed. That startup failure is not suppressed as a successful initial attempt. The completed check was a healthy service smoke test, not an availability benchmark, failover test, or automated recovery trial.

A later container-verifier rerun exceeded its original approximately three-second startup allowance. The verifier now waits up to 30 seconds and includes state/log diagnostics on timeout. All three scenarios passed after that correction. Failed reruns clear old success receipts, preventing stale evidence from being presented as a current pass.

The local Docker config image ID and Kubernetes/containerd image manifest ID may differ; both observed identifiers are retained. No registry push or vulnerability-scan result is claimed. The template still uses a local imported image tag; immutable registry deployment is a later gate.

## Existing state and ownership

This Windows checkout initially held only the assessment and extraction scratch files and had no Git commits. WSL contained an older `/opt/release-lab/source-snapshot` plus existing registry, cluster, Jenkins/agent, and database artifacts. These predate this milestone. No claims are made about their current end-to-end delivery state based solely on their documentation.

The sample was tested using a unique image name and disposable `release-foundation` namespace. Earlier `demo-dev` workload definitions, Jenkins configuration, environment Git, database data, and secrets were not changed. Source continuity must be reconciled before a future pipeline uses this Windows checkout; do not replace the historical trusted snapshot automatically.

## Open gates

1. Five user interviews and second-user pilot: not conducted; see [worksheet](../user-research.md).
2. Team hours and supervisor acceptance of the proposed release strategy: not confirmed.
3. Shared lab capacity: this Windows host is constrained; choose existing university hardware or a lean serialized profile before concurrent platform services.
4. Git/source provenance: decide how this checkout and the historical Linux implementation should converge before connecting SCM/CI.

## Next technical milestone

Reconcile the source baseline with the existing Linux lab, then validate repeatable provisioning and CI/GitOps delivery against it. Preserve one release owner. Require a real source commit -> test -> build -> scan -> registry digest -> environment Git -> Argo reconciliation trace, plus a failed-test case that never changes desired deployment state. Existing historical receipts can guide setup but cannot substitute for a fresh validation run.

Do not call the entire original eight-week plan complete. The full stack, automated recovery in this checkout, product API/UI, customer validation, durable evidence storage, and production HA are outside this milestone.
