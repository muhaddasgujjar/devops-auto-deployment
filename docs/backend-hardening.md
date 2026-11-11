# Backend hardening and supervised collection runbook

This extends [the backend contracts](backend.md). The local API now uses a
restricted database login; migrations and bootstrap administration have separate
protected configuration. The dedicated backend pipeline and supervisor are
independent of the existing demo delivery job.

## Database roles

| Role | Allowed work |
|---|---|
| `release_state` | Local bootstrap, role provisioning, isolated test DB creation and restore administration |
| `release_state_migrator` | Owns the application schema/tables; performs explicit migrations; no superuser/createdb/createrole privileges |
| `release_state_runtime` | Required SELECT/INSERT and specific UPDATE columns; no DDL, database creation, role escalation, audit deletion/rewrites or event-identity updates |

API startup refuses superuser/administrative roles and table owners. Migration
revision metadata is readable but cannot be rewritten by the runtime account.
Audit/observations are append-only to that account. New migration write grants must
be explicitly reviewed; broad default write privileges are not granted. These
rules were tested with actual PostgreSQL permission failures, while the normal
API/import/reconciliation suite still passed.

The grants follow PostgreSQL's [privilege model](https://www.postgresql.org/docs/17/ddl-priv.html)
and [role-specific default privileges](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html).
The current schema is revision `0003_monitoring`, after the recovery and monitoring
migrations. Ownership changes do not replace or reset application data.

For a fresh installation in Ubuntu/WSL, after creating the pinned backend venv:

```sh
PY=/opt/release-lab/backend-venv/bin/python
/opt/release-lab/venv/bin/python -m scripts.backend_runtime setup
$PY -m scripts.provision_backend_roles
export RELEASE_CONFIG_FILE=/opt/release-lab/secrets/backend/config.json
export RELEASE_MIGRATION_CONFIG_FILE=/opt/release-lab/secrets/backend/migration-config.json
export RELEASE_BOOTSTRAP_CONFIG_FILE=/opt/release-lab/secrets/backend/bootstrap-config.json
$PY -m alembic upgrade head
$PY -m scripts.provision_backend_roles
$PY -m scripts.validate_backend
```

Provisioning before migration establishes restricted logins/schema ownership;
provisioning afterward applies the explicit table grants. The existing database
has already completed both steps. Calls are repeatable, preserve credentials and
data, and refuse unexpectedly privileged managed roles. Tests create/drop only
isolated `release_state_test_*` databases using bootstrap credentials. Normal
API/collector services receive neither bootstrap nor migration credentials.

Backup uses the local administrative container connection. Restore creates a new
named database, loads the archive, then reapplies migrator ownership and runtime
grants using `RELEASE_BOOTSTRAP_CONFIG_FILE`. A restore was verified through a
separate API process using the restricted runtime role.

## Supervised services

Start the core lab with `scripts/lab.ps1 -Action start -Profile lean`, start the
backend database, and refresh the scoped observer token before a later session:

```sh
/opt/release-lab/venv/bin/python -m scripts.backend_runtime start
/opt/release-lab/backend-venv/bin/python -m scripts.install_backend_services --refresh-observer-token
systemctl start release-state-api.service release-state-collector.service
systemctl show release-state-api.service release-state-collector.service -p ActiveState -p MainPID -p NRestarts
cat /var/lib/release-observer/status.json
```

Install requires committed backend/frontend code and a matching compiled portal
(`npm ci --prefix frontend --ignore-scripts`, then `npm run build --prefix frontend`).
See [portal operation](portal.md). It copies that snapshot under
`/opt/release-lab/backend-runtime/<SHA>/` and never executes a mutable Windows
working tree. Services use separate non-login users, root-provided systemd
credentials, read-only filesystem protection, no privilege escalation and no
access to `/mnt`, the original secrets directory or the Docker socket. The API
binds loopback 8090. Service installation does not enable boot startup.

`Restart=on-failure`, a three-start/120-second limit and three-second restart delay
bound crash recovery. See [systemd service behavior](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).
The collector polls every 30 seconds with at most three API attempts per cycle
and bounded backoff. An uncertain POST retries the same body/event ID; a version
conflict causes a fresh read and new source snapshot. Authentication failures
terminate rather than being retried indefinitely. Source outages are recorded
without inventing a healthy release; API outages appear in the local status file.

