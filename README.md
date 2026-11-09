# Self-hosted release platform

Milestone 1 establishes the scope, a controlled sample workload, measurable acceptance criteria, and environment evidence. The platform design uses Jenkins -> OCI registry -> environment Git -> Argo CD -> Argo Rollouts, with Prometheus analysis. The custom product API and UI are later milestones.

Current overall assessment: approximately **20% of the full MVP**, using a weighted evidence rubric. See [progress and prioritized next steps](docs/progress-and-next-plan.md) and [source reconciliation](docs/source-reconciliation.md). The local source baseline and historical lab are separate lineages; integrate them through reviewed contract changes.

Start with [milestone status](docs/milestones/01-foundation.md), [scope and acceptance criteria](docs/mvp-scope.md), and [lab runbook](docs/runbooks/local-demo.md). The original [assessment](DevOps_Product_Assessment_and_Build_Plan.md) remains design background.

## Run without containers

Python 3.11 or newer is sufficient; no third-party Python dependencies are required for this sample.

```powershell
python demo/app/server.py
```

Open <http://127.0.0.1:8080/api/work>. The service defaults to loopback and healthy behavior. Stop it with Ctrl+C. This is a controlled test workload, not the production platform API.

## Validate

```powershell
python scripts/validate.py
```

This launches temporary loopback servers, exercises healthy and faulty releases, checks instrumentation, and writes `docs/evidence/native-validation.json`. It closes those servers when finished. Container/cluster evidence is separate.

## Build/deploy

See the runbook for Docker and Kubernetes steps. The Docker base digest is tracked in `versions.json`; a built sample image has its own digest. Do not mistake the base digest for the sample artifact digest. No hosted services, public repositories, or paid resources are provisioned by these files.
