# DevOps auto-deployment

The old-chat implementation and the newer foundation have been merged into this
single Git project, preserving both histories. The canonical application is
`demo/app.py`; `examples/foundation/` is an isolated earlier test fixture, not a
second product. See [merged status and the solo one-week plan](docs/merged-project-status.md).
The earlier 20% assessment is superseded by the combined-work estimate there.
After persistent monitoring and isolated restore acceptance, the current weighted
MVP estimate is approximately **83%**; see [progress and next priorities](docs/progress-after-monitoring.md).

Run the 60 core/demo tests using `python scripts/validate.py` in an environment with
`requirements-validation.txt` installed. Results go to `docs/evidence/merge-validation.json`.
The separate 88-test backend/session/recovery/monitoring suite requires PostgreSQL and the pinned backend
venv; see [permissions, CI and supervised operation](docs/backend-hardening.md).
The November 9 merge passed tests/schema checks but exposed live lab failures.
The laptop recovery session restored controllers, serving telemetry and GitOps
sync, with a lean startup profile. See [laptop work and later migration](docs/laptop-first.md)
for that recovery session. It predates the subsequent CI and runtime acceptance.

The subsequent [CI-to-GitOps milestone](docs/milestones/02-ci-gitops.md) is now complete
for a local manual acceptance run: Jenkins build 8 delivered the reviewed source,
passed the updated vulnerability gate and promoted through Argo. The controlled
passing trial observed 849 HTTP 200 responses. Earlier failed trials are retained.

The [runtime rejection milestone](docs/milestones/03-runtime-failure-validation.md)
extends that proof to HTTP errors, latency, readiness failure, missing traffic and
telemetry outage through actual Jenkins and GitOps. An interrupted observation is
excluded and repeated; pre-promotion rejection is distinguished from the subsequent
post-promotion recovery milestone. The [durable state milestone](docs/milestones/04-durable-state.md)
now adds authenticated APIs, PostgreSQL evidence/audit state, read-only restart
reconciliation and a restore verified through a separate API process.
The [hardening milestone](docs/milestones/05-backend-hardening.md) adds restricted
database roles, scoped and supervised collection, and a dedicated backend CI job
with real test/scan/publication gates. The [portal milestone](docs/milestones/06-real-data-portal.md)
adds authenticated real-data views, evidence history and admin audit access.
Use [the portal runbook](docs/portal.md) to build it and start the local interface
at `http://127.0.0.1:8090/`.

The [recovery milestone](docs/milestones/07-post-promotion-recovery.md) adds sustained
post-promotion error/latency detection, durable incidents, a restricted Git writer
and read-only recovery history. Real serving-error and latency trials restored an
enrolled accepted digest through Git; missing telemetry and worker restart were
also exercised. Earlier clock-invalid attempts remain excluded. See the
[recovery runbook](docs/recovery.md) and [next delivery plan](docs/next-delivery-plan.md).

The [monitoring milestone](docs/milestones/08-persistent-monitoring.md) adds retained
Prometheus storage, versioned alerts, a durable notification outbox and a local
receiver. A real fault/outage/replay trial and an isolated platform restore passed.
See [the monitoring and restore runbook](docs/monitoring.md). Browser visual review,
user interviews and supervisor acceptance remain open.

A self-hosted Kubernetes release platform under development. Jenkins owns builds;
Git owns desired configuration; Argo CD owns synchronization; Argo Rollouts owns
candidate promotion. The recovery worker publishes accepted target configuration
through Git. The custom API records their real state; the React portal displays it.

## Current milestone

This implementation supplies a dependency-free demo service, HTTP integration tests,
a non-root container, a Jenkins pipeline, a rolling-update baseline, blue/green
templates, candidate-specific Prometheus analysis, and a lean k3d lab.
The lean cluster is installed on Ubuntu/WSL 2. Jenkins/Argo CD local integration
is now exercised with real images and controller evidence. External SCM triggers,
fresh-machine reproduction and formal benchmarks remain open. The older
[live validation](docs/live-validation.md) describes the initial experiments.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-validation.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m demo.app
# Another terminal: curl.exe http://127.0.0.1:8080/
```

Create the environment once and reuse it. A project-local `.venv` is recommended
for dependency isolation; it adds negligible RAM overhead. Activation is optional:
`.\.venv\Scripts\Activate.ps1` enables plain `python` commands in PowerShell.
On Linux create it with `python3 -m venv .venv` and use `.venv/bin/python`.
Docker, kubectl, k3d, Jenkins, and Trivy are separate system tools, not pip packages.

`/healthz` and `/readyz` expose probe status; `/metrics`
exposes Prometheus metrics. `DEMO_MODE=error` returns HTTP 500 while probes remain
healthy; `latency` delays application requests; `startup` fails readiness.
Faults are selected at startup or through an opt-in ephemeral pod-local file used
by the controlled post-promotion test injector. There is no HTTP fault activation API.

Start with [the lab runbook](docs/lab.md). See [architecture decisions](docs/architecture.md),
[the delivery backlog](docs/implementation-plan.md), and [validation evidence](docs/validation.md).
Windows users can follow [WSL runtime setup and automated trials](docs/windows-runtime.md).
For a repeatable acceptance walkthrough, follow [testing the current lab](docs/testing-current-lab.md).

| Path | Purpose |
|---|---|
| `demo/` | Controlled good/faulty application and Dockerfile |
| `ci/Jenkinsfile` | Test, build, scan, push, resolve digest, update environment Git |
| `platform/` | Lightweight monitoring and Argo CD application template |
| `templates/` | GitOps release resources and rolling baseline |
| `scripts/` | Lab bootstrap, digest-only rendering, load/evidence client |
| `tests/` | HTTP behavior, fault isolation, rendering validation |
| `versions.json` | Component pins; compatibility needs live validation |

No subscription or cloud account is required for the lab. Docker/k3d need a Linux
container runtime. The current Windows host has about 8 GiB RAM: start with the lean
single-node profile for routine work and the full profile for serial trusted-lab
CI trials. A separate isolated build host remains later work. PostgreSQL and the
product API now run with restricted roles and supervised local services. The
post-promotion recovery, persistent monitoring, local notifications and a quiesced
platform restore are accepted locally. Independent-machine reproduction follows.

The installed Windows lab can be managed from PowerShell:

```powershell
.\scripts\lab.ps1 -Action start
.\scripts\lab.ps1 -Action review
.\scripts\lab.ps1 -Action status
.\scripts\lab.ps1 -Action stop
```

Use `bootstrap` only on a fresh lab; it deliberately refuses to replace an existing
cluster. Start/stop preserve the existing cluster and manage a WSL keepalive helper.
`review` opens loopback access to the sample app (8081), native Rollouts dashboard
(3100/rollouts/), and Prometheus (9090). See [the current review and gap list](docs/current-review.md).
