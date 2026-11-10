# Release-state backend runbook and contracts

This backend records and explains releases. Jenkins publishes environment Git;
Argo CD syncs it; Rollouts controls the serving selector. The backend collector
uses only `get`/local Git reads and never applies, patches, promotes or rolls back.

## Contracts

| Record | Identity / meaning |
|---|---|
| Project/environment | This prototype serves one configured project/environment/job per API instance |
| Build | Unique project + CI job + build number; source SHA and result are immutable |
| Artifact | Registry image digest is separate from scanned image/config ID; absent scan proof stays unknown |
| Release | Environment + build; environment Git SHA and candidate hash remain distinct |
| Analysis | Candidate analysis name, phase and metric evidence |
| Observation | Event-linked response counts and accepted/historical/excluded/not-measured quality |
| Incoming event | Unique environment + external event ID; canonical content hash and exact request-byte hash |
| Audit | Actor, version, parsed changes, exclusions and unavailable-source records in the same transaction |

`desired` and `stable` in `GET /environment` can refer to different releases. A
published build does not imply a promoted release. The stable revision/hash remain
visible even if its full release record has not yet been imported. Failed CI gates
have a build record without an artifact or release; the original negative-gate
fixture is explicitly synthetic and retains its report in the event payload.

All writes lock the environment row within one SQLAlchemy transaction. The caller
supplies `expected_version`; a competing writer receives HTTP 409. Repeated event
IDs with identical domain content return their stored result, even if the caller
supplies a newer expected version. A reused ID with changed content receives 409.
The version field is excluded from domain hashing; exact request bytes have a
separate retained SHA-256. Failed transactions retain no partial accepted records.

For the configured CI job, increasing build numbers order publications. Within a
release, the trusted controller producer supplies an increasing observation
sequence and binds it to a Rollout UID. Older releases/observations remain evidence
and cannot replace newer serving state. A replacement controller UID is rejected
until an explicit enrollment/migration is designed; silently resetting Jenkins
build numbers is also unsupported.

