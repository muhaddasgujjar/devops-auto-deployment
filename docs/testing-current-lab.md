# Test the current lab

The serial CI/GitOps failure suite is described in
[the fault-matrix runbook](gitops-fault-matrix.md). It includes controlled missing
traffic and monitoring outages, plus explicit retry after a shared dependency
prevents recovery verification.

Run these commands in PowerShell from the project root. The existing lab already
has a stable release; do not bootstrap it again or run the `initial` scenario.
Run trials one at a time and let each command finish before starting another.
After GitOps adoption, use the Jenkins-driven commands below. The old `trial`
action is only for an isolated lab before Argo CD owns the workload.

## 1. Check application behavior and manifests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.validate_manifests
```

Expected: 28 tests pass and 21 resource/config documents validate. Schema checking
can take a few minutes. These checks do not deploy or change the running lab.

## 2. Check the running system

```powershell
.\scripts\lab.ps1 -Action start
.\scripts\lab.ps1 -Action review
.\scripts\lab.ps1 -Action status
Invoke-RestMethod http://localhost:8081/
```

Expected: health report `ok: true`, node Ready without memory/disk pressure,
Rollouts and Prometheus available, a healthy application response, and two fresh
serving-revision targets. The report is written to `output/current-health.json`.

Open http://localhost:3100/rollouts/ and select `demo-dev` / `release-demo`.
Prometheus is at http://localhost:9090/; execute
`up{job="demo-pods",namespace="demo-dev"}` to see target health and revision labels.
During a deployment, stable and candidate targets can both appear.

## 3. Prove a healthy candidate can receive traffic

```powershell
.\scripts\lab.ps1 -Action gitops-trial -Scenario healthy
```

This builds, scans and publishes a fresh image, deploys a candidate, generates test
traffic and records independent stable-service responses. Allow several minutes.
Expected: `verdict: candidate-promoted-through-gitops`, `stable_non_200: 0`, successful analysis,
and a new stable/active revision. Refresh the application page to see its revision.

## 4. Prove an HTTP regression is rejected

```powershell
.\scripts\lab.ps1 -Action gitops-trial -Scenario error
```

Expected: `verdict: candidate-rejected-and-restored-through-gitops`, `stable_non_200: 0`, failed candidate
analysis, and the previous healthy revision still serving the application URL.
A degraded candidate is the intended outcome of this experiment, even when
Kubernetes probes pass. Do not manually promote it in the dashboard.

The GitOps command also supports `latency` (reject) and `startup` (readiness abort).
The earlier isolated engine runner additionally supports `no-traffic` and
`telemetry-outage`; it must not be used to bypass GitOps ownership. Equivalent
Jenkins-driven experiments for those two conditions remain pending.

## 5. Inspect evidence and finish healthy

After each trial, inspect its timestamped `output/gitops-SCENARIO-TIMESTAMP` folder.
For the latest trial:

```powershell
$latestTrial = Get-ChildItem .\output -Directory -Filter 'gitops-*' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content (Join-Path $latestTrial.FullName 'summary.json')
```

Check the expected verdict and zero stable failures. Raw response observations,
AnalysisRuns, service selectors, source hashes, image digest, vulnerability scan
and SBOM are retained alongside the summary. A nonzero exit, `trial-failed`, or
nonzero stable failure count needs investigation; a controller decision alone
does not prove the application's availability.

After fault experiments, return to a healthy desired release:

```powershell
.\scripts\lab.ps1 -Action gitops-trial -Scenario healthy
.\scripts\lab.ps1 -Action status
```

When finished, `scripts/lab.ps1 -Action stop` closes browser forwarding and stops
the cluster while preserving its state. Evidence, tools, kubeconfig and virtual
environments remain local and are excluded from Git. See [CI/GitOps scope and
acceptance evidence](ci-gitops.md) for local integration versus remote deployment.
