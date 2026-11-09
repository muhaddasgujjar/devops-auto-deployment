# Laptop-first delivery and later migration

Date: 10 November 2026 (Asia/Karachi). The user's selected sequence is to finish work suitable for the existing 8 GB laptop, then clone the same project onto the other machine. Do not require the other machine's details before progressing locally.

## Completed local recovery

- The k3s log contained an address-related networking startup error after WSL resumed: `failed to find interface with specified node ip`. The API briefly responded and then returned ServiceUnavailable. Further restarts converged on the assigned address and controllers recovered while WSL was held active. This is consistent with an upstream-reported restart/IP problem, not proof of a memory failure. [k3d issue](https://github.com/k3d-io/k3d/issues/1637), [k3s issue](https://github.com/k3s-io/k3s/issues/12639).
- No cluster was deleted, IP addresses reassigned manually, or network policy disabled. The launcher regenerates its ignored kubeconfig and now requires consecutive healthy controller observations instead of trusting a single transient Ready result.
- Restored the existing restricted local Git SSH service using the checked-in setup procedure. It retained the existing repository and keys. A hard Argo refresh cleared the stale connection error and synchronized environment commit `0401e6ceb244020af09c5c915241e038d64011bd`.
- The live doctor passed all six checks: node, Rollouts, Prometheus, stable service, fresh telemetry from both serving pods, and GitOps synchronization. See `docs/evidence/laptop-health-recovered.json`. It verifies the previously deployed digest, not a build of the latest merged source.
- Added `lean` and `full` startup profiles. The PowerShell launcher defaults to lean: it restores configured Git transport without starting Jenkins or its agent. It does not stop CI already running from a full session; run `stop` first when switching profiles. Full explicitly starts those managed containers. The low-level module retains its full default for compatibility; prefer the launcher on this laptop.
- Stop/start trials exposed k3d's post-start CoreDNS log wait failing after the Kubernetes API and pods were healthy. The helper is now bounded by a 75-second process deadline around `--wait=false --timeout 60s`. Only a process timeout or the specific CoreDNS log-wait deadline is deferred to mandatory independent readiness checks; other helper errors fail startup. Helper diagnostics remain in `output/cluster-start-helper.json`. These helper warnings are not themselves proof of readiness. Interrupted/failed attempts are not counted as successful lifecycle checks; the final corrected cycle is recorded separately.
- Added tests for readiness transients/timeouts and lean execution boundaries. The unified suite passes 34 tests. Individual Kubernetes calls have their own timeouts; the polling budget is checked between inspections, so the final in-flight inspection can extend past the nominal polling deadline.

The historical IP/startup issue can recur after host/network changes. The startup gate detects a persistent failure; it does not claim to fix every upstream IP-allocation scenario. Investigate logs if it cannot converge. Do not recreate the cluster or suppress readiness failures to obtain a green report.

Repeated rapid restarts also left historical `up=1` series in Prometheus's query lookback, alongside the two fresh current targets. The existing strict target-count/freshness checks correctly rejected those observations until the old series expired. The release-readiness polling budget is therefore 420 seconds (controllers remain 180). No metric threshold or target-count check was relaxed. The application can serve normally while this conservative telemetry gate waits. Readiness polling does not itself generate a new deployment.

## Lifecycle validation result

The final corrected cluster stop/start sequence passed all six release-health checks on two consecutive observations (14 polling attempts after the final observer was started). Jenkins and its agent remained stopped. See `docs/evidence/laptop-restart-validation.json` and the retained helper warning in `docs/evidence/laptop-start-helper.json`. This validates local resumption of the previously deployed release, not a cold WSL reboot, fresh-machine install, or new-source CI execution. Earlier interrupted/failing attempts are excluded. The lab is stopped at the end of this work session to release RAM.

## Daily laptop commands

```powershell
.\scripts\lab.ps1 -Action start -Profile lean
.\scripts\lab.ps1 -Action status
.\scripts\lab.ps1 -Action review
# End the work session:
.\scripts\lab.ps1 -Action stop
```

Lean startup verifies the node and controllers. `status` checks the application, telemetry and GitOps too; require those before release experiments. `review` opens loopback forwards; it is optional and consumes additional processes. Stopping preserves the cluster/volumes. Start/stop can be used on this existing lab; bootstrap is for a new machine and deliberately refuses to replace an existing cluster.

Run `-Profile full` only for an intentional CI session, with enough available memory, and avoid concurrent builds/scans during availability measurements. Heavy multi-node, parallel-build and benchmark work can move to the second machine later. A GPU is not needed for this platform.

## Work to complete here, in order

1. Recover and validate the lean lifecycle. Record the stop/start health result separately from the merge's failed health receipt.
2. Make the merged source the explicit trusted CI input, preserving the old source snapshot. Prove one serial local test/build/scan/push/environment-commit trace if memory permits. This remains open; a healthy old release is not that proof.
3. Add durable release/evidence storage and the minimal API: database migrations, idempotency, release serialization, and restart reconciliation. Most API/unit-test work needs neither a GPU nor a full cluster.
4. Build the three UI screens against real API contracts. Work with the lean lab or run API tests independently; do not start every optional service together.
5. Add local alert delivery, backup/restore procedures and failure-path tests. Run controlled recovery scenarios sequentially.
6. Finish requirements/user interviews and supervisor review in parallel. Keep the second-user pilot for a reproducible installation.

The limited RAM is a reason to serialize tasks and stop unused processes, not to stop source development. No additional hosting account is required by this plan. The project remains incomplete until the actual release/recovery and product acceptance gates pass.

## Cloning onto the other machine later

Source is committed locally; no external Git remote has been configured. When ready, either select a Git hosting destination and push deliberately, or transfer a local Git bundle without publishing:

```powershell
# After checking that your latest changes are committed:
git bundle create tmp/release-platform.bundle --all
git bundle verify tmp/release-platform.bundle
```

Copy that bundle to the other machine, then run:

```bash
git clone -b codex/foundation-baseline /path/to/release-platform.bundle release-platform
cd release-platform
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-validation.txt
.venv/bin/python scripts/validate.py
.venv/bin/python -m scripts.validate_manifests
```

A bundle/clone contains Git source and committed test evidence, not the running lab. Linux system tools are installed separately using the pinned-tool setup guide; a new lab is provisioned with `scripts/bootstrap-lab.sh` on a dedicated supported Linux environment. The Windows launcher specifically targets Ubuntu-24.04 in WSL and should not be copied as a native Linux launcher.

Regenerate kubeconfigs and machine-local credentials on the new host; configure its own Git SSH endpoint, verified host keys, registry connectivity and CI agent. Do not assume this laptop's `/opt/release-lab`, gateway IP, Docker volumes or cached images exist there. The current localhost HTTP registry is a lab-only boundary; a shared/remote setup still needs mutually reachable TLS registry configuration.

Database data, registry artifacts, Jenkins state, environment Git history and runtime evidence need separate application-aware backup/restore if they must be retained. Do not put credentials or volume archives into the source repository. Keep the existing environment Git history and retained stable images until recovery requirements permit removal.

Fresh-machine provisioning has not been tested on the second machine. Migration acceptance requires passing tests/schema checks, healthy services, and a fresh commit-to-release trial there. Prefer validating the new installation before retiring the laptop setup.
