# Run and demonstrate the project

Use the existing laptop lab for the complete demonstration on **13 November 2026**.
Allow setup time before the meeting. A fresh clone contains source and public
evidence, but no running cluster, database, credentials, images or compiled portal.

## Download

```sh
git clone https://github.com/muhaddasgujjar/devops-auto-deployment.git
cd devops-auto-deployment
```

Use `main` for the current canonical project. Save local changes before switching
branches in an existing checkout; never reset a working lab to perform an update.

## Quick application check on Windows or Linux

With Python installed, run:

```sh
python -m demo.app
```

Open `http://127.0.0.1:8080/`, `/healthz` and `/metrics` on that same address.
Expect healthy HTTP responses and text measurements. Ctrl+C stops it. This is
the small workload used to test releases, **not the dashboard or full platform**.

Run the 60 core tests in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-validation.txt
.\.venv\Scripts\python.exe -m scripts.validate
```

On Linux use `.venv/bin/python` instead. Backend integration tests are separate
and need the configured PostgreSQL lab. Manifest validation needs upstream
schemas/internet on first use.

## Start the existing laptop lab

Run PowerShell in the **original project folder**. Do not bootstrap or run an
initial deployment again: the cluster and private state already exist.

```powershell
.\scripts\lab.ps1 -Action start -Profile lean
.\scripts\lab.ps1 -Action review
.\scripts\lab.ps1 -Action status
```

Expect healthy controllers and a responding application. Review provides the
application at `http://127.0.0.1:8081/`, Rollouts at
`http://127.0.0.1:3100/rollouts/` and Prometheus at `http://127.0.0.1:9090/`.
If startup fails, inspect its logs/readiness; do not recreate the lab.

In a root Ubuntu/WSL terminal **at this checkout**, start the product services:

```sh
/opt/release-lab/venv/bin/python -m scripts.backend_runtime start
/opt/release-lab/backend-venv/bin/python -m scripts.install_backend_services --refresh-observer-token --refresh-recovery-token --refresh-notifier-token
systemctl start release-state-api release-state-collector release-notification-receiver release-state-notifier
systemctl is-active release-state-api release-state-collector release-notification-receiver release-state-notifier
```

The installer needs a matching compiled portal, already retained on the laptop.
If missing/mismatched, follow [portal build instructions](portal.md). Services use
committed snapshots. Tokens last one hour; refresh and restart workers for later
sessions. Keep recovery stopped for a read-only presentation; start it explicitly
only for a planned recovery experiment.

Open `http://127.0.0.1:8090/`. Use the existing **read** key. The authorized owner
can retrieve only this key in the private WSL shell before screen sharing:

```sh
/opt/release-lab/backend-venv/bin/python -c 'import json; print(json.load(open("/opt/release-lab/secrets/backend/tokens.json"))["read"])'
```

Keep the key out of slides, screenshots and Git. There is no public default login.
Wait roughly one collector cycle for fresh observations. Stale/unavailable data
and expired credentials must not be presented as healthy live evidence.

## Five-minute presentation

1. Explain: “We test an update before replacing the working application.”
2. Show the application and desired/serving versions in the portal. Point out
   observation freshness: current, stale or unavailable.
3. Open successful and rejected release records. Building successfully does not
   automatically mean the version is approved to serve users.
4. Show recovery history, including failed/excluded experiments with their labels.
   Do not describe a historical recovery as happening now.
5. Show monitoring alerts and delivered notices. An alert and its delivery are
   different records. Notifications currently use a local inbox, not email/SMS.
6. Present [the short report](simple-project-report.md) and
   [restore result](evidence/platform-restore.json). Explain the remaining 17%.

The latest accepted monitoring trial used origin build 22. Saved public receipts
are under `docs/evidence/`; private raw logs remain under ignored `output/`.

## Optional live delivery experiment

Only run this after the walkthrough works and sufficient time/memory is available.
In root WSL at the checkout:

```sh
docker start registry.localhost
/opt/release-lab/venv/bin/python -m scripts.integration_runtime start --profile full
/opt/release-lab/venv/bin/python -m scripts.gitops_trial healthy --job release-merged
/opt/release-lab/venv/bin/python -m scripts.gitops_trial error --job release-merged
/opt/release-lab/venv/bin/python -m scripts.gitops_trial healthy --job release-merged
```

Run serially. Expect healthy promotion, rejection of the faulty candidate while
the old stable version serves, then a final healthy desired release. Check each
actual summary, controller decision and stable HTTP response stream. A failure
needs investigation. The 8 GB laptop can experience memory pressure; earlier
acceptance serialized builds against cluster-heavy checks. No duration is promised.
Do not use the old manual `trial` command on an Argo-managed workload.

## Stop and preserve

In root WSL:

```sh
systemctl stop release-state-notifier release-notification-receiver release-state-recovery release-state-collector release-state-api
/opt/release-lab/venv/bin/python -m scripts.backend_runtime stop
```

Then PowerShell: `.\scripts\lab.ps1 -Action stop`. Stop the owned registry if
started. Preserve data/volumes/backups and leave unrelated services alone.

For another computer follow [fresh-machine setup](machine-transfer.md) and
[acceptance checks](target-machine-acceptance.md). Full operation needs dedicated
Ubuntu 24.04 amd64/WSL, Linux Docker, internet downloads, new credentials and
initial configuration. A clone alone is not a full installation. Old live database
state must not silently adopt new controller identities or build sequences.
