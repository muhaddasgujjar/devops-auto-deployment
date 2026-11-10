# Next milestone: durable release and evidence state

Completed for local acceptance on 10 November 2026; see
[milestone 4](milestones/04-durable-state.md) and
[current progress/next priorities](progress-after-backend.md). The text below
retains the original acceptance plan.

This is the next laptop milestone after runtime rejection acceptance. The existing
CI/controller path supplies evidence; the product backend must retain and explain
it. No database, API or UI completion is claimed by this plan.

## Ordered implementation

1. **Define contracts and authority first.** Keep source commit, build ID, scanned
   image identity, registry digest, environment commit and candidate hash as
   separate fields. Represent desired candidate and serving stable independently.
   Preserve `failed`, `inconclusive`, provider error, readiness timeout and promoted
   outcomes. A successful Jenkins build means publication, not promotion.

2. **Add PostgreSQL and migrations.** Use FastAPI, SQLAlchemy and Alembic with a
   local PostgreSQL service. Model project/environment, build/artifact, release,
   analysis, observation, incoming event and audit record. Store raw payload hashes
   and provenance with parsed state; use UTC timestamps and durable unique keys.
   Migration and restore commands must be documented and work on a fresh database.

3. **Import existing evidence before adding new callbacks.** Validate the committed
   CI and runtime reports, link every release to its source/image/environment
   identities, and preserve failed/excluded attempts. Importing the same report
   twice must produce no duplicate releases or audit effects. Import all records
   in a transaction so a malformed report cannot leave partial accepted evidence.

4. **Expose a small authenticated API.** Provide release history, per-environment
   desired/serving state, build/scan/SBOM references and analysis outcomes. Use
   server-side read/developer/admin permissions. Validate callback signatures,
   timestamp freshness and payload size before accepting events. Keep a local-only
   test mode explicit; never silently bypass authentication in the normal service.

5. **Make ingestion durable and ordered.** Persist an event ID with a payload hash;
   identical retries return the prior result, conflicting reuse is rejected.
   Transactional deduplication and environment version checks must prevent racing
   writers. Delayed callbacks must not overwrite newer serving state. Preserve
   event time and ingestion time separately, accounting for the observed clock
   corrections rather than treating wall-clock order as release authority.

6. **Reconcile after restart.** A read-only worker compares the latest environment
   Git revision, Argo sync, Rollout candidate/stable hashes and analysis evidence
   against stored state. Mark stale/unknown state explicitly when a source is
   unavailable. The worker must not become a second deployment controller: CI
   publishes Git, Argo CD syncs and Rollouts selects the serving revision.

7. **Verify on actual PostgreSQL.** Exercise duplicate/conflicting events,
   transaction rollback, concurrent environment updates, forged callbacks,
   out-of-order events, process restart and backup/restore. Use the existing runtime
   evidence as import fixtures. SQLite-only checks do not prove PostgreSQL locking
   or migration behavior.

## Acceptance evidence

- A new database can be migrated and seeded from the real evidence reports.
- Re-import, concurrent delivery and process restart preserve release identity
  and prevent duplicate side effects.
- API results correctly distinguish a rejected desired candidate from its healthy
  serving stable release, and a healthy promotion from mere CI success.
- Invalid authentication and conflicting event identities are rejected; audit
  records explain accepted state transitions and excluded evidence.
- Read-only reconciliation converges after a missed callback and reports source
  outages without inventing healthy state.
- A database backup is restored into a separate empty database and checked through
  the API. Commands and sanitized receipts are committed.

Keep PostgreSQL/API work separate from full cluster/CI observations on the 8 GB
laptop. Stop the lab while coding and testing the backend; run the services
together only for the integration acceptance. No paid API, cloud database or
subscription is required. Keep the other-machine migration deferred.

## Following sequence

After durable state works, build a minimal real-data interface for environment
status, release history, scans and decision evidence. Then implement post-promotion
detection and Git-authoritative recovery, including serialization, recovery failure
and audit trails, before exposing any recovery action in the interface. Add local
notifications, repeated trials and migration/reproduction on the other machine.

Human scope validation, supervisor acceptance, external SCM/branch policy and TLS
registry access remain tracked gaps. They do not block this reversible local
backend work and must not be marked complete without evidence.
