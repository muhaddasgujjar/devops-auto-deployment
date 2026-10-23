# Releaseboard product foundation

Open http://localhost:8083/ for the React/Vite dashboard, served by FastAPI with
PostgreSQL metadata. API documentation: http://localhost:8083/docs.

This milestone is a read-only operations portal for the existing single-app lab.
Jenkins, Argo CD, Rollouts, and the recovery worker retain ownership of builds,
desired state, traffic and recovery. Multi-user roles, onboarding, promotion APIs
and external notification delivery remain pending.

## Views and freshness

- Overview: serving revision, targets, latest build, evidence totals, GitOps sync,
  recovery status and recorded pre/post analysis results.
- Releases: chronological, searchable outcomes and independent serving checks.
- Builds: modes, duration, outcomes and links to authoritative Jenkins logs.
- Evidence: failures and incomplete experiments remain visible. Drawers provide
  scans, SBOMs, analyses and raw observations as verified downloads.
- Activity: durable reconciliation transitions and signed integration receipts.

The browser refreshes cached API data every 15 seconds. The observer polls every
20 seconds plus collection time, independently of HTTP requests. Observations
older than 60 seconds, any missing source, or an observer error prevent an overall
healthy badge. Target ages describe the last observation. A completed analysis
is historical evidence, not continuous SLO proof. A failed build can coexist with
a healthy running release.

## Data and event model

Migration `3ad06a64c009` creates projects, environments, builds, artifacts,
releases, analyses, recovery attempts, evidence runs, observations, audit events,
inbox receipts and outbox events. The fixed lab project/environment are seeded.
Digests and Git SHAs are retained. Repeated identical observations upsert records
without duplicate transition events. Archived evidence remains immutable in its
independent store; product records provide a queryable projection.

Views return up to 100 releases/builds/analyses and 200 evidence runs. Earlier
analysis files remain downloadable even when their native objects were cleaned
up. Analyses observed by the API persist in PostgreSQL after native cleanup.

`POST /api/integrations/events` accepts exactly `kind`, `resource_id`, and `state`;
kind is `build.observed` or `release.observed`. It records a receipt for later
reconciliation, never a deployment command or authoritative state override.
Required headers are `X-Release-Event-Id`, `X-Release-Timestamp` (Unix seconds),
and `X-Release-Signature` (`sha256=` plus the hexadecimal HMAC-SHA256).
Sign the exact bytes `timestamp + "." + event_id + "." + request_body` with
`RELEASE_CALLBACK_SECRET`. Deliveries expire after five minutes. Duplicate IDs
are idempotent across restart; changed payloads under an existing ID return 409.
Payloads are capped at 256 KiB and arbitrary credential structures are rejected.

Inbox processing, audit and outbox writes share a transaction. Unprocessed
receipts survive restart. Outbox events remain pending until a real notification
receiver is configured; delivery is never implied. User roles, promotion
concurrency, and bounded external notification retries are the next product slice.

## Install and operate

The existing Linux venv is used. Python dependencies are pinned in
`apps/api/requirements.lock.txt`; frontend dependencies use `package-lock.json`.

```powershell
wsl -d Ubuntu-24.04 -u root --cd 'C:\Users\hasnat\OneDrive\Desktop\Abdullah Saleem\projects\devops-auto-deployment' --exec /opt/release-lab/venv/bin/python -m pip install -r apps/api/requirements.lock.txt
Set-Location apps/web
npm ci
npm run build
Set-Location ../..
.\scripts\lab.ps1 -Action portal-setup
.\scripts\lab.ps1 -Action portal-status
```

`portal-setup` preserves the labelled `release-portal-db` container and retained
`release-portal-data` volume, applies migrations and installs/restarts systemd
`release-lab-portal.service`. It is repeatable. `portal-start`/`portal-stop` manage
these components. Ordinary lab start/stop includes them after setup. The UI is a
production static build; no Node server is needed during review. After changes,
rebuild the UI and rerun `portal-setup` to migrate/reload the backend.

PostgreSQL uses the image digest in `versions.json`, loopback port 5433, 32 MiB
shared buffers, 20 connections, a 192 MiB cap and 0.5 CPU. The API uses loopback
8083 with a 192 MiB/35% CPU systemd limit. Generated database and callback
credentials stay in protected `/opt/release-lab/secrets/portal*.env` files, outside
the checkout. The API returns no credentials or console logs. Evidence downloads
must belong to the requested run and match their stored size and SHA-256.

This local profile trusts the operator and has no user login. Keep it loopback
only. The observer still uses the existing admin kubeconfig; a shared deployment
needs dedicated RBAC and server-enforced user roles. The database survives
component restarts. Existing evidence backups do not include PostgreSQL;
database backup/restore and off-host coverage remain required before shared use.

## Verification

```powershell
wsl -d Ubuntu-24.04 -u root --cd 'C:\Users\hasnat\OneDrive\Desktop\Abdullah Saleem\projects\devops-auto-deployment' --exec /opt/release-lab/venv/bin/python -m unittest discover -s apps/api/tests -v
wsl -d Ubuntu-24.04 -u root --cd 'C:\Users\hasnat\OneDrive\Desktop\Abdullah Saleem\projects\devops-auto-deployment' --exec env PORTAL_TEST_POSTGRES=1 /opt/release-lab/venv/bin/python -m unittest discover -s apps/api/tests -v
```

The PostgreSQL suite migrates randomly named, isolated test schemas and removes
only those schemas. It does not reset the product database. Checks cover repeated
reconciliation, chronological histories, concurrent event delivery, restart
deduplication, payload conflicts, stale/invalid signatures and corrupted or
unauthorized evidence downloads. Core tests stay separate so the lean Jenkins
demo job does not require product dependencies. Wiring product checks into SCM
CI is outstanding.

Browser checks cover responsive layout, evidence search, file drawers, outcome
filtering and build/activity navigation. Saved checks/screenshots are under
ignored `output/portal-*` paths. The remaining Jenkins/GitOps fault matrix is a
separate unfinished acceptance gate; this UI does not relabel those failed runs.

On 23 October 2026, eight API tests passed on PostgreSQL, all 35 core tests passed,
and all 21 manifest/config validations passed. The production frontend build
passed. Restarting PostgreSQL and the API retained the same 14 releases, 13 builds,
13 artifacts, 45 evidence runs and existing audit/outbox records; the receipt is
`output/portal-restart-check.json`. The final lab health check includes the portal
and passed with no attention conditions. These are local foundation checks, not
production or multi-user acceptance.
