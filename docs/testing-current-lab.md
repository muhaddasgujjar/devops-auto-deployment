# Test the current lab

Run these commands in PowerShell from the project root. The existing lab already
has a stable release; do not bootstrap it again or run the `initial` scenario.
Run trials one at a time and let each command finish before starting another.

## 1. Check application behavior and manifests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.validate_manifests
```

Expected: 12 tests pass and 18 resource/config documents validate. Schema checking
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
.\scripts\lab.ps1 -Action trial -Scenario healthy
```

This builds, scans and publishes a fresh image, deploys a candidate, generates test
traffic and records independent stable-service responses. Allow several minutes.
Expected: `verdict: candidate-promoted`, `stable_non_200: 0`, successful analysis,
and a new stable/active revision. Refresh the application page to see its revision.

## 4. Prove an HTTP regression is rejected

```powershell
.\scripts\lab.ps1 -Action trial -Scenario error
```

Expected: `verdict: candidate-rejected`, `stable_non_200: 0`, failed candidate
analysis, and the previous healthy revision still serving the application URL.
A degraded candidate is the intended outcome of this experiment, even when
Kubernetes probes pass. Do not manually promote it in the dashboard.

The same command supports `latency` (reject), `startup` (readiness abort),
`no-traffic` (inconclusive), and `telemetry-outage` (promotion blocked; the runner
restores Prometheus afterward). The stronger target-count/freshness policy has
been exercised with healthy promotion and direct live Prometheus expression
checks; rerun the fault scenarios to extend that policy's evidence.

## 5. Inspect evidence and finish healthy

After each trial, inspect its timestamped `output/trial-SCENARIO-TIMESTAMP` folder.
For the latest trial:

```powershell
$latestTrial = Get-ChildItem .\output -Directory -Filter 'trial-*' |
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
.\scripts\lab.ps1 -Action trial -Scenario healthy
.\scripts\lab.ps1 -Action status
```

When finished, `scripts/lab.ps1 -Action stop` closes browser forwarding and stops
the cluster while preserving its state. Evidence, tools, kubeconfig and virtual
environments remain local and are excluded from Git. These tests cover the local
release engine; Jenkins execution and Argo CD reconciliation remain future tests.