The read-only collector is scoped to the pinned Kubernetes 1.35 CRD API and uses
the Rollout's numeric resource version as its observation sequence, only within
that controller UID/type. It re-reads Rollout and Argo metadata and environment Git
after collecting the snapshot and rejects changing sources. Kubernetes 1.35
documents ordering within the same API resource type; it does not justify
cross-type version comparisons or assuming a fixed integer size. Values beyond
this prototype's bigint contract fail closed.
[Kubernetes resource-version semantics](https://v1-35.docs.kubernetes.io/docs/reference/using-api/api-concepts/#resource-versions).

`freshness` is independent of the stored release outcome: imported evidence is
`historical`, successful current observation is `current`, observations older than
300 seconds are reported as `stale`, and failed source reads are `unavailable`.
Unavailability retains last-known desired/serving identities. Re-observing an
unchanged resource version can restore freshness without inventing a new release.
Source timestamps and ingestion timestamps are retained separately.

## API and authentication

| Endpoint | Permission |
|---|---|
| `GET /health/live` | Public process liveness only |
| `GET /health/ready` | read/developer/admin; database revision check |
| `GET /environment`, `/releases`, `/releases/{id}`, `/builds` | read/developer/admin |
| `GET /openapi.json` | read/developer/admin; API contract |
| `GET /audit` | admin |
| `POST /imports` | developer/admin; curated evidence import |
| `POST /callbacks` | Separate HMAC-authenticated collector identity |

User keys go in `X-API-Key`. Configuration stores SHA-256 key hashes and roles;
plaintext keys live only in the private tokens file. There is no default key or
authentication bypass. This is a local API-key prototype, not enterprise SSO.
FastAPI supplies header security dependencies;
[the documented API key mechanism](https://fastapi.tiangolo.com/reference/security/#fastapi.security.APIKeyHeader)
is combined with explicit server-side role checks here.

Callbacks sign the **exact body bytes** with
`v1=hex(HMAC-SHA256(secret, timestamp + '.' + body))` in `X-Release-Signature`;
`X-Release-Timestamp` is Unix seconds with a 300-second acceptance window. This
transport freshness check is separate from event deduplication and observed state
freshness. Invalid signatures, expired timestamps and payloads above 1 MiB are
rejected. Controller observations require a UID; callbacks cannot claim curated
HTTP experiment acceptance. The CLI signs callbacks without printing secrets.

Imports accept `ci_acceptance`, `runtime_acceptance` and `ci_negative_gate` reports.
They validate identities and outcome consistency before a transaction. Importing a
portable report records authenticated curator-provided proof; it does not rerun a
scan, re-hash unavailable raw output, or provide a digital attestation. Live-only
discovery leaves missing scan/config-ID metadata null rather than inferring it.

## Start on the current laptop

Run these from this checkout in Ubuntu/WSL. Start the core lab only for live
reconciliation. PostgreSQL uses its own labelled container and volume, bound to
`127.0.0.1:15432`; an older `release-portal-db` on 5433 is preserved.

```sh
python3 -m venv /opt/release-lab/backend-venv
/opt/release-lab/backend-venv/bin/python -m pip install -r requirements-backend-lock.txt
/opt/release-lab/venv/bin/python -m scripts.backend_runtime setup
export RELEASE_CONFIG_FILE=/opt/release-lab/secrets/backend/config.json
/opt/release-lab/backend-venv/bin/python -m alembic upgrade head
/opt/release-lab/backend-venv/bin/python -m uvicorn backend.api:create_app \
  --factory --host 127.0.0.1 --port 8090 --no-access-log
```

The final command stays in the terminal. Stop it with Ctrl+C. `setup` is repeatable
and preserves the database volume and credentials; `start`, `status` and `stop`
manage the same labelled PostgreSQL container without deleting it.

If WSL cannot reach PyPI, download a pinned Linux/Python 3.12 wheelhouse from
Windows, then install offline in WSL. The installed backend is separate from the
older CI/demo validation venv:

```powershell
python -m pip download --no-deps --only-binary=:all: --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --python-version 3.12 --implementation cp --abi cp312 -r requirements-backend-lock.txt -d output/backend-wheels
```

```sh
/opt/release-lab/backend-venv/bin/python -m pip install --no-index \
  --find-links output/backend-wheels -r requirements-backend-lock.txt
```

From another configured Linux terminal while the API is running:

```sh
export RELEASE_CONFIG_FILE=/opt/release-lab/secrets/backend/config.json
PY=/opt/release-lab/backend-venv/bin/python
$PY -m backend.cli import docs/evidence/ci-gitops-acceptance.json --kind ci_acceptance
$PY -m backend.cli import docs/evidence/runtime-failure-validation.json --kind runtime_acceptance
$PY -m backend.cli import docs/evidence/ci-negative-gate.json --kind ci_negative_gate
$PY -m backend.cli state
$PY -m backend.cli reconcile --kubeconfig output/lab.kubeconfig
```

The CLI runs one bounded reconciliation per invocation. Continuous worker/service
supervision and automatic Jenkins producer hooks remain operational follow-up
work; they are not installed as a desktop automation. The CLI sends credentials
only to an explicitly loopback HTTP origin. The database/configuration live under
the named Docker volume and `/opt/release-lab/secrets/backend/`, not Git. Protect
and transfer that private configuration separately when moving machines.

## Verify and restore

```sh
export RELEASE_CONFIG_FILE=/opt/release-lab/secrets/backend/config.json
/opt/release-lab/backend-venv/bin/python -m scripts.validate_backend
```

This creates and migrates an isolated `release_state_test_*` database, exercises
real PostgreSQL locking/transactions and API behavior, then drops only that test
database. The core/demo suite remains `python scripts/validate.py` in the original
validation venv. Transactions use SQLAlchemy's explicit commit/rollback context;
see [SQLAlchemy transaction documentation](https://docs.sqlalchemy.org/en/20/core/connections.html#using-transactions).

```sh
/opt/release-lab/backend-venv/bin/python -m backend.backup backup output/state-UNIQUE.dump
/opt/release-lab/backend-venv/bin/python -m backend.backup restore output/state-UNIQUE.dump \
  --database release_state_restore_UNIQUE123
```

An archive path must be new. A restore target must be new and have the required
prefix; it never cleans or overwrites an existing database. Configure a separate
protected copy of the settings with that database name to check it through the
API. The acceptance harness verifies identical environment, releases, builds and
audit API views after an actual custom-format dump/restore. PostgreSQL documents
this archive workflow in [pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html)
and [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html).

Alembic upgrades are explicit; application startup refuses a missing or unsupported
revision. Destructive downgrade is disabled. See the
[Alembic migration workflow](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

## Remaining boundaries

This is one local project/environment, not a multi-tenant service. API runtime and
migrations currently share the local PostgreSQL owner role; separate restricted
runtime credentials are a hardening priority before network exposure. Backend
packaging/build/scanning is separate from the existing demo-only Jenkins snapshot.
Keep the API on loopback. No UI, post-promotion actuator, SSO, TLS ingress,
notification system or production availability claim is included in this stage.
