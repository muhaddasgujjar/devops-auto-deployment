# Post-promotion recovery

Local functional acceptance passed for error and latency recovery; see
[milestone 7](milestones/07-post-promotion-recovery.md) and the
[independent receipt](evidence/recovery-acceptance.json). Pre-promotion rejection
remains a separate capability. This is not a production availability result.

## Policy and ownership

`backend/recovery_policy.py` fixes policy `post-promotion-v1`: monitor a promoted
deployment for one hour, in completed 30-second windows. Three consecutive bad
windows trigger one incident per deployment/policy. Each window needs at least
100 estimated requests from Prometheus `increase`, both current serving pods up,
and scrape age at most 15 seconds. Error ratio above 5% or P95 above 0.5 seconds
is a breach. Missing, stale, empty, nonfinite or low-traffic data is inconclusive.
Queries select both pod hash and the current serving pod names, avoiding retired
series. Recovery needs three healthy windows plus at least 100 actual matching
HTTP 200 probes with no identity mismatches and a maximum ten-second sample gap.
Health windows used for success must begin after recovery publication/verification.

A target must have been promoted earlier within seven days, with a bound immutable
image/scan identity, zero recorded HIGH/CRITICAL findings, scan/SBOM hashes,
successful candidate analysis and an accepted healthy HTTP observation. A known
incident origin is excluded from future target selection. No target records an
explicit failure without a Git write. One active incident is allowed per
environment, with a five-minute cooldown after the last terminal transition.
Recovery has a ten-minute deadline, including ordinary Argo polling, possible
cold-target pre-promotion analysis and fresh serving verification.

The recovery process writes only the accepted pod template into today's Rollout
manifest and adds a marker outside Argo's workload directory. It preserves
current strategy, services, replica count and unrelated Git files. Every change
is a forward child of the failed deployment's environment commit. Normal Git
fast-forward conflict handling lets a competing publisher win; the writer never
rebases or force-pushes. A retained incident marker identifies an already-pushed
commit after a crash/uncertain API response. A process lock and a PostgreSQL
partial unique index prevent multiple active recovery owners.

