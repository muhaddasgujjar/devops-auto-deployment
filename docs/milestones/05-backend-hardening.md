# Milestone 5: backend permissions, CI and supervised collection

Completed 10 November 2026 for local acceptance. These early backend prerequisites
are complete before starting the real-data interface.

| Gate | Accepted evidence |
|---|---|
| Restricted PostgreSQL runtime | Normal API/import/reconciliation passes; DDL, database creation, role escalation, audit rewrites/deletion and event-identity changes are denied |
| Separate migrations | Non-superuser migrator owns application schema/tables and performs actual schema changes |
| Backend/worker tests | 32 pass on real PostgreSQL; 54 core/demo tests also pass |
| Supervision | Dedicated non-root API and observer users; both automatically restart after SIGKILL |
| Scoped Kubernetes access | Target reads allowed; rollout patch, secret list, pod creation and other-application read denied |
| Outage recovery | Removing/restoring the observer binding records unavailable/current; API outage exhausts three bounded attempts and recovers |
| Restricted-role restore | New restored database returns identical environment/releases/builds/audit through the runtime role |
| Backend CI negative gate | Jenkins build 1 has exactly one intentional test failure (33 tests); no scan/SBOM or published registry tag |
| Backend CI positive gate | Jenkins build 2 passes all 32 tests, boots UID 10001 runtime, scans OS/Python, emits SBOM and publishes verified digest |

CI source: `4920c8d61cd9bbaecdacb8ef3787f9b0913de224`.
Published runtime:
`localhost:5001/release-state@sha256:7dfc7600acb3bbf8b96759e59cab852ba9f7778fc153132ce67df33d59e65365`.
True OCI config digest:
`sha256:eb53b2a93fb3edf54efb84b106bc51988d564deb8a4d004bcff139f415590899`.
Trivy 0.76.0 reported **zero HIGH/CRITICAL findings**, with both Alpine OS and
Python dependency results present. The CycloneDX SBOM contains 63 components.
All CI PostgreSQL containers, credentials, networks and test volumes were
ephemeral; published image/test provenance was checked independently. The negative
tag was independently verified absent from the registry. Demo environment Git
remained at `d64ce70aed529b8649e51b504d6e673c7dd6b517`; this job does not deploy it.

The service tests used the committed backend snapshot
`a9ed12a114eeb1668262189d43ae079c4d12ce65`. API and collector crash restarts each
incremented the actual systemd restart counter. Source permission loss retained
the stored serving revision. A new backup was restored, ownership/grants were
reapplied, and four API views matched through the restricted database role.
These functional trials do not establish production uptime or timing benchmarks.

## Evidence and operation

- `docs/evidence/backend-tests.json`: 32 backend/worker tests including permissions,
  conflict re-snapshotting, uncertain POST replay and retry bounds.
- `docs/evidence/merge-validation.json`: 54 separate core/demo tests.
- `docs/evidence/backend-services-acceptance.json`: actual service restarts,
  scoped Kubernetes authorization, outages and restricted-role restored API.
- `docs/evidence/backend-ci-acceptance.json`: independent registry/test/scan/SBOM
  correlation and both Jenkins results.
- [Hardening runbook](../backend-hardening.md): credential separation, service
  installation, token refresh, CI setup and restore commands.

The cluster, services, database, registry and CI started for this milestone were
stopped after validation. Their persistent state and the existing older database
were preserved. Neither external messages nor a remote Git push were performed.

## Limits and next work

Services are manually started, not enabled at boot. The scoped observer token has
a one-hour lifetime and must be refreshed explicitly before later sessions; expiry
fails closed as unavailable. The trusted Docker-socket CI agent remains a local
lab boundary. External SCM/PR isolation, TLS ingress, SSO/multi-tenancy and bigger
machine reproduction are still open.

Next: the minimal authenticated interface using actual environment/release/scan/
analysis/audit data and clear stale/unavailable states. Post-promotion recovery,
notifications and broader evaluation remain later gates. No recovery action
should be exposed before its Git-authoritative implementation is verified.
