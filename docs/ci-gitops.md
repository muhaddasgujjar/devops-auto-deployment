# Local CI and GitOps integration

This profile uses the existing WSL host because no separate Linux host or cloud
account is available. It is a trusted local experiment. A remote host and mutually
reachable TLS registry remain the deployment target for a team installation.
The [GitHub-source acceptance record](scm-validation.md) now verifies scheduled
SCM builds, automatic healthy promotion and controlled HTTP-error rejection.

## Ownership and boundaries

1. A Jenkins controller runs on loopback port 8082 with authentication, no anonymous
   read access, zero build executors, and a bounded JVM/container memory budget.
2. A separate trusted Linux agent runs the tests, Docker build and Trivy scan. It
   receives the environment Git write credential through Jenkins. It has Docker
   socket access, which is root-equivalent on this dedicated host. Neither the
   controller nor agent is given a kubeconfig or Kubernetes CLI.
3. The publisher pushes digest-only desired manifests to a separate local bare Git
   repository over SSH. A non-fast-forward push fails; it never force-pushes.
4. Argo CD Core reads that repository with a separate read-only key and reconciles
   the restricted Application into `demo-dev`. Rollouts owns candidate decisions
   and service revision selectors.
5. An independent observer generates candidate traffic and records stable service
   responses. It has Kubernetes access; it observes deployments without applying
   release manifests. CI success means the environment commit was published, not
   that the candidate was approved for traffic.

Argo CD Core has no persistent UI server. Use Kubernetes Application status and
the existing Rollouts/Prometheus browser interfaces. The upstream core manifest
checksum and Jenkins base-image digest are recorded in `versions.json`.

## Setup and lifecycle

Run from the project root in PowerShell, after the original lab has a healthy
stable release:

```powershell
.\scripts\lab.ps1 -Action start
.\scripts\lab.ps1 -Action gitops-setup
.\scripts\lab.ps1 -Action ci-setup
wsl -d Ubuntu-24.04 -u root --exec /opt/release-lab/venv/bin/python -m scripts.configure_jenkins --enable-main
.\scripts\lab.ps1 -Action review
.\scripts\lab.ps1 -Action status
```

Image/plugin downloads may take considerable time. Logs are retained under
`output/release-*-build.log`. Initial GitOps adoption seeds the exact serving pod
template into the environment repository before enabling reconciliation. It
refuses to overwrite a pre-existing environment branch. Jenkins setup similarly
refuses to replace an existing controller or trusted source snapshot.

After adoption, the old `trial` action deliberately refuses manual deployment.
Use the GitOps trial instead:

```powershell
.\scripts\lab.ps1 -Action gitops-trial -Scenario healthy
.\scripts\lab.ps1 -Action gitops-trial -Scenario error
.\scripts\lab.ps1 -Action gitops-trial -Scenario healthy
```

Run one trial at a time. Expected verdicts are
`candidate-promoted-through-gitops` and `candidate-rejected-through-gitops`, with
zero failed stable observations. `latency` and `startup` are also supported.
Healthy restore uses a new Git commit; Argo continues owning the workload.
Evidence is retained in timestamped `output/gitops-SCENARIO-TIMESTAMP` folders.
Avoid source pushes during a trial: the polling job can publish another candidate.
Serialization across the complete analysis/release lifetime remains a later milestone.

`start` reuses labelled CI containers and starts the dedicated Git SSH service;
`stop` closes review forwards, stops the agent/controller, then stops the cluster.
Jenkins home is a Docker volume. Local environment Git lives under
`/var/lib/release-lab/git/environment.git`; keys remain under
`/opt/release-lab/secrets`. These paths are outside OneDrive and the source checkout.
They are local state outside the scope of the [evidence and TSDB backups](persistence.md).
Long-running PowerShell setup/trial commands temporarily request that Windows
stay awake and release that request on exit. Background polling follows the
host's normal sleep behavior; this local machine is not an always-on build host.

## Jenkins access and source provenance

Jenkins is at http://localhost:8082/ with user `release-admin`. Retrieve its generated
password locally, without committing or sharing it:

```powershell
wsl -d Ubuntu-24.04 -u root --exec cat /opt/release-lab/secrets/jenkins-password
```

The optional `release-local` acceptance job uses an immutable snapshot of the trusted working checkout stored
on the Linux filesystem. Its snapshot Git SHA is carried into images and release
evidence. This allows integration code to be exercised before it is published.
It is a manual local acceptance job, not proof of a GitHub-triggered build. Select
it explicitly with `-BuildJob release-local`. The default `release-main` job uses
`ci/Jenkinsfile` from GitHub main and polls for source changes.
Both jobs use the same environment publisher and unique release identifiers.

