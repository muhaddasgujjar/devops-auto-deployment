# Milestone 4: durable PostgreSQL state and authenticated API

Completed 10 November 2026 for the local prototype. Release/evidence storage,
authenticated APIs and bounded read-only reconciliation now work on real data.
This is the historical stage-4 checkpoint. [Milestone 5](05-backend-hardening.md)
subsequently completed the role separation, backend CI and supervision work.

## Accepted results

- **20 backend tests passed on a fresh migrated PostgreSQL database**: API roles,
  HMAC/expiry, request limits, malformed input, conflicting events, concurrent
  duplicates/writers, transaction rollback, delayed observations, restart,
  unavailable sources, unchanged-version freshness recovery and complete OpenAPI
  request-schema references. Malformed non-ASCII signatures are rejected as 401.
- **54 existing core/demo tests passed**. The immutable demo source in Jenkins
  still has its separate 36-test suite; this does not claim backend CI coverage.
- Real HTTP imports retained nine historical releases and ten builds, including
  the failed synthetic gate and excluded interrupted runtime trial. Replay and
  restart produced no duplicate effects.
- With the API stopped, actual Jenkins **build 17** delivered a healthy release
  through tests, scan/SBOM, registry digest, environment Git, Argo CD and Rollouts.
  Its local proxy trial observed **628 stable responses, all HTTP 200**.
- After restart, the database still held build 16. The read-only collector
  discovered build 17 and its exact image/Git/serving/analysis identities. An
  unavailable source set freshness to `unavailable`; a later read restored
  `current` with the same Kubernetes resource version and retained serving identity.
- A **47,799-byte custom-format backup** was restored into a new database,
  `release_state_restore_a56492e75d90`. A separate API process returned identical
  environment, release, build and audit views. PostgreSQL reported **17.11**.

Final database counts: 11 builds, 10 artifacts, 10 releases, six analyses,
11 observations, seven incoming events and seven audit entries. Build 5 is a
failed synthetic gate without an artifact/release. Live discovery leaves build
17's backend scan metadata unknown until CI evidence is imported; the separate
CI proof retains the actual passing scan. Missing provenance is not invented.

Final serving revision:
`05d553b044d566ce06fca3205db0632fe0328c77-jenkins-17`, hash `6c68b89cf4`.
Environment commit: `d64ce70aed529b8649e51b504d6e673c7dd6b517`.
Image: `localhost:5001/release-demo@sha256:4f4a15a16b0a0c5ff81fd3651f56425156a42ff92e50e7177fbb972349a8490e`.

## Evidence and reproduction

`backend/` supplies contracts, FastAPI roles, SQLAlchemy transactions, Alembic
migrations, report import, read-only collection, signed callback client and safe
backup/restore. Environment locks, unique event identity and expected-version
checks prevent duplicate effects and stale state replacement. Desired candidate
and serving stable remain separate. [Contracts and commands](../backend.md)
document setup, authentication, imports, reconciliation and restore.

Committed receipts:

- `docs/evidence/backend-tests-milestone4.json`: preserved 20-test receipt matching
  the original acceptance report hash; the latest suite is recorded separately.
- `docs/evidence/merge-validation.json`: separate core/demo suite.
- `docs/evidence/backend-acceptance.json`: real HTTP/process restart, missed
  release, source outage, restored API equality, archive and implementation hashes.
- `docs/evidence/backend-missed-release.json`: independently checked build-17
  scan/image/Git/controller identity and client observations.

The two-stage harness runs `python -m scripts.accept_backend import` while the
core lab is stopped, then a real healthy Jenkins/GitOps release with the API
stopped, followed by `python -m scripts.accept_backend reconcile-restore`. It
intentionally expects stored build 16 and a later live release: this is a dated
acceptance scenario, not a database reset command. API processes stop in `finally`.
Archives/logs/configuration stay private locally, outside committed source.
Milestone-2/3 history is preserved.

## Remaining boundaries

This is a loopback single-project/environment prototype with API keys. Runtime
and migrations currently share the local PostgreSQL owner role; separate
restricted runtime credentials are a hardening priority. A dedicated backend
build/test/scan job and supervised recurring collection precede broader exposure
and the next UI milestone. Automatic Jenkins callback hooks are not installed;
the HMAC callback path and on-demand collector are implemented and exercised.

The older `release-portal-db` on port 5433 was preserved. This backend uses its own
labelled container/volume on port 15432. Services started for this milestone are
stopped after final health verification, preserving data, archives and keys.
SSO, multi-tenancy, TLS ingress, notifications, public availability guarantees,
product UI and post-promotion Git-authoritative recovery remain open.
