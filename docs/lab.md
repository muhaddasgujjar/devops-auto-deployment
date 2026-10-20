# Lab runbook

## 1. Local application checks (Windows or Linux)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-validation.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m demo.app
```

Create `.venv` once; reuse it for subsequent commands. Optional PowerShell activation:
`.\.venv\Scripts\Activate.ps1`. Direct interpreter paths work without activation
or changes to PowerShell execution policy. `.venv/` is ignored by Git.
The demo and tests need only Python's standard library; PyYAML and jsonschema are
the current project's only third-party Python dependencies and support validation.

Set a fault in a new terminal before starting the process:

```powershell
$env:DEMO_MODE = 'error'
.\.venv\Scripts\python.exe -m demo.app
```

Use `DEMO_MODE=error .venv/bin/python -m demo.app` in Bash. Stop the previous service first.

Manifest checks download the selected components' official schemas and
cache them in ignored `.tools/schemas` (internet needed on first run):

```bash
# Linux: create/install once if not already done.
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-validation.txt
.venv/bin/python -m scripts.validate_manifests
```

On Windows use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.

## 2. Container lab prerequisites

Use Linux or WSL2 with a working Linux Docker runtime, Python 3.11+, Git, kubectl,
and k3d matching `versions.json`. Install tools from their official distributions.
The bootstrap does not install Docker or change Windows virtualization settings.
Start with spare RAM for Docker; keep Jenkins outside this 8 GiB host.

On a Linux shell at the repository root:

```bash
bash scripts/bootstrap-lab.sh
export KUBECONFIG="$PWD/output/lab.kubeconfig"
kubectl get pods -A
```

Bootstrap creates only `release-lab`, writes a dedicated ignored kubeconfig, installs
Rollouts and lean Prometheus, and refuses to reuse an existing named cluster.
After a partial failure, inspect with `k3d kubeconfig get release-lab` and repair
the failed step explicitly. No global kube context is changed.

## 3. Build and establish a healthy baseline

The registry is on the same Docker host. These Bash commands push a tag only to
resolve its digest; Kubernetes receives the immutable reference:

```bash
commit=$(git rev-parse HEAD)
docker build -f demo/Dockerfile --build-arg DEMO_MODE=healthy --build-arg APP_REVISION="$commit" -t localhost:5001/release-demo:healthy .
docker push localhost:5001/release-demo:healthy
docker pull localhost:5001/release-demo:healthy
image=$(docker image inspect localhost:5001/release-demo:healthy --format '{{index .RepoDigests 0}}')
python3 scripts/render_release.py --image "$image" --commit "$commit" --output output/release
kubectl apply -f output/release
kubectl get rollout,analysisrun,pods -n demo-dev
```

Use `kubectl port-forward -n demo-dev service/demo-stable 8081:80` and, in a separate
terminal, `kubectl port-forward -n demo-dev service/demo-preview 8082:80`.
Check stable responses manually. First creation has no stable predecessor and
may skip analysis. Never use a fault artifact to establish the initial revision.

Port forwards can close when their selected pod is replaced. Restart them after
preview changes. Any resulting transport errors belong in the evidence; use a
separate Linux load host and stable routing for final availability benchmarks.

## 4. Reject a faulty candidate

Keep an external client running against stable while changing desired state:

```bash
python3 scripts/load.py http://127.0.0.1:8081/ --seconds 240 --workers 4 --output output/stable-error-trial.jsonl
```

In another terminal, build/push a new artifact with `--build-arg DEMO_MODE=error`
and a unique tag (e.g. `:error-1`), pull it and resolve RepoDigests as above, then
render and apply the new digest. Once candidate pods are ready, restart preview's
port forward and generate traffic throughout analysis:

```bash
python3 scripts/load.py http://127.0.0.1:8082/ --seconds 180 --workers 4 --output output/preview-error-trial.jsonl
kubectl get analysisrun -n demo-dev -o yaml > output/error-analysis.yaml
kubectl get rollout release-demo -n demo-dev -o yaml > output/error-rollout.yaml
kubectl get service demo-stable demo-preview -n demo-dev -o yaml > output/error-services.yaml
```

Expected: error metric fails; Rollouts aborts candidate promotion; stable selector
and healthy responses remain. Verify this live; the local unit tests cannot prove it.
Repeat with `latency` and `startup`. For missing telemetry stop preview traffic
or temporarily scale Prometheus to zero: progression must not succeed. Restore
Prometheus to one replica after the experiment. A paused/inconclusive candidate
needs operator review, never `promote --full` to bypass missing evidence.

Render a new healthy digest to recover the experiment. For an aborted identical
digest use the version-matched Rollouts CLI's explicit retry after review. Do not
use Deployment undo on a GitOps-managed Rollout.

## 5. Rolling baseline

```bash
python3 scripts/render_release.py --baseline --image "$image" --commit "$commit" --output output/baseline
kubectl apply -f output/baseline
kubectl rollout status deployment/release-demo -n demo-baseline --timeout=180s
kubectl port-forward -n demo-baseline service/demo 8083:80
```

Apply error and latency digests in this namespace for comparison. Readiness can
pass despite application errors; conventional Deployment does not automatically
restore the old image on that regression. Record outcomes with the same client.

## 6. GitOps and Jenkins integration

Only after the manual lab succeeds, create a separate environment Git repository
with an initial `main` commit. Install the selected Argo CD non-HA manifest in an
`argocd` namespace, configure its repo read credential, and replace
`__ENV_REPO_URL__` in `platform/argocd/application.yaml`. Apply that file to delegate
`environments/dev` to Argo CD. Stop applying release resources manually after this
ownership handoff. Never commit `output/` or kubeconfigs to either repository.

Configure one Jenkins Pipeline job for trusted `main`, using `ci/Jenkinsfile` and
a `trusted-linux-docker` agent. Install Pipeline, Git, SSH Agent, and Timestamper
plugins, Python, Docker, and the pinned Trivy CLI. Add `environment-git-ssh` (write
access only to the environment repo), verified SSH known_hosts, and registry login
outside source control. The environment branch must permit this restricted bot's
updates; use a promotion PR flow instead if branch policy requires review.

Use an authenticated, reachable TLS registry when agent and cluster are on different
hosts; the localhost example works only on the same Docker host. Do not mount the
build host Docker socket into the application cluster. Restrict job parameters,
credentials, and job modification to operators. Jenkins has no Kubernetes credentials.
Keep exactly one writer/job per environment; rejected Git pushes fail without force
or blind retry. Serialization here is per job, not a platform-wide lock.

Configure the SCM trigger at Jenkins only. GitHub cannot deliver to laptop localhost;
use a reachable secured endpoint or document polling as a temporary lab fallback.
Review real scan output; no ignored vulnerability policy is supplied by default.

## 7. Evidence and teardown

Store JSONL, controller YAML, source/environment Git commits, image digest, component
pins, hardware, cache state and trial times together. Results are not an SLO.
Prometheus samples are ephemeral. Protect evidence before teardown.

To remove this disposable lab explicitly: `k3d cluster delete release-lab`.
This removes lab workloads and cluster storage; export needed data first.
