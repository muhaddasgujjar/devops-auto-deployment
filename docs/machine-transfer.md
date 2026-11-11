# Transfer the single merged project

Milestone 9 prepares transfer on the laptop. It does not claim that the other
machine has been inspected or that independent installation has passed. The MVP
estimate remains **83%**. Human validation and visual review remain open in the
[pilot worksheet](pilot-and-scope-review.md).

## Portable source

From a clean committed checkout, run with Python 3.11+ and Git:

```powershell
python -m scripts.export_transfer
```

The command creates `output/transfer/<full-source-SHA>/release-platform.bundle`
and `transfer.json`, refuses overwrites, verifies the bundle and performs a real
independent clone/fsck/tree comparison. All Git refs and their reachable history
are included, preserving both merged project histories. Ignored files and working
runtime data are excluded. This is not an offline dependency package. Keep the
receipt beside the bundle and compare its SHA-256 after copying:

```powershell
Get-FileHash .\release-platform.bundle -Algorithm SHA256
git clone --branch codex/foundation-baseline .\release-platform.bundle release-platform
cd release-platform
git fsck --full
git rev-parse HEAD
```

Compare HEAD with `source_commit` in the receipt. A bundle clone's origin points
to the copied bundle; it is not a hosted remote. No GitHub URL is configured or
published. If a hosted remote is chosen later, configure it explicitly then.

## Inventory before installation

Run `python -m scripts.machine_inventory --output output/target-inventory.json`
on the other machine, and again inside its intended Linux/WSL runtime. It reads
OS/architecture, visible host RAM, logical CPUs, checkout disk free space and
tool versions/daemon availability. It starts no services. Missing tools are
reported; an inventory is not an installation pass. It does not collect passwords,
Docker environment variables, Kubernetes config or machine/user names.

Check Ubuntu 24.04 amd64, Python 3.12 for the host backend, systemd PID 1, working
Linux Docker, clock agreement with the host and capacity for the chosen profile.
The installers and wheel locks currently target amd64, not ARM. GPU VRAM does not
replace system RAM. The laptop's successful serialized trials are not a peak RAM
estimate for concurrent builds. Begin serially; measure pressure before concurrency.
Reserve disk for image layers, builds, TSDB and backups in addition to source.
Record actual capacity and chosen resource limits in the target worksheet.

Compare tools with `versions.json`, backend images/security package with
`backend-versions.json`, Python locks with `requirements-backend-lock.txt` and
`requirements-backend-musl.lock`, and frontend dependencies with its npm lock.
Some infrastructure images are tag pinned rather than fully digest locked;
complete infrastructure digest enforcement remains open. Do not describe this
handoff as a complete supply-chain lock.

## Fresh installation order

Use a dedicated Linux lab, preferably a checkout on its Linux filesystem. Do not
copy Windows venvs. Commands below require the dedicated Linux administrator.
Inspect occupied ports before creating services: 2222 Git, 5001 registry, 6445
Kubernetes, 8082 Jenkins, 8090 API, 8092 receiver and 15432 PostgreSQL. Preview 8093
and review forwards are optional. Preserve unrelated services; resolve collisions
by reviewed configuration rather than killing unknown processes.

1. Follow [Windows/WSL tool setup](windows-runtime.md) or the dedicated Ubuntu
   installer `sudo bash scripts/install-linux-tools.sh`. It creates the validation
   venv at `/opt/release-lab/venv`. Internet access is needed for pinned tools,
   packages, images, manifests and vulnerability data. Recheck the inventory.
2. Run `sudo bash scripts/bootstrap-lab.sh` only on a fresh lab. It refuses an
   existing `release-lab`. Export `KUBECONFIG=$PWD/output/lab.kubeconfig`. Check
   controllers, Bound `monitoring/prometheus-data`, Retain policy and Prometheus
   readiness. For an existing lab use the guarded monitoring installer instead.
