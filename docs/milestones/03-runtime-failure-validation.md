# Milestone 3: runtime rejection through CI and GitOps

Completed 10 November 2026: all six accepted cases and the final six-check health
gate passed. This is local manual pre-promotion acceptance, not production readiness.

## Accepted results

| Scenario | Jenkins build | Observed outcome | Stable HTTP 200 / samples |
|---|---:|---|---:|
| Error | 9 | Error ratio 1.0 exceeded 0.05; candidate aborted | 342 / 342 |
| Latency | 10 | P95 0.975 seconds exceeded 0.5; candidate aborted | 320 / 320 |
| Readiness | 11 | Candidate ReplicaSet timed out; both pods unready; aborted | 879 / 879 |
| Telemetry outage | 13 | Analysis Error blocked promotion; monitor restored | 421 / 421 |
| Missing traffic, repeat | 15 | Both metrics Inconclusive with empty results; promotion blocked | 488 / 488 |
| Healthy final release | 16 | Successful candidate analysis and automatic promotion | 601 / 601 |

There were **3,051 accepted stable observations, all HTTP 200**. Every fault
case retained its baseline stable selector and response revision. Each of these
six Jenkins builds ran 36 tests, passed the HIGH/CRITICAL gate with zero reported
findings at those severities, and produced an SBOM and an exact synced environment
commit. The current observer/project suite has 54 passing tests. The independent
recorder also rejected copied evidence with a mismatched scan image, wrong Git
revision or injected HTTP 500; see `docs/evidence/runtime-recorder-validation.json`.

Final serving revision:
`05d553b044d566ce06fca3205db0632fe0328c77-jenkins-16`, hash `78f7c449ff`.
Environment commit: `2d1d629be3a81bdad0c23dc809b47236313e184c`.
Image: `localhost:5001/release-demo@sha256:56c097a893ae7e05da7833afedd8c7e95242defdec4c702bf4774730ac3c75d4`.
The final check passed nodes, Rollouts, Prometheus, stable service, fresh serving
telemetry and GitOps sync. The lab was then stopped to release laptop RAM; its
volumes, accepted release, Git state and local credentials were preserved.

Portable checked evidence: `docs/evidence/runtime-failure-validation.json`.
It includes all eight attempt summaries: build 12 is explicitly excluded by the
recorder's gap check; build 14 is an additional passing healthy control before
the missing-traffic repeat. The selected matrix uses final healthy build 16.

This milestone validates the runtime safety of the merged delivery path. Every
candidate follows Jenkins tests, a blocking HIGH/CRITICAL Trivy scan, CycloneDX
SBOM generation, digest publication, environment Git commit, Argo CD sync and
Argo Rollouts. The observer requests a hard refresh of the Argo Application;
Jenkins has no cluster credentials and does not apply manifests.

The application source remains the reviewed CI snapshot
`05d553b044d566ce06fca3205db0632fe0328c77`. Its release job runs 36 tests. The newer
observer and evidence recorder are separate project changes; their tests do not
retroactively become tests in that older build snapshot. Observer commit and
content hashes are retained per trial.

## Acceptance matrix

| Candidate / injection | Required outcome |
|---|---|
| HTTP 500 with passing probes | Error-ratio analysis fails; abort; old stable retained |
| Slow HTTP with passing probes | P95 analysis exceeds 0.5 seconds; abort; old stable retained |
| Readiness failure | Progress deadline aborts; old stable retained |
| Healthy candidate without preview requests | Empty candidate metrics become Inconclusive; promotion blocked |
| Healthy candidate with Prometheus temporarily stopped | Provider error blocks promotion; original monitor restored |
| Healthy candidate with preview requests | Successful analysis and automatic promotion; desired and serving release agree |

Stable-service samples must all return HTTP 200 and a healthy response. Fault
cases must preserve the baseline response revision as well as the service's
ReplicaSet selector. Analysis evidence must belong to the current candidate,
and Argo must report the exact environment commit as Synced. Previous analyses
and stale observed generations cannot satisfy the decision gate.
An observation stream must contain at least two samples, and no forward wall-clock
inter-sample gap may exceed 10 seconds. Small backward clock corrections are
counted separately; the sequential request file retains causal order. This is an evidence-quality
guard for interrupted clients, separate from the three-second HTTP timeout and
the requirement for no non-200 observations.

