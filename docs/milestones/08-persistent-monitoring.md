# Milestone 8: persistent monitoring and local notifications

Status: **local technical acceptance passed, 11 November 2026**. The scoped MVP
estimate is approximately **83%**; [the weighted rubric](../progress-after-monitoring.md)
awards three observability points. Browser visual review, interviews, second-user
pilot and supervisor scope acceptance remain open.

Accepted implementation source: `83705f347d535dba6cb1e6ddeede1925ed42b1b8`.
Documentation and evidence closeout commits follow that source. The installed
API, collector, recovery and notifier use immutable service snapshots; credentials
stay outside Git. See [operation and restore instructions](../monitoring.md).

## Accepted evidence

| Check | Actual result |
|---|---|
| Core tests / manifest schemas | 60 tests / 38 resource documents passed |
| Backend CI | Build 19: 88 tests, runtime and portal assets verified, zero reported HIGH/CRITICAL vulnerabilities |
| Publication guard | Build 18: exactly one intentional failure, no registry publication |
| Frontend | Five tests, TypeScript compilation and production bundle passed; no visual acceptance claimed |
| Native Prometheus rules | Six promtool cases for sustained errors, resolution, scrape absence and latency/volume |
| Permissions | Eight live Kubernetes authorization checks, separate service users, API import/recovery/audit/browser writes denied |
| Origin release | Real Jenkins build 22, promoted immutable image through environment Git and Argo |
| Fault observations | 21,901 stable-endpoint observations, including 5,338 matching HTTP 500 responses; final 100 matching healthy HTTP 200 responses |
| Sampling validity | Maximum sample gap 0.944 seconds; wall/monotonic offset span 0.064 seconds |
| Notifications | Actual firing and resolution events; receiver outage, retry, restart and expired-lease replay; one immutable inbox entry per notification |
| Persistent metrics | Four exact historical series identical after Prometheus pod replacement; original PVC and PV identities retained |
| Isolated platform restore | All 17 database table fingerprints, Git refs/default branch/fsck, configuration archive, eight receiver receipts and four historical metric series verified |
| Restored API | Separate API ready; desired and stable identity matched, with four recovery records and monitoring/audit history readable |

Receipts: [CI](../evidence/backend-ci-acceptance.json),
[core tests](../evidence/merge-validation.json), [rules](../evidence/monitoring-rules.json),
[permissions](../evidence/notification-permissions.json),
[live monitoring](../evidence/monitoring-acceptance.json),
[portal HTTP/assets](../evidence/portal-service-acceptance.json),
[backup](../evidence/platform-backup.json), [restore](../evidence/platform-restore.json),
and [shutdown/source verification](../evidence/monitoring-closeout.json).
The live raw trial is `output/monitoring-20261111T083842Z`; raw files are hashed in
its summary and the public receipt. This is one functional experiment, not a
latency distribution or production availability result.

## Persistence and delivery boundaries

The implementation adopts the earlier version's existing 2 GiB local claim,
`release-retain`, without shrinking or rebinding it. Previously ephemeral history
is not claimed as migrated. Prometheus retains 24 hours / 512 MB, with a 384 MiB
memory limit and one Recreate replica. The measured data directory after pod
replacement was 1,024 KiB; this small functional trial does not establish long-term
capacity. WAL/head/compaction use additional space. Local node loss requires backup.

PostgreSQL alert transitions and outbox insertion share a transaction. FIFO
delivery uses 45-second leases, bounded backoff and a maximum of five attempts.
The live error notice delivered on attempt three; resolution delivered on attempt
one. The uncertain-ACK experiment deliberately acknowledged to a real client
without reporting delivery to the API, then restarted the receiver/notifier and
let the lease expire normally. This proves replay and receiver deduplication;
it does not claim to have timed a process crash at the exact ACK boundary.

The private platform bundle is
`/var/lib/release-lab/platform-backups/8d0d7c026b01` in WSL. It contains database,
Git, configuration, SQLite and a head-inclusive TSDB snapshot, with per-file and
manifest hashes. It excludes runtime credentials. Restore used a new database,
separate bare Git directory, a no-scrape Prometheus and an independent API.
Source fingerprints and Git refs remained unchanged. Disposable processes,
container, API credentials and successful restore database were removed; private
archives and restored files remain. This does not provision an entire new machine.

Closeout verified installed source bytes and portal asset hashes against the
accepted commit, backup hashes and private modes, original PVC identity and
unchanged source database/Git. All five services and six owned containers were
stopped; API, receiver, preview, Jenkins and main database listeners were closed.
The older unrelated PostgreSQL service on port 5433 stayed running and unchanged.
The private bundle occupies 2,333,615 bytes. A post-restore memory sample is retained
in `output/m8-post-restore-memory.txt`; writers and CI were already stopped, so it
is explicitly not a peak-memory measurement.

## Retained failures and corrections

Backend build 13 passed tests but failed on an upstream Trivy database download
timeout. Build 14 subsequently blocked publication on 16 HIGH findings in the old
`krb5-libs` package. The signed Alpine patch is now pinned at `1.22.3-r0`; no scan
exclusion or update-skip flag was added. Build 15 exposed an incorrect exact-version
APK command and stopped before tests. It was corrected to `apk add --upgrade`.
Intermediate builds 16/17 passed the negative/positive gates; final-source builds
18/19 repeat those gates after the storage correction. See
[security evidence](../evidence/monitoring-runtime-security.json).

The first monitoring install tried to introduce a new 1 GiB static volume while
an older 2 GiB retained claim already existed. Kubernetes correctly rejected the
immutable binding/shrink change. The installer now validates and adopts the
existing claim. Only the newly created, unused Available PV metadata was removed
after checking its exact path, phase and lack of claim UID. Original PVC/PV/data
were preserved. Four core regression cases cover compatible adoption and refusal
of incompatible size/class/reclaim policy/binding.

Visual review remains blocked: the in-app browser failed initialization, and
Windows computer use stopped before input because it could not verify the current
browser URL. No screenshots or visual pass are claimed. See
[visual-review status](../evidence/monitoring-visual-review.json) and
[the human review worksheet](../pilot-and-scope-review.md).