3. Establish the initial healthy workload, scoped environment Git/SSH transport,
   Argo CD adoption and trusted Jenkins using [the lab](lab.md),
   [GitOps ownership](ci-gitops.md) and [CI milestone](milestones/02-ci-gitops.md).
   Create fresh machine-local keys, host trust and Jenkins credentials. Use
   `prepare_merged_source --copy-to-agent` and configure both jobs to the reviewed
   target commit. Verify the backend gate and demo pipeline separately. The agent
   has trusted Docker access; untrusted external PR builds are not yet isolated.
   Backend CI also requires its wheel cache: download the existing hash-locked
   musl wheels, then copy them to the agent as in [backend CI](backend-hardening.md):

   ```sh
   python3 -m pip download --only-binary=:all: --require-hashes --platform musllinux_1_2_x86_64 --python-version 3.12 --implementation cp --abi cp312 -r requirements-backend-musl.lock -d output/backend-musl-wheels
   ```

   Do not regenerate `backend-wheel-lock.json` to make a mismatched download pass.
4. Create the backend venv and a new empty database with restricted roles:

   ```sh
   python3 -m venv /opt/release-lab/backend-venv
   PY=/opt/release-lab/backend-venv/bin/python
   $PY -m pip install -r requirements-backend-lock.txt
   /opt/release-lab/venv/bin/python -m scripts.backend_runtime setup
   $PY -m scripts.provision_backend_roles
   export RELEASE_CONFIG_FILE=/opt/release-lab/secrets/backend/config.json
   export RELEASE_MIGRATION_CONFIG_FILE=/opt/release-lab/secrets/backend/migration-config.json
   export RELEASE_BOOTSTRAP_CONFIG_FILE=/opt/release-lab/secrets/backend/bootstrap-config.json
   $PY -m alembic upgrade head
   $PY -m scripts.provision_backend_roles
   $PY -m scripts.validate_backend
   ```

   Fresh installation upgrades directly to `0003_monitoring`. The populated
   M7/M8 rehearsal scripts expect specific older revisions; do not run those
   one-time upgrades on a fresh database already at head.
5. Build the portal with the pinned Node image or matching Node toolchain, using
   `npm ci --prefix frontend --ignore-scripts`, `npm test --prefix frontend`
   and `npm run build --prefix frontend`. Check [portal operation](portal.md).
   Install services using the three refresh flags in [monitoring](monitoring.md).
   Start API/collector/receiver/notifier first and verify permissions and freshness.
   Start recovery only after a valid accepted target has been enrolled. Service
   tokens expire in one hour; refresh/restart for later sessions. No automatic
   boot enablement or automatic token renewal is claimed.
6. Complete [target acceptance](target-machine-acceptance.md). Retain failures and
   raw evidence from that machine. Do not reuse laptop receipts as new-run results.

## Archive verification versus continuing old state

Keep the private laptop platform bundle outside Git. Its location and file hashes
are recorded in [the backup receipt](evidence/platform-backup.json). It contains
operational history and is not part of the source bundle. Transfer it separately
using a private channel/storage. Runtime keys are excluded and must be recreated.
The archived images/registry, Jenkins home, raw trial output and OS provisioning
are also outside the source bundle; rebuild or transfer those explicitly if needed.

The laptop ledger binds observations to a Kubernetes Rollout UID and build ordering.
A new cluster and new Jenkins sequence must **not** silently continue that ledger.
Start fresh state for new operation. Historical import is explicitly historical,
not evidence of a live serving deployment. Never reset ordering or edit old IDs
to make acceptance pass. Continuing the old live ledger needs an explicit,
reviewed controller-identity/build-sequence migration, which is not implemented.

The current platform restore command verifies an archive in an isolated target
while preserving an already initialized source lab; it is not a bare-machine
installer or a live-ledger migration. Restored database role/password handling
must use the destination's own protected credentials. Consult
[restore boundaries](monitoring.md) before running it on the other machine.

Recovery target enrollment also remains explicit. The current recorder relies
on preserved healthy runtime-trial artifacts under `output/`, which the Git bundle
does not include. A fresh healthy CI observation alone is not an accepted target.
Produce and validate new target evidence, or implement a reviewed generic target
enrollment path before claiming fresh-machine automated recovery acceptance.

## Stop and preserve

Stop all five backend services, then the labelled backend DB, CI and owned k3d
nodes/registry as in [monitoring shutdown](monitoring.md). Preserve volumes and
private backups. Do not shut down unrelated databases or delete a cluster to fix
an installation error. Keep the laptop reference intact until reproduction passes.
