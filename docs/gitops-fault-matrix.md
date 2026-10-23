# Jenkins/GitOps fault acceptance

Run from the existing workspace with the lab Healthy, recovery idle, and Jenkins
idle. The matrix builds through `release-main`, publishes digest-pinned artifacts
to environment Git, and observes Argo CD/Rollouts and the durable recovery worker.
It preserves the existing cluster, release policy, and known-good manifests.

```powershell
.\scripts\lab.ps1 -Action status
.\scripts\lab.ps1 -Action gitops-fault-matrix
```

The matrix runs serially: latency, startup, no preview traffic, temporary
telemetry outage, shared telemetry outage, then a healthy release. Each child
trial archives its scan, SBOM, observations, controller state, and verdict.
The enclosing matrix records child run IDs and explicit recovery attempts.

| Scenario | Required evidence |
|---|---|
| latency | Candidate p95 metric Failed; old service preserved; Git recovery verified |
| startup | Native progress deadline exceeded; old service preserved; Git recovery verified |
| no-traffic | No preview clients; empty/NaN candidate measurements become Inconclusive; Git recovery verified |
| telemetry-outage | Prometheus temporarily scaled to zero after pre analysis starts; query errors; monitor restored when Git recovery starts; fresh recovery verification |
| shared-telemetry-outage | Monitor stays unavailable through the unchanged 600-second recovery deadline; persisted recovery_failed; monitor restored; failure remains until explicit retry |
| healthy | Complete pre/post gates and serving/Git acknowledgement |

The telemetry scenarios build healthy application artifacts; the observer injects
the dependency fault. Monitoring is outside the Argo application's Git-owned
manifest path. The fixture records its prior replica count before scaling,
restores that count in `finally`, and leaves application manifests and Service
selectors to their owners. The shared outage demonstrates a dependency required
to verify fallback health; it does not simulate an application database outage.

The ordinary shared-outage trial must exit unsuccessfully and retain
`trial-failed`. Only the enclosing matrix can certify that this expected failure,
the fixed deadline, and the explicit retry were verified. Recovery timers are
not shortened for the demonstration. The startup and shared-outage cases each
include a ten-minute wait; allow 45–60 minutes for the full sequence, including
builds, reconciliation, and the final healthy analysis windows.

The runner archives analysis snapshots while observing, and recovery archives
the failing state before native cleanup. Acceptance requires evidence of the
intended failure, not merely any eventual recovery. Serving observations must
all return HTTP 200 for these pre-promotion scenarios. Final availability checks
run before archival so a failing check cannot retain a successful verdict.

For a single case:

```powershell
.\scripts\lab.ps1 -Action gitops-trial -Scenario no-traffic
.\scripts\lab.ps1 -Action gitops-trial -Scenario telemetry-outage
```

Use the matrix for the shared-outage case, because it also performs the explicit
recovery retry. A direct shared-outage trial deliberately fails. `Ctrl+C` requests
cleanup; a forced process kill or host shutdown cannot run Python cleanup.
If interrupted during a telemetry fixture, inspect its
`output/gitops-*/telemetry-fixture.json`, restore the recorded monitor replica count,
wait for monitoring to be ready, then inspect `recovery-status` before an explicit
`recovery-retry`. Do not clear failed status files or edit the lease to bypass it.

Source pushes to main can independently schedule builds. Keep main unchanged
during these serial fault experiments. The matrix checks queue/build idleness
and Trivy database freshness before each case; the normal CI scan gate remains
enabled. Passing local experiments does not establish production availability
or recovery percentiles.

Live acceptance results are recorded below only after the experiments complete.
