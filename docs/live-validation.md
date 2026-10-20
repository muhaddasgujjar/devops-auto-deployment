# Live cluster validation - 20 October 2026

This is a local lab experiment on the existing 8 GiB Windows machine, not a
production availability or recovery guarantee. Raw trial artifacts are in ignored
`output/trial-*/` and `output/baseline-*/`. They contain source hashes, source HEAD
plus dirty-worktree status, image digest, scan/SBOM, desired manifests, Kubernetes
resources, timestamped responses, and summary JSON. No remote Git push was made.

## Installed runtime

- Ubuntu 24.04.5 LTS on the pre-existing WSL 2.7.11 installation.
- WSL cap: 3 GiB memory, four processors, 2 GiB swap, gradual reclamation.
- Docker Engine/CLI 29.9.1, Buildx 0.38.0, host containerd 2.4.2.
- k3d 5.9.0 and single-node k3s 1.35.9+k3s1.
- kubectl 1.35.9, Argo Rollouts 1.10.1, Prometheus 3.15.0, Trivy 0.76.0.
- Linux Python dependencies isolated in `/opt/release-lab/venv`; Windows `.venv`
  remains intact. Twelve HTTP/rendering tests and eighteen schema checks passed
  in both environments.

Tool checksums and actual Apt versions are retained in `output/install/`.
The image was tested as UID 10001, read-only root filesystem, dropped capabilities,
and no privilege escalation. Kubernetes successfully pulled application images
through the lab registry. Prometheus discovered both application pods with their
candidate-specific revision label.

## Security findings and remediation

The original Python 3.14.3 Debian runtime failed scanning: 113 high and six critical
package findings. Updating to the current Debian Python runtime removed critical
findings but still left 48 high findings, including packages without listed fixes.
No ignore list or severity relaxation was introduced.

The dependency-free demo now uses Python 3.14.8 on Alpine 3.24, pinned by manifest
digest in the Dockerfile and `versions.json`. Unused pip/setuptools/wheel runtime
build tools are removed. The selected image reports Alpine 3.24.2 and **zero high
or critical findings** in the captured Trivy scan. Each subsequent trial scans its
actual artifact and records its SBOM before publishing. This is a dated scanner
result, not proof of absence of all vulnerabilities or an infrastructure audit.

## Trials

Controller and availability outcomes are recorded separately. A run is rejected by
the trial harness if any observed stable request fails, even if the controller
correctly promotes or aborts. The service proxy is an independent client path
through the Kubernetes API; it is not production ingress or an external-network
availability measurement. Initial preview 503 responses during pod startup are
recorded but do not count as stable-service failures.

| Scenario | Controller result | Decision interval | Stable requests / failures |
|---|---|---:|---:|
| Healthy candidate | Promoted after passing both metrics | 135.9 s | 612 / 0 |
| HTTP 500 candidate, healthy probes | Failed analysis; candidate rejected | 68.3 s | 307 / 0 |
| Latency candidate, healthy probes | Failed analysis; candidate rejected | 67.6 s | 308 / 0 |
| Insufficient candidate traffic | Inconclusive; no promotion | 103.4 s | 428 / 0 |
| Prometheus scaled to zero | Analysis error; no promotion; telemetry restored | 94.2 s | 411 / 0 |
| Unready candidate after history workaround | Automatically aborted | 205.0 s | 917 / 0 |

These successful runs observed **2,983 stable requests with no failures**. This is
a finite set of local checks, not an availability SLO. The earlier pilot failure is
retained below. Each interval runs from the harness's release-start timestamp to
its observed controller decision; image build/scan/push and queue time are excluded.
The readiness deadline measures lack of progress, not absolute release duration:
old-set cleanup advanced the progress timestamp before the 180-second timer ran.

The separate `demo-baseline` rolling Deployment returned thirty HTTP 200 responses
with the good image. With the same scanned HTTP-error image, it remained Available
while returning thirty HTTP 500 responses. It was scaled to zero after comparison.
This proves the selected readiness/liveness probes do not detect that regression;
it is not a performance comparison under statistically repeated identical trials.

The successful startup retest is the second `trial-startup-*` directory, after the
original five-minute deadline failure. Failed and passing runs remain separate;
no original evidence was overwritten. The native controller removed retired
objects, re-enabled deadline evaluation, and aborted while stable stayed healthy.

The known-good, scanned digest was restored after testing with history limit zero.
Restoration evidence is in `output/final-restore.json`; the consolidated local
evidence index is `output/live-validation-index.json`. The cluster passed a full
stop/start cycle, both system controllers became ready, and the restored service
returned healthy responses with two available replicas. The lab is left stopped
between work sessions to release RAM. Start it with
`scripts/lab.ps1 -Action start`.

Final checks passed in both Windows and Linux venvs: twelve tests and eighteen
schema validations, including consistency checks for the pinned runtime, k3s,
and Prometheus image selections. Linux `pip check`, Bash syntax, Python compilation,
PowerShell launcher execution, and Git whitespace checks also passed.

## Issues found while installing and testing

1. Large Rollouts CRDs require server-side apply; bootstrap was corrected.
2. k3d's checksum file uses an `_dist/` prefix; installer verification was corrected.
3. The configured registry container is `registry.localhost`. The original custom
   mirror pointed at `k3d-registry.localhost`; the source now uses the correct name.
   The first cluster received an additional Docker network alias to make its
   already-loaded original mirror work without replacing the cluster. Fresh
   bootstraps use the corrected endpoint directly.
4. Rollouts reports `observedGeneration` as a string; trial comparison was corrected.
5. A pilot healthy promotion passed controller analysis but had one client timeout
   in 975 stable requests while Trivy unpacked its database. This failed the
   availability gate and is retained in `trial-healthy-20261020T112025Z`.
   The competing task is a plausible cause, not a proven root cause.
6. A subsequent trial stopped before deployment because the stable endpoint was
   unavailable after WSL idled/stopped between commands. The launcher now manages
   a hidden WSL keepalive and waits for system controllers on cluster start.
   This failed preflight is retained in `trial-healthy-20261020T112620Z`.
7. With revision history set to three, startup failure stayed Progressing beyond
   the 180-second lack-of-progress deadline and the 300-second harness deadline.
   All 1,408 observed stable requests succeeded, but the abort criterion failed.
   Retired zero-replica sets still had expired `scale-down-deadline` annotations.
   The pinned controller's
   [deadline guard and history cleanup code](https://github.com/argoproj/argo-rollouts/blob/v1.10.1/rollout/sync.go)
   skips deadline evaluation while such markers exist. The lab now sets
   `revisionHistoryLimit: 0` so the native controller removes retired sets.
   This is a configuration workaround, not an upstream controller patch.
   Cleanup also removes their associated AnalysisRuns; the exported trial evidence
   is therefore the historical record. Active stable/candidate sets are retained,
   and non-zero old replicas remain protected during their scale-down window.

## Remaining gates

Jenkins and Argo CD are not installed or connected. The selected component versions
and templates are prepared, but a protected environment repository and an isolated
Linux build host still need configuration. Do not describe the current manual lab
driver as an operational Jenkins/GitOps integration.

Post-promotion analysis, durable release history, permissions, reconciliation,
notification delivery, persistent metrics, backups, multi-node resilience, and
repeated benchmark trials remain in the implementation backlog. The native
Rollouts tests here exercise pre-promotion rejection and retained stable service.