Argo CD discovers Git changes and Argo Rollouts owns promotion/service selectors.
The recovery account cannot patch Rollouts, services or Applications, execute in
pods, or read secrets. It can read the managed rollout/pods/analysis/application
and proxy GETs to the two demo services and Prometheus. Finite read-only preview
probes supply the existing candidate traffic gate when an accepted target starts
cold. [Rollouts rollback behavior](https://argoproj.github.io/argo-rollouts/features/rollback/)
can fast-track an existing retained revision; fresh serving evidence is still
required before this ledger reports success.

## Durable contracts

Migration `0002_recovery` adds immutable health windows and recovery events,
versioned incidents, first-promotion time and an environment-wide controller
sequence. A deployment is identified by build **and environment Git commit**.
Restoring an older build therefore creates a new deployment record and preserves
its original acceptance record. Lower build numbers only apply through an
authorized recovery; old controller sequences cannot regress desired state.

Incidents move proposed → applying → verifying → recovered, failed or superseded.
Failure remains terminal even if a previously published recovery later serves
healthy traffic. Observations still record that serving truth; they do not turn
the failed incident into a success. Clock discontinuities stop actuation, and a
trial with inconsistent wall/monotonic time is excluded rather than benchmarked.
The dedicated `recovery` API role can read evidence and submit health/phase events;
it cannot import curated acceptance, access admin audit or create browser sessions.
The observer's HMAC credential cannot create a recovery incident. Runtime SQL
grants preserve incident origin/target/policy and append-only event/window data.

Read APIs: `/recoveries`, `/recovery/policy`, `/recovery/health?release_id=<id>`.
Service writes: `POST /recovery/health` and `POST /recoveries/<id>/events`, with
environment and incident version checks and durable event IDs. The portal exposes
read-only incident history, source/target identities, trigger windows and phase
timeline. Operator retry buttons are not part of this milestone.

## Upgrade and start the existing laptop lab

Stop API/observer/recovery before migrating. `scripts.migrate_recovery` creates a
backup, restores an isolated copy, proves the populated upgrade preserves counts
and identities, then migrates the real database and checks the restricted runtime.
It runs once from `0001_release_state`; an already migrated installation skips it.
Set the protected `RELEASE_CONFIG_FILE`, `RELEASE_BOOTSTRAP_CONFIG_FILE` and
`RELEASE_MIGRATION_CONFIG_FILE` paths described in the backend runbook. Preserve
its backup and receipt. Existing milestone-6 service snapshots cannot serve the
new schema; install the committed new snapshot before starting them again.

Build the portal as in [portal operation](portal.md), commit reviewed source, then
start the lean lab. Its local SSH setup creates a separate repository-scoped
recovery key and denies non-fast-forward/deletion ref updates. In WSL:

```sh
/opt/release-lab/venv/bin/python -m scripts.backend_runtime start
/opt/release-lab/backend-venv/bin/python -m scripts.install_backend_services --refresh-observer-token --refresh-recovery-token
systemctl start release-state-api release-state-collector release-state-recovery
cat /var/lib/release-recovery/status.json
```

Recovery runs as a separate non-root systemd user from an immutable source
snapshot. LoadCredential supplies its service API key, read-only Kubernetes token,
separate SSH key and host-key trust anchor. It receives no database/admin/HMAC
credential or Docker socket. TLS verification is required for direct Kubernetes
signal reads. Startup is manual, crash restart is bounded, and both Kubernetes
tokens expire after one hour. Refresh explicitly and restart the relevant
services for a later session; token expiry cannot authorize a recovery.

Supplemental historical acceptance is imported with `--kind recovery_target`.
`scripts.record_recovery_target` first checks preserved artifact hashes and scan/
image/analysis identities. It supplements missing scan identity without rewriting
the original report, changing environment desired state or inventing a new trial.
Target enrollment currently uses these curated retained receipts. A newly
observed successful CI release does not automatically acquire accepted target
status without its bound scan/SBOM, analysis and HTTP acceptance evidence. If no
eligible retained target exists, the worker records `no_accepted_target` and
does not publish Git. Automating that evidence-enrollment path is later integration
work; this milestone proves recovery against an explicitly enrolled target.

## Acceptance and shutdown

Check host time before trials. This Ubuntu 24.04 WSL installation had both
Hyper-V host synchronization and `systemd-timesyncd` active. Repeated wall-clock
corrections invalidated two trial attempts. Following
[Canonical's WSL time guidance](https://ubuntu.com/wsl/docs/stable/explanation/time-sync/),
the conflicting NTP unit was stopped and disabled in this WSL distribution;
Windows/Hyper-V time synchronization remains active. No Windows time setting or
kernel clock-source setting was changed. A fresh 30-second wall/monotonic/raw
clock capture showed about 5 microseconds of wall/monotonic offset variation.
Fresh trial streams must independently pass the two-second clock-consistency gate.
Do not suppress this gate or adjust stored incident timestamps to obtain a pass.
The reversible unit change is `systemctl disable --now systemd-timesyncd`;
`systemctl enable --now systemd-timesyncd` restores its prior enabled state but
may reintroduce this conflict. Review the target machine's own time setup before
applying the same change elsewhere.

Run core and PostgreSQL suites before configuring reviewed Jenkins sources. The
backend pipeline also runs real temporary Git conflict/idempotency tests in its
test-only Git-equipped container; the published API image remains non-root.
After clean-source/backend CI acceptance, configure the normal `release-merged`
job to the same reviewed commit and run:

```sh
/opt/release-lab/backend-venv/bin/python -m scripts.recovery_trial error --restart-writer --telemetry-gap-seconds 120 --stop-ci-after-build
# Start the managed Jenkins controller/agent again before the next trial.
/opt/release-lab/backend-venv/bin/python -m scripts.recovery_trial latency --stop-ci-after-build
```

The root lab test injector waits for a genuinely healthy promoted build before
writing only `/fault/mode` in its two serving pods. The demo's opt-in 1 MiB
ephemeral fault volume has no HTTP activation route. This injector is separate
from the recovery service's read-only Kubernetes identity. It removes its own
fault marker on failure/exit and retains failed trials. Initial CI discovery uses
the established manual Argo refresh; recovery discovery uses ordinary Argo polling.
The driver never patches live selectors or the recovery deployment.

A ten-minute timeout, lost sources or unavailable Git records failure rather than
success. Retain failed trials, event timestamps, controller snapshots and client
streams. Git and PostgreSQL do not form a distributed transaction: forward Git
publication is authoritative; an uncertain publication is reconciled through its
marker and fresh source snapshots. This local functional acceptance is not an
availability guarantee or a repeated timing benchmark.

```sh
systemctl stop release-state-recovery release-state-collector release-state-api
/opt/release-lab/venv/bin/python -m scripts.backend_runtime stop
```

Stop the cluster/CI separately with `scripts/lab.ps1 -Action stop`. Preserve all
volumes, environment Git, backups and reviewed source snapshots. The unrelated
older database on 5433 remains outside this milestone's management.
