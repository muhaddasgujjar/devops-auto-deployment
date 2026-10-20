# Windows runtime setup

The lab uses Ubuntu 24.04 on WSL 2 with Docker Engine.
Python dependencies remain in each operating system's own `.venv`; a Windows
venv cannot be used as a Linux venv.
The installed Linux environment is `/opt/release-lab/venv`; the Windows `.venv`
remains in the project directory. Both contain `requirements-validation.txt`.

## Host configuration

The initial host has 8 GiB of RAM. Its newly created `%USERPROFILE%\.wslconfig`
caps WSL at 3 GiB, four processors, and 2 GiB swap; GUI applications are disabled
and gradual memory reclamation is enabled. This is a cap, not a reservation.
Existing applications were not closed. Memory pressure may still prevent a trial;
check available memory before starting the lab. Jenkins stays outside this host.

WSL 2.7.11 and the Linux kernel were already installed. Ubuntu installation:

```powershell
wsl --install --distribution Ubuntu-24.04 --no-launch --web-download
```

If Windows requests administrator approval or a restart, complete that Windows
step before continuing; the agent cannot supply administrator credentials or
restart the user's session. Check registration with `wsl --list --verbose`.

## Install Linux tools

Open Ubuntu, navigate to this project, and run:

```bash
sudo bash scripts/install-linux-tools.sh
```

The installer is for a dedicated Ubuntu 24.04 amd64 lab. It configures Docker's
signed Apt repository and installs Docker Engine/CLI/Buildx, Python/venv, Git,
and curl. It installs pinned kubectl, k3d, and Trivy binaries only after checking
their SHA-256 hashes against upstream checksum files. Actual Docker Apt package
versions and checksum files are retained in ignored `output/install/`.
It starts Docker but does not grant Docker group membership to existing users.

Prefer a project checkout on the Linux filesystem for sustained builds. Windows
OneDrive paths are usable for the first test but introduce filesystem overhead.
Do not copy the Windows `.venv`; create a separate Linux environment if needed.

## Bootstrap and trial

Use a root shell on the dedicated lab for these Docker operations, or configure
an appropriate Docker execution policy yourself. No Windows administrator access
is needed to enter an already installed WSL distribution as its Linux root user.

```bash
sudo bash scripts/bootstrap-lab.sh
export KUBECONFIG="$PWD/output/lab.kubeconfig"
sudo --preserve-env=KUBECONFIG python3 -m scripts.live_trial initial --output output/trial-initial-1
sudo --preserve-env=KUBECONFIG python3 -m scripts.live_trial healthy --output output/trial-healthy-1
sudo --preserve-env=KUBECONFIG python3 -m scripts.live_trial error --output output/trial-error-1
```

Repeat for `latency`, `startup`, `no-traffic`, and `telemetry-outage`. Use a fresh
output directory each time. The initial trial establishes a stable revision;
subsequent trials require a verified healthy stable service. The runner refuses
other Kubernetes contexts and workloads already marked as owned by Argo CD.

Each trial builds an artifact, requires a passing high/critical vulnerability scan,
records its SBOM, pushes its immutable digest, applies a rendered release,
generates preview traffic except where intentionally absent, monitors stable
responses through a local Kubernetes service proxy, and captures source hashes,
Rollout/AnalysisRun/pod/service/event JSON plus an outcome summary. The proxy
resolves service endpoints per request; it avoids binding the whole experiment
to one pod as `port-forward service/...` would. These are lab-path measurements,
not production ingress or network availability claims.

The telemetry outage case restores Prometheus to one replica in cleanup. After
an inconclusive trial, a fresh trial uses a new pod-template revision. Original
Git HEAD and dirty-worktree state are recorded alongside file hashes, since
uncommitted local source is not represented by HEAD alone.

Read each trial's `summary.json`; a controller decision alone does not prove stable
availability. Investigate any non-200 stable responses. Scanning, Jenkins/GitOps
integration, and repeated benchmarks have separate evidence and acceptance gates.
The first Debian-based images failed the scan. The selected Alpine-based runtime
contains no third-party application dependencies and omits unused Python build
tools; the original failed reports remain in `output/` for comparison.

## PowerShell shortcut

From the project root, the launcher runs commands inside the dedicated Ubuntu
distribution with its Linux tools and venv:

```powershell
.\scripts\lab.ps1 -Action status
.\scripts\lab.ps1 -Action bootstrap
.\scripts\lab.ps1 -Action trial -Scenario initial
.\scripts\lab.ps1 -Action trial -Scenario error
.\scripts\lab.ps1 -Action stop
.\scripts\lab.ps1 -Action start
.\scripts\lab.ps1 -Action review
.\scripts\lab.ps1 -Action close-review
```

Bootstrap, start, trial, and review create or reuse a small hidden `wsl.exe sleep infinity`
process recorded in `output/runtime-keeper.json`. WSL systemd services alone did
not keep this distribution alive between commands during testing. Stop terminates
only the helper whose PID and command line match this project record. The helper
does not reserve a separate memory pool; it keeps the distribution's services alive.

`review` verifies HTTP access from Windows to `http://localhost:8081/`,
`http://localhost:3100/rollouts/`, and `http://localhost:9090/`. It supervises
loopback-only Linux forwards and the checksum-verified native Rollouts CLI dashboard.
On an existing installation, install the matching CLI with
`wsl -d Ubuntu-24.04 -u root --exec bash scripts/install-review-tools.sh` from the
project directory. The main Linux installer includes it on fresh installations.
The dashboard uses the dedicated lab kubeconfig and exposes its administrative
controls to the local user. It is an operations interface; the custom portal is pending.

The supervisor restarts forwards after a child exits and reconnects the sample
forward when the stable service revision changes (checked approximately every
five seconds). A reconnect can briefly interrupt browser requests. Experiments
continue to use the independent per-request service proxy for availability evidence.
`close-review` closes only this project's supervised interfaces. `stop` closes
them before stopping the cluster. Process ownership includes Linux PID start time.
Logs and process records are in ignored `output/review*` files.

`status` now checks node readiness/pressure, both controllers, an actual healthy
stable-service response, and exactly two fresh serving-revision scrape targets.
It writes `output/current-health.json` and returns a failing exit code on failed
checks. Candidate degradation is reported separately from stable-service health.
Run status after startup; controller readiness alone does not prove application health.

Stopping the cluster preserves its state. To reclaim all WSL runtime memory after
finishing experiments, stop the lab first and use `wsl --terminate Ubuntu-24.04`.
This ends running processes in that distribution, so save any Linux work first.

## Compare against probes alone

After a healthy and HTTP-error trial have produced scanned image records, use
their actual output directory names in Ubuntu:

```bash
export KUBECONFIG="$PWD/output/lab.kubeconfig"
/opt/release-lab/venv/bin/python -m scripts.compare_baseline \
  --healthy-trial output/trial-healthy-TIMESTAMP \
  --error-trial output/trial-error-TIMESTAMP \
  --output output/baseline-comparison-1
```

This uses a separate `demo-baseline` Deployment, records thirty responses per
image, checks Deployment availability, then scales that Deployment to zero.
It demonstrates why passing probes alone can accept an HTTP 500 regression.
