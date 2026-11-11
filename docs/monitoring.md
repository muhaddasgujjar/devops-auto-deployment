# Persistent monitoring, local notifications and platform restore

Milestone 8 implementation is under acceptance. The accepted MVP estimate remains
80% until CI, the live monitoring trial and isolated restore pass.

Prometheus uses a 1 GiB static local PVC, `Retain` reclaim policy, one replica and
Recreate updates. Its TSDB retention is 24 hours / 512 MB with a 384 MiB memory
limit. These retention limits are not a hard filesystem quota: head data, WAL,
compaction and snapshots also use space. The directory belongs to UID 65534 on
the labelled k3d server. This protects pod replacement, not destruction of the
node/container or hardware loss. It is not replicated storage.

The first transition from the old ephemeral deployment initializes retained
storage. Previously ephemeral monitoring history is not claimed as migrated.
Acceptance captures known samples on the new PVC and checks the exact historical
query after replacement. Backups cover the retained TSDB separately.

## Rules and ownership

The ConfigMap contains versioned native rules for absent/failed demo scrapes,
sustained HTTP errors and sustained latency with minimum request volume. Run
`python -m scripts.check_monitoring_rules` for six actual promtool cases.
Rules describe workload signals; they do not declare controller rejection or
successful recovery. The API separately evaluates candidate rejection,
inconclusive candidate evidence, post-promotion incidents, recovery failure,
controller unavailability and Prometheus unavailability from durable evidence.
Missing telemetry preserves already-firing workload alerts until fresh evidence
can resolve them. Failed observations never become healthy by default.

Alert transitions and one notification per transition commit in the same
PostgreSQL transaction. Delivery uses an environment FIFO outbox, 45-second
leases, at most five attempts, and 5/15/30/60-second waits between attempts.
The fifth unsuccessful attempt becomes terminal `dead`; it does not retry forever.
A retrying firing notice blocks later resolution notices from overtaking it.
The dashboard distinguishes alerts from pending/delivered/exhausted delivery.

The notifier has a separate API service key, OS user and a read-only named
Prometheus proxy identity. It cannot import evidence, create recoveries, log into
the browser, access admin audit, mutate Kubernetes, write environment Git or use
the Docker socket. The receiver has its own OS user and bearer credential,
listens only on `127.0.0.1:8092`, and stores immutable ID/payload-hash receipts in
SQLite. It commits before acknowledging. Delivery is at least once; the local
receiver deduplicates IDs, including after restart. External email/chat delivery
is outside this milestone and requires the user's chosen destination.

## Existing-lab upgrade and operation

Stop all API, collector, recovery, notifier and receiver services before the
populated upgrade. Start the owned PostgreSQL container, load protected runtime,
bootstrap and migrator file paths as in the backend runbook, then run
`python -m scripts.migrate_monitoring` once from `0002_recovery`. It restores and
upgrades a copy first, compares original row hashes, then upgrades the main DB.
Do not rerun the older milestone-7 migration script on an upgraded database.

Start the lean cluster and run `python -m scripts.install_monitoring` to prepare
the owned node directory and apply the persistent configuration. Commit reviewed
source and build the portal before installing service snapshots:

```sh
/opt/release-lab/backend-venv/bin/python -m scripts.install_backend_services --refresh-observer-token --refresh-recovery-token --refresh-notifier-token
systemctl start release-state-api release-notification-receiver release-state-collector release-state-notifier
```

Start recovery explicitly for ordinary operation; the monitoring-only fault
experiment keeps recovery stopped to isolate alert/notification behavior. All
services are manually started, not boot enabled. Kubernetes service tokens last
one hour; refresh credentials and restart the corresponding services for later
sessions. Retain the WSL clock-conflict fix described in the recovery runbook.

Read-only API: `GET /monitoring`. Notifier/admin service routes:
`POST /monitoring/tick`, `POST /notifications/claim`, and
`POST /notifications/{id}/result`. Delivery results require the current lease and
the matching receiver receipt. Public operator roles cannot perform these writes.

## Backup and isolated restore

Quiesce API/collector/recovery/notifier/receiver and CI publishers, leaving the
working PostgreSQL container and Prometheus running. Commit code/configuration
before backup. Set the protected runtime/bootstrap/migrator configuration paths.

```sh
/opt/release-lab/backend-venv/bin/python -m backend.platform_backup backup
/opt/release-lab/backend-venv/bin/python -m backend.platform_backup restore --bundle /var/lib/release-lab/platform-backups/PRINTED_ID
```

The private bundle contains a custom PostgreSQL dump, environment Git bundle,
committed configuration archive, SQLite receiver backup and head-inclusive
Prometheus TSDB snapshot. It excludes runtime credentials and SSH/service keys.
File hashes and the manifest hash are recorded separately. Snapshot creation uses
the Prometheus admin API via the local administrator's Kubernetes proxy. The
notifier's GET-only identity cannot invoke this POST. The admin API remains on
the cluster service, not a public listener.

Restore validates file hashes before creating any target. It refuses existing
destinations, restores a new named database and bare Git repository, checks exact
row hashes/default branch/refs, starts an isolated API and a no-scrape Prometheus,
and reproduces the saved historical query. Receiver receipt content is checked
separately. Temporary API credentials/processes and the labelled restore container
are removed; a successful disposable database is removed after verification.
The archive and isolated restored files remain for review. Failed targets remain
for diagnosis. Source database content and environment refs must remain unchanged.

This is a quiesced functional recovery check, not point-in-time recovery or a
full-machine disaster-recovery guarantee. Existing OS services, external secrets,
container images and the registry need their own provisioning on another machine.
Transfer private archives separately from Git and recreate credentials there.

## Shutdown

```sh
systemctl stop release-state-notifier release-notification-receiver release-state-recovery release-state-collector release-state-api
/opt/release-lab/venv/bin/python -m scripts.backend_runtime stop
```

Stop the cluster/CI with the existing lab helper and stop its registry. Preserve
the working volumes, retained monitoring directory, environment Git and private
backups. The older unrelated PostgreSQL service on port 5433 remains unmanaged.