Root plugins are listed in `ci/plugins.txt`. All 59 installed plugin versions and
SHA-256 checksums are locked in `ci/plugins.lock.txt`, `ci/plugins.lock.json` and
`ci/plugins.sha256`; controller builds verify the downloaded archives.
Jenkins core/plugin updates require compatibility and security review.

## Database download recovery

The scanner keeps its high/critical gate enabled and updates its database from
the official GHCR repository. Network failures block the build before environment
Git is changed. If container downloads fail on this host, fetch the current OCI
database layer through Windows and verify its digest, then import it into an idle
agent. The importer rejects expired databases and unexpected archive members.

```powershell
$dbArchive = Join-Path (Get-Location) 'output\gitops\trivy-db.tar.gz'
.\.venv\Scripts\python.exe -m scripts.fetch_trivy_db --archive $dbArchive --stage-in-wsl
$linuxArchive = '/opt/release-lab/cache/trivy-db-current.tar.gz'
wsl -d Ubuntu-24.04 -u root --exec /opt/release-lab/venv/bin/python -m scripts.import_trivy_db --archive $linuxArchive
```

The module commands require the project as the current directory. The helper
records layer digest and vendor timestamps under `output/gitops/`. It does not
change the vendor's UpdatedAt/NextUpdate dates, skip scanning, or disable future
updates. It records the actual local import time in DownloadedAt, matching Trivy's
normal installer behavior.
The optional WSL staging streams bytes from Windows and verifies the digest
again on Linux. This avoids large reads through the Windows mount, which failed
with `Cannot allocate memory` on this constrained host despite free Linux cache.

## Remote transition still required

- The `release-main` job checks out GitHub main and polls every two minutes. It is
  initially disabled until the reviewed implementation is present on main. Enable
  it with `python -m scripts.configure_jenkins --enable-main` inside the lab. Polling
  avoids exposing localhost or creating a public webhook.
- Move the environment repository to the intended Git server, provision separate
  read/write deploy credentials and verify its host key. Protect the environment branch.
- Replace the loopback HTTP registry with a registry reachable over verified TLS;
  provision push/pull credentials independently.
- Move the trusted build agent off the cluster host. Extend the local telemetry
  and evidence backups to an independent host and cover all other lab state
  before treating this as a shared service.

## Observed local acceptance — 22 October 2026

`release-local` build 5 completed tests, the HIGH/CRITICAL scan gate, SBOM export,
registry publication and environment Git commit
`690c466df712317e8c2f35a82a1f7912e6904462`. The source is the immutable local
snapshot `492d52d79097486646cfaa3fba135b6515e77259`, not a GitHub main commit.
The image digest is
`sha256:7e32ce7b486346116b930c43b4e25dbf1d272d3d9a9a25cf98b5704ee36b01ac`.

The interrupted observer left the candidate without traffic and its analysis
became Inconclusive. A retry-only pilot did not restart it: native retry acts on
aborted rollouts. The corrected recovery aborts that paused candidate first and
then retries, preserving the gate and starting a fresh AnalysisRun rather than
resuming past the measurement. [Argo's analysis behavior](https://argoproj.github.io/argo-rollouts/features/analysis/)
documents the manual intervention required by an inconclusive result.

The recovered run `output/gitops-healthy-20261022T183433Z` verified Argo CD Synced
to that environment commit, both metrics Successful, the matching image/revision
serving from stable, and 734 stable HTTP observations with zero non-200 responses.
Its `operator_analysis_retry: true` explicitly distinguishes this recovery from
an uninterrupted automatic run. The failed retry pilot retained 1,985 stable
observations with zero non-200s and is archived as `trial-failed`.

This initial record proves the local snapshot build/publish/reconcile/promotion path with
operator recovery. GitHub polling through `release-main`, uninterrupted healthy
delivery, Jenkins-driven fault rejection, a fresh controller rebuild from all
plugin locks, and fresh-machine reproduction were unverified at that point.
The later [SCM acceptance](scm-validation.md) completes healthy automatic delivery
and HTTP-error rejection; the other listed acceptance gaps remain explicit. The
scanner database used by build 5 was current on 21 October; new builds must fetch
a fresh database rather than reuse expired metadata.

## Upstream references

- [Argo CD Core](https://github.com/argoproj/argo-cd/blob/v3.5.5/docs/operator-manual/core.md)
- [Jenkins Docker installation](https://www.jenkins.io/doc/book/installing/docker/)
- [Jenkins Java requirements](https://www.jenkins.io/doc/book/platform-information/support-policy-java/)
