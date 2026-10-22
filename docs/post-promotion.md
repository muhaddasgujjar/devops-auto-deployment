# Post-promotion monitoring and recovery

The local release policy now has a second, revision-specific analysis after
Rollouts switches the active Service. It checks serving error ratio and p95
latency, requires 100 serving requests per minute, exactly two healthy targets,
and scrape samples no older than 15 seconds. Five measurements run 15 seconds
apart after a 60-second warmup. Preview traffic is excluded from serving metrics.
Empty/NaN serving results fail the post gate; query transport errors reach the
configured error limit. Missing evidence never certifies the release.

The old revision is retained for 600 seconds. This exceeds the normal 120-second
post-analysis window. `scaleDownDelayRevisionLimit` is omitted because the native
controller rejects a positive limit with the history-limit-zero workaround.
An explicitly configured scale-down delay can cancel a running post-analysis,
so the reconciler also requires all five successful measurements for both metrics.
Native [Rollouts blue/green behavior](https://argoproj.github.io/argo-rollouts/features/bluegreen/)
returns traffic to the previous stable ReplicaSet when post-analysis fails/errors.

## Desired-state recovery and release serialization

Native traffic rollback is only the first step. The environment repository's
root `release-control.json` is a durable release lease, outside Argo's manifest
directory. Publishers atomically commit it with the candidate manifests and use
normal non-force pushes. A second publisher cannot replace a deploying,
recovering or failed release. Concurrent clones race at the Git push; only a
fast-forward writer wins. The frozen legacy `release-local` job is disabled
because its older publisher does not implement this lease.

The bounded WSL systemd observer reads that lease and the actual Rollout,
AnalysisRuns, Service, Argo Application, serving response and Prometheus targets.
It runs under a 192 MiB memory/25% CPU limit without a new database service.
It holds the restricted environment Git write key; Jenkins still has no
Kubernetes credential. This local observer currently uses the lab administrator
kubeconfig and fixed namespace/application paths; a dedicated namespace-scoped
service account is required before a shared deployment.

When a release aborts, the observer archives failing resources, restores the
previous verified environment manifests with a new Git commit and waits for
Argo CD. It declares `recovered` only when desired and serving revision/image
match the target, Argo is Synced, Rollouts is Healthy, the response is healthy,
and both telemetry targets are fresh on three consecutive observations.
Recovery has a fixed ten-minute deadline; restarting the observer does not reset
it. New releases remain blocked until verification completes.

Git write denial or a recovery timeout becomes `recovery_failed`, with evidence
and an explicit operator retry. A failed Git write is also saved in an atomic
local status file; it stays blocked across restarts even when the Git lease
cannot be updated. The observer never force-pushes, edits service selectors,
repeatedly resets deadlines, or claims that traffic rollback alone is recovery.

## Commands

From the project root in PowerShell:

```powershell
.\scripts\lab.ps1 -Action recovery-setup
.\scripts\lab.ps1 -Action recovery-status
.\scripts\lab.ps1 -Action gitops-trial -Scenario healthy
.\scripts\lab.ps1 -Action gitops-trial -Scenario post-error
.\scripts\lab.ps1 -Action recovery-failure-check
```

`post-error` is a controlled application fixture: preview requests carry
`X-Release-Preview: true` and pass; ordinary serving requests fail after traffic
switches. Probes remain healthy. It models a serving-only regression, not an
unplanned production incident. Preview clients must set this header to keep
their synthetic load out of the serving metrics. Ordinary browser traffic is
counted as serving traffic.

Unlike a pre-promotion rejection, this experiment must record some real serving
HTTP 500s before detection and rollback. Its expected verdict is
`post-promotion-recovered-through-gitops`, with failed requests attributed only
to the bad candidate, followed by the previous healthy revision serving again.
Do not call it zero-downtime recovery.

`recovery-failure-check` is a separate fault experiment. It pauses only the local
recovery observer, submits another serving-only fault, confirms native traffic
rollback, and attempts the Git restoration with the read-only key. It requires
an explicit failed state, persistence across restart without a hidden retry,
and then a new successful attempt using the write key. The ordinary observer
must report that denied-write trial as failed; the enclosing failure-check
report records whether the expected failure and operator retry were verified.

After fixing the reported cause of a failed recovery:

```powershell
.\scripts\lab.ps1 -Action recovery-retry
.\scripts\lab.ps1 -Action recovery-status
```

Retry creates a new attempt and bounded deadline. If recovery is not failed, the
command refuses to override an active release. `start`/`stop` manage the observer
with the lab; restarting its systemd service preserves the Git intent and local
failure block. `status` checks observer freshness and reports failed recovery.

Final trial and recovery evidence is archived by SHA-256 in the independent
evidence store. Git intents and `/var/lib/release-lab/recovery/status.json` are
durable local state, not off-machine backups. The post-promotion gate is a finite
window; it does not provide indefinite SLO monitoring or recover from loss of the
only cluster/host. First-ever deployment without a previous good revision still
requires independent baseline verification.

This one-application profile sets Argo CD reconciliation to 30 seconds with no
jitter, including Git revision cache expiry. Both Argo components are restarted
when that setting changes, as required by the [pinned configuration documentation](https://github.com/argoproj/argo-cd/blob/v3.5.5/docs/operator-manual/argocd-cm.yaml).
This reduces desired-state recovery delay without using per-release manual refresh.

## Validation notes

The first live policy pilot exposed a controller semantic constraint absent from
the upstream structural schema: a scale-down revision limit of 1 is invalid with
history limit 0. The field was removed, and validation now checks that relation
and retention duration. The pilot is retained as failed; the observer restored
the previous known-good Git manifests and verified three healthy observations.
Subsequent healthy/post-error acceptance results are recorded separately.

On 23 October 2026 (local time), corrected healthy build 5 passed both complete
analysis windows, followed by verified Git acknowledgement. All 1,903 stable
observations returned HTTP 200. Its source was
`f73e1b5420ce99970d41e0c555a92456d9a6d07b`; evidence is
`output/gitops-healthy-20261022T193915Z` (UTC timestamp).

Serving-fault build 6 passed preview, switched active traffic, failed post
analysis, and returned traffic to build 5 automatically. The independent client
recorded 1,548 requests, including 278 injected candidate 500s, with an observed
error window of 63.658 seconds. The observer restored the known-good manifests
in Git, verified healthy responses and telemetry three times, and Argo CD
reported the final acknowledgement Synced. No operator recovery or manual
promotion was used. Evidence: `output/gitops-post-error-20261022T194720Z`.

Bad deployment commit: `ffc9101e4985af63fc2ab9d58777007c393e4065`.
Verified recovery acknowledgement: `a0c02ebf3aef180a458d6d5e656dd84770088b41`.
The archived recovery resource snapshot preserves the failed PostPromotion run
before subsequent native history cleanup.

The actual Git transport refused a second publisher during the active release
without changing HEAD (`output/release-lease-check.json`). A separate sample
shows the lease still deploying while active traffic had moved and post analysis
was Running (`output/post-promotion-lease-check.json`). Unit/integration tests
also cover denied pushes, timeout failure, immutable failed status across
process restart, and independent environment edits during an active lease.

The live denied-write fixture also passed:
`output/recovery-write-check-20261022T195406Z` records
`denied-write-restart-and-retry-verified`. Build 7 passed preview, failed post
analysis and rolled traffic back while the Git observer was stopped. The read
key's restoration push was denied, the failed state and unchanged Git HEAD
survived observer restart, and explicit retry attempt 2 restored desired state.
The final recovery acknowledgement was
`39396e645b65e4afb22f6f6b7dca78f79302f07f`, verified Synced and Healthy with
three fresh observations. Its ordinary fault trial remains `trial-failed` as
expected (`output/gitops-post-error-20261022T195407Z`): 1,100 observations,
including 271 injected candidate 500s and no unrelated failure responses.

All 28 unit/HTTP/Git integration tests passed on Windows and Linux; all 21
resource/config documents passed pinned schema and local policy validation.
These are finite local trials; they do not establish recovery percentiles,
production HA or a false-positive rate.
