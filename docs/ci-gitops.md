# Local CI and GitOps integration

This profile uses the existing WSL host because no separate Linux host or cloud
account is available. It is a trusted local experiment. A remote host and mutually
reachable TLS registry remain the deployment target for a team installation.

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

`start` reuses labelled CI containers and starts the dedicated Git SSH service;
`stop` closes review forwards, stops the agent/controller, then stops the cluster.
Jenkins home is a Docker volume. Local environment Git lives under
`/var/lib/release-lab/git/environment.git`; keys remain under
`/opt/release-lab/secrets`. These paths are outside OneDrive and the source checkout.
They are local state, not a tested backup system.

## Jenkins access and source provenance

Jenkins is at http://localhost:8082/ with user `release-admin`. Retrieve its generated
password locally, without committing or sharing it:

```powershell
wsl -d Ubuntu-24.04 -u root --exec cat /opt/release-lab/secrets/jenkins-password
```

The local job uses an immutable snapshot of the trusted working checkout stored
on the Linux filesystem. Its snapshot Git SHA is carried into images and release
evidence. This allows integration code to be exercised before it is published.
It is a manual local acceptance job, not proof of a GitHub-triggered build.
`ci/Jenkinsfile` remains the production SCM pipeline for a trusted main-branch job.
Both jobs use the same environment publisher and unique release identifiers.

Root plugins are version-pinned in `ci/plugins.txt`; dependency resolution and
installation must be recorded and locked before moving to a shared host.
Jenkins core/plugin updates require compatibility and security review.

## Remote transition still required

- Commit and review the integration code, then configure Jenkins SCM checkout and
  polling or an authenticated reachable webhook. Do not expose localhost publicly.
- Move the environment repository to the intended Git server, provision separate
  read/write deploy credentials and verify its host key. Protect the environment branch.
- Replace the loopback HTTP registry with a registry reachable over verified TLS;
  provision push/pull credentials independently.
- Move the trusted build agent off the cluster host. Add persistent telemetry,
  durable evidence storage and backups before treating this as a shared service.

## Upstream references

- [Argo CD Core](https://github.com/argoproj/argo-cd/blob/v3.5.5/docs/operator-manual/core.md)
- [Jenkins Docker installation](https://www.jenkins.io/doc/book/installing/docker/)
- [Jenkins Java requirements](https://www.jenkins.io/doc/book/platform-information/support-policy-java/)