Missing traffic and telemetry describe uncertainty, not a proven faulty release.
The safe behavior is to keep the existing stable version. Candidate rejection
before promotion does not implement rollback after a bad release has promoted.

## Reproduction on the current laptop

Start the full profile and let the release health gate pass before observing:

```powershell
.\scripts\lab.ps1 -Action start -Profile full
wsl -d Ubuntu-24.04 --cd "C:/Users/hasnat/OneDrive/Documents/ChatGPT/Deveops" --exec /opt/release-lab/venv/bin/python -m scripts.wait_lab --stage release --output output/runtime-preflight.json
```

Run the following in that checkout's Linux shell, with the existing reviewed
`release-merged` Jenkins job configured. Keep the CI controller and agent running
throughout all observations and run only one trial at a time:

```sh
for scenario in error latency startup no-traffic telemetry-outage healthy; do
  /opt/release-lab/venv/bin/python -m scripts.gitops_trial "$scenario" --job release-merged || exit
done
/opt/release-lab/venv/bin/python -m scripts.wait_lab --stage release --output output/runtime-final-ready.json
/opt/release-lab/venv/bin/python -m scripts.doctor --output output/runtime-final-health.json
```

The telemetry trial uses JSON Patch tests for the original Prometheus deployment
UID and replica count. A `finally` block restores its original single replica and
waits for availability, even if observation fails. It refuses to overwrite an
externally changed deployment. Stop the matrix at any failed trial and retain
that attempt before deciding whether a correction and repeat are warranted.

Each trial writes an ignored `output/gitops-SCENARIO-TIMESTAMP/` directory with
CI artifacts, scan/SBOM, controller snapshots and independent client samples.
After selecting one accepted trial for each case, export the checked evidence:

```sh
/opt/release-lab/venv/bin/python -m scripts.record_runtime_acceptance \
  --trials output/gitops-error-TIMESTAMP output/gitops-latency-TIMESTAMP \
  output/gitops-startup-TIMESTAMP output/gitops-no-traffic-TIMESTAMP \
  output/gitops-telemetry-outage-TIMESTAMP output/gitops-healthy-TIMESTAMP \
  --health output/runtime-final-health.json
```

The recorder checks artifact identities, controller outcomes, measurements and
stable samples before writing `docs/evidence/runtime-failure-validation.json`.
That portable index includes artifact hashes and attempt summaries. Raw output
is local and ignored by Git; copy it explicitly if a future evaluator needs the
complete request streams. Historical milestone 2 evidence is preserved.

The initial missing-traffic trial (build 12) produced the expected Inconclusive
analysis, but its client stream contains a 538-second interruption. Its raw
observer summary predates the sampling-gap guard and reports acceptance; the
independent recorder rejects it. Preserve that original summary and the explicit
cross-check failure rather than overwriting history. A fresh uninterrupted trial
passed as build 15 and is used for acceptance.

Small backward wall-clock adjustments are counted per trial. The repeat and final
release additionally include monotonic client timestamps and gap checks. Wall
elapsed times remain approximate; no recovery-time or latency benchmark is claimed
from these timestamps. The latency rejection value above comes from candidate
Prometheus analysis, separate from client clock corrections.

The pinned controller reports readiness timeout with reason `RolloutAborted` and
a message naming the candidate ReplicaSet that timed out. The evidence recorder
checks that message, the abort policy, and both unready candidate pods; it does
not assume the Kubernetes Deployment reason `ProgressDeadlineExceeded`.

## Limits and next work

This is a serial local acceptance experiment using the Kubernetes API proxy.
HTTP observation starts after CI completes, excludes build/scan/Git publication,
and does not measure a public ingress SLA. One accepted case per scenario is not
a failure-rate distribution or production availability guarantee.

Next, implement durable release/evidence state with FastAPI, PostgreSQL migrations,
idempotent event ingestion and reconciliation. Retain a distinction between the
desired candidate and the serving stable version. Post-promotion detection and
Git-authoritative recovery still require separate implementation and evidence.
