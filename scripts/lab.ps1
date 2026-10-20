param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('install', 'bootstrap', 'status', 'start', 'stop', 'trial', 'review', 'close-review')]
    [string]$Action,
    [ValidateSet('initial', 'healthy', 'error', 'latency', 'startup', 'no-traffic', 'telemetry-outage')]
    [string]$Scenario = 'initial'
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$wslArguments = @('--distribution', 'Ubuntu-24.04', '--user', 'root', '--cd', $projectPath, '--exec')
$keeperFile = Join-Path $projectPath 'output\runtime-keeper.json'
function Get-LabKeeper {
    if (Test-Path -LiteralPath $keeperFile) {
        $record = Get-Content -LiteralPath $keeperFile -Raw | ConvertFrom-Json
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$record.pid)" -ErrorAction SilentlyContinue
        if ($process.Name -eq 'wsl.exe' -and $process.CommandLine -match '--distribution Ubuntu-24\.04 --user root --exec sleep infinity') {
            return $process
        }
    }
    return $null
}
function Enable-LabKeeper {
    if (-not (Get-LabKeeper)) {
        New-Item -ItemType Directory -Path (Join-Path $projectPath 'output') -Force | Out-Null
        $keeper = Start-Process -FilePath (Join-Path $env:WINDIR 'System32\wsl.exe') -ArgumentList @('--distribution', 'Ubuntu-24.04', '--user', 'root', '--exec', 'sleep', 'infinity') -WindowStyle Hidden -PassThru
        @{pid = $keeper.Id; purpose = 'Keep the dedicated WSL lab active between commands'} | ConvertTo-Json | Set-Content -LiteralPath $keeperFile
    }
}
if ($Action -in @('bootstrap', 'start', 'trial', 'review')) { Enable-LabKeeper }
switch ($Action) {
    'install' { & wsl @wslArguments bash scripts/install-linux-tools.sh }
    'bootstrap' { & wsl @wslArguments bash scripts/bootstrap-lab.sh }
    'status' {
        & wsl @wslArguments /opt/release-lab/venv/bin/python -m scripts.doctor --output output/current-health.json
    }
    'start' {
        & wsl @wslArguments k3d cluster start release-lab
        if ($LASTEXITCODE -ne 0) { throw 'Cluster start failed' }
        & wsl @wslArguments bash -c 'export KUBECONFIG="$PWD/output/lab.kubeconfig"; set -e; kubectl wait --for=condition=Ready node --all --timeout=120s; kubectl rollout status deployment/argo-rollouts -n argo-rollouts --timeout=120s; kubectl rollout status deployment/prometheus -n monitoring --timeout=120s'
    }
    'stop' {
        & wsl @wslArguments /opt/release-lab/venv/bin/python -m scripts.review --stop
        & wsl @wslArguments k3d cluster stop release-lab
        $stopExitCode = $LASTEXITCODE
        $keeper = Get-LabKeeper
        if ($keeper) { Stop-Process -Id $keeper.ProcessId }
        if ($stopExitCode -ne 0) { throw "Cluster stop failed with exit code $stopExitCode" }
    }
    'review' {
        $reviewState = (& wsl @wslArguments /opt/release-lab/venv/bin/python -m scripts.review --status | Out-String) | ConvertFrom-Json
        if (-not $reviewState.running) {
            $launchArguments = @('--distribution', 'Ubuntu-24.04', '--user', 'root', '--cd', ('"' + $projectPath + '"'), '--exec', '/opt/release-lab/venv/bin/python', '-m', 'scripts.review')
            Start-Process -FilePath (Join-Path $env:WINDIR 'System32\wsl.exe') -ArgumentList $launchArguments -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectPath 'output/review-supervisor.log') -RedirectStandardError (Join-Path $projectPath 'output/review-supervisor-error.log') | Out-Null
        }
        foreach ($url in @('http://localhost:8081/', 'http://localhost:9090/-/ready', 'http://localhost:3100/rollouts/')) {
            $ready = $false
            for ($attempt = 0; $attempt -lt 15; $attempt++) {
                try { $null = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing; $ready = $true; break } catch { Start-Sleep -Seconds 1 }
            }
            if (-not $ready) { throw "Review endpoint unavailable: $url; inspect output/review-*.log" }
        }
        & wsl @wslArguments /opt/release-lab/venv/bin/python -m scripts.review --status
    }
    'close-review' { & wsl @wslArguments /opt/release-lab/venv/bin/python -m scripts.review --stop }
    'trial' {
        $trialOutput = 'output/trial-' + $Scenario + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
        & wsl @wslArguments bash -c 'export KUBECONFIG="$PWD/output/lab.kubeconfig"; exec /opt/release-lab/venv/bin/python -m scripts.live_trial "$@"' -- $Scenario --output $trialOutput
    }
}
if ($LASTEXITCODE -ne 0) { throw "Lab command failed with exit code $LASTEXITCODE" }
