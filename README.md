# DevOps auto-deployment

A self-hosted Kubernetes release platform under development. Jenkins owns builds;
Git owns desired configuration; Argo CD owns synchronization; Argo Rollouts owns
candidate promotion. The custom API and UI follow a measured recovery experiment.

## Current milestone

This implementation supplies a dependency-free demo service, HTTP integration tests,
a non-root container, a Jenkins pipeline, a rolling-update baseline, blue/green
templates, candidate-specific Prometheus analysis, and a lean k3d lab.
The lean cluster is installed on Ubuntu/WSL 2 and has been exercised with real
images and controller trials. A bounded local Jenkins/Argo CD integration profile
is available; see [CI and GitOps setup](docs/ci-gitops.md) for its acceptance evidence
and remaining remote-host requirements. See [engine validation](docs/live-validation.md)
for the earlier controlled trials. Formal repeated benchmarks remain pending.
Persistent monitoring, immutable release evidence and backup/restore verification
are described in [the persistence runbook](docs/persistence.md).
Scheduled GitHub-source delivery and HTTP-error rejection now pass through the
real pipeline; see [the acceptance record](docs/scm-validation.md) for measured
observations and remaining limits.

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
Faults are selected at startup with no public mutation API.

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
single-node profile. The current local Jenkins controller and trusted agent have
bounded memory; a separate build host remains the team deployment target. PostgreSQL,
the portal, and full monitoring are later milestones.

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
