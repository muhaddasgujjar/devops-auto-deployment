# Persistent monitoring and release evidence

This local milestone keeps Prometheus samples across pod replacement and saves
trial evidence independently of the source checkout. It adds no always-running
database service: the evidence CLI uses Python's SQLite and a content-addressed
object directory. PostgreSQL remains the planned product backend.

## Storage boundaries

- Prometheus uses `monitoring/prometheus-data`, a 2 GiB claim with the
  `release-retain` local-path StorageClass. Retention is 24 hours or 512 MB of
  retained blocks, whichever limit applies first. WAL and temporary compaction
  files add overhead; the local-path requested size is not a filesystem quota.
- `Recreate` ensures a single Prometheus writer during Deployment updates.
  Monitoring pauses briefly during maintenance; run maintenance only after the
  active release is Healthy and CI is idle.
- Evidence lives at `/var/lib/release-lab/evidence` in WSL, outside OneDrive and
  the checkout. Its SQLite catalogue records verdicts and availability failures;
  SHA-256 objects retain reports, scans, SBOMs, observations and desired manifests.
  Jenkins console logs and credential files are deliberately excluded.
- Run identifiers are immutable. Archiving the same evidence is idempotent;
  changed content under the same identifier is rejected. Missing summaries must
  explicitly be archived as `incomplete`, never as successful experiments.

Local volumes survive pod replacement and normal lab stop/start. They do not
provide replicated storage, node-loss recovery, or protection from deleting the
k3d cluster/WSL distribution. Retain protects the volume's reclaim behavior;
it does not create an external backup. See [Kubernetes StorageClasses](https://kubernetes.io/docs/concepts/storage/storage-classes/)
and [Prometheus storage limits](https://prometheus.io/docs/prometheus/latest/storage/).

## Prove persistence and a real restore

From the project root in PowerShell:

```powershell
.\scripts\lab.ps1 -Action storage-check
```

The command refuses an unfinished release or running Jenkins build. It exports
available application samples before applying the storage manifests. On the
first migration from `emptyDir`, this JSON is a readable historical export;
it is not an import of the old TSDB into the new volume.

It then records a query at a fixed historical timestamp, stops/recreates the
Prometheus pod and verifies that exact sample. A clean shutdown precedes the
offline copy of the complete TSDB, including the WAL. The backup is restored to
a **different empty claim**, and a separate Prometheus instance must return the
same historical sample. This prevents fresh scrapes from masquerading as a
successful restore. The primary is restarted even if verification fails.

Reports and the SHA-256-identified TSDB archive are saved under
`output/storage-TIMESTAMP` and archived in the evidence store. Temporary copy pods
are removed; the restore Deployment is scaled to zero and its claim is retained
for inspection. Each check creates a new retained claim: run it intentionally,
and review disk usage before repeating it. Never delete the primary claim.

## Evidence catalogue and portable backups

Run module commands from the project root. New trial commands archive their
final reports automatically, including failed trials. These commands inspect
the independent store:

```powershell
wsl -d Ubuntu-24.04 -u root --exec /opt/release-lab/venv/bin/python -m scripts.evidence list
wsl -d Ubuntu-24.04 -u root --exec /opt/release-lab/venv/bin/python -m scripts.evidence verify
wsl -d Ubuntu-24.04 -u root --exec /opt/release-lab/venv/bin/python -m scripts.evidence backup --archive /var/lib/release-lab/evidence-backup.tar.gz
wsl -d Ubuntu-24.04 -u root --exec /opt/release-lab/venv/bin/python -m scripts.evidence restore --archive /var/lib/release-lab/evidence-backup.tar.gz --store /var/lib/release-lab/evidence-restored
```

Choose new backup/restore paths for subsequent attempts. Backups use SQLite's
consistent backup API, bundle referenced objects, and print the archive checksum.
Restore requires a new or empty directory, rejects unexpected archive entries,
and checks catalogue integrity and every object hash. It does not replace the
live store. An object hash detects accidental corruption; it is not a signature
against a malicious host administrator.

These backups currently remain on this machine. Copy a verified archive to an
independent disk/host before relying on disaster recovery. Jenkins home,
environment Git, registry images, credentials and the Kubernetes control plane
need their own backup policies; the evidence archive is not a full-lab backup.

## Acceptance record

The checked-in evidence tests cover source-folder loss, immutable run IDs,
idempotent archival, corruption detection, backup/restore and path traversal.
The live storage-check report records actual pod replacement and independent
TSDB restore; a failed report is retained as a failure, not a completed gate.

On 22 October 2026, `output/storage-20261022t183844z` passed both checks. The
historical query `sum(demo_requests_total{namespace="demo-dev"})` at timestamp
`1792694355.101` returned `13551` before replacement, after replacement, and from
the restored TSDB on its independent claim. The backup SHA-256 is
`e0031a3a8544eb32c15be01f4b674ba9bd789cd104db3face642ffb364a81bf8`.
The primary was restored to one replica and the verification instance to zero.
All 20 unit/HTTP integration tests passed on Windows and Linux, and all 20
resource/config documents passed the pinned upstream schema checks.

The evidence backup at `output/backups/evidence-20261022T184027Z.tar.gz` restored
into `/var/lib/release-lab/evidence-restore-20261022T184027Z` and verified all 278
file references across 20 runs (222 deduplicated objects). Its SHA-256 is
`0ae64144f4821c5137280f453a230aff2f754aefcf4af396aeade0947cb73a79`.
`output/persistence-verification.json` records both live and restored catalogue
checks. The interrupted 21 October observer is explicitly `incomplete`; failed
pilots remain failed. This archive is outside WSL but still on the same machine.