The worker uses a separate read API key and HMAC signing secret, with no database
URL or admin API key. Kubernetes access is limited to pod/service and
Rollout/AnalysisRun reads in `demo-dev` and the single application in `argocd`.
Actual authorization checks denied rollout patches, secret reads, pod creation
and access to another application. The scoped observer manifest is separate from
the workload's environment Git ownership.

**The observer token lasts one hour.** Explicitly refresh it with the installer
before later sessions, then restart the collector to load the new credential.
Expiry/read failure is reported as unavailable. Automatic renewal and migration
to a continuously hosted deployment are future operational work; no long-lived
cluster-admin credential is supplied to the worker.

To stop and preserve state:

```sh
systemctl stop release-state-collector.service release-state-api.service
/opt/release-lab/venv/bin/python -m scripts.backend_runtime stop
```

Stop the core lab separately with `scripts/lab.ps1 -Action stop`. The old
`release-portal-db` on 5433 remains untouched; this backend uses 15432.

## Dedicated backend CI

`ci/Jenkinsfile.backend` configures the manually triggered `backend-gate` job.
It clones a reviewed commit, verifies 23 pinned musl wheel hashes, builds separate
runtime/test targets and runs the full backend suite against an ephemeral isolated
PostgreSQL instance. Bootstrap/migration/test credentials are generated for that
CI run and never supplied from the real backend database. The actual runtime
target must boot under UID 10001 before a blocking Trivy HIGH/CRITICAL scan, an
OS/Python coverage check, CycloneDX SBOM generation and digest publication.

The Docker context is constructed from explicit source/fixture/wheel allowlists.
Credentials, working output and `.git` are excluded. The published runtime target
contains no test fixtures or ephemeral credentials. Runtime and test containers
receive no Docker socket, cluster configuration or real database credentials.
Run containers/networks/anonymous test volumes are labelled and removed in cleanup.
The Jenkins agent itself remains a trusted Docker-socket/root-equivalent lab host;
external PR isolation and remote SCM remain open.

The exact image base and package wheels are pinned in `backend-versions.json`,
`requirements-backend-musl.lock` and `backend-wheel-lock.json`. To obtain the
Linux/musl Python 3.12 wheelhouse from Windows:

```powershell
python -m pip download --no-deps --require-hashes --only-binary=:all: --platform musllinux_1_2_x86_64 --platform musllinux_1_1_x86_64 --python-version 3.12 --implementation cp --abi cp312 -r requirements-backend-musl.lock -d output/backend-musl-wheels
```

The existing CI agent's cache is `/opt/release-backend-wheels`, copied by the
administrator from those verified wheels. Prepare/copy a clean committed source
with `scripts.prepare_merged_source --copy-to-agent`, then configure only the
backend job using `scripts.configure_backend_ci --source-sha <SHA>`. Run
`scripts.run_backend_ci --negative-test` and `scripts.run_backend_ci` serially.
The installer leaves the proven `release-merged` demo job pinned to its own source.

With the managed CI agent running, populate its read-only cache from the downloaded
wheelhouse (CI still verifies every recorded hash):

```sh
docker exec --user 0 release-agent mkdir -p /opt/release-backend-wheels
docker cp output/backend-musl-wheels/. release-agent:/opt/release-backend-wheels/
docker exec --user 0 release-agent chown -R 0:0 /opt/release-backend-wheels
docker exec --user 0 release-agent chmod -R a-w,a+rX /opt/release-backend-wheels
```

Backend CI can run with the cluster and real backend database stopped. Start the
existing Jenkins controller/agent and loopback lab registry, then run the jobs
serially. This keeps their ephemeral PostgreSQL/test containers within the laptop
budget. Stop CI and registry after acceptance; do not remove volumes or snapshots.

For independent receipt generation, run `scripts.record_backend_ci` with the
positive and negative trial folders. It checks actual registry bytes/tag absence,
source labels, runtime UID, scan identity, OS/Python coverage and SBOM contents.
Docker's image ID and the OCI manifest/config digests are retained separately;
the older CI result field `image_config_id` is a Docker image-ID alias, not proof
of the OCI config digest. Use the canonical verifier fields for those identities.

Backend CI publishes an artifact only. It does not update the demo environment
repository or grant CI a controller-observation secret. Automatic producer hooks,
external SCM and broader deployment remain separate work.
