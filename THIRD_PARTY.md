# Third-party inventory

No upstream application source has been copied or merged. Demo, tests, scripts,
pipeline, and configuration in this repository are project-authored.

| Dependency | Use | Upstream licence reference |
|---|---|---|
| Python / official Python image | Demo runtime | https://docs.python.org/3/license.html |
| Alpine Linux packages | Minimal runtime distribution; inventory in generated SBOM | https://alpinelinux.org/about/ |
| k3d | Local k3s-in-Docker lab | https://github.com/k3d-io/k3d/blob/main/LICENSE |
| k3s | Local Kubernetes runtime | https://github.com/k3s-io/k3s/blob/master/LICENSE |
| Distribution registry image | Local OCI registry | https://github.com/distribution/distribution/blob/main/LICENSE |
| Argo Rollouts | Release controller and native CLI/dashboard | https://github.com/argoproj/argo-rollouts/blob/master/LICENSE |
| Argo CD | GitOps controller, later installation | https://github.com/argoproj/argo-cd/blob/master/LICENSE |
| Prometheus | Candidate telemetry | https://github.com/prometheus/prometheus/blob/main/LICENSE |
| Trivy | CI vulnerability scan and SBOM | https://github.com/aquasecurity/trivy/blob/main/LICENSE |
| Jenkins | External CI controller/agent | https://github.com/jenkinsci/jenkins/blob/master/LICENSE.txt |
| FastAPI | Local authenticated state API | [Upstream license](https://github.com/fastapi/fastapi/blob/master/LICENSE) |
| SQLAlchemy | PostgreSQL access and transactions | [Upstream license](https://github.com/sqlalchemy/sqlalchemy/blob/main/LICENSE) |
| Alembic | Explicit database migrations | [Upstream license](https://github.com/sqlalchemy/alembic/blob/main/LICENSE) |
| Psycopg | PostgreSQL driver and binary distribution | [Upstream notices](https://github.com/psycopg/psycopg/blob/master/COPYING) |
| PostgreSQL / official image | Durable release/evidence state | [Upstream license](https://www.postgresql.org/about/licence/) |
| Uvicorn | Local API process | [Upstream license](https://github.com/encode/uvicorn/blob/main/LICENSE.md) |
| HTTPX | Authenticated CLI and HTTP acceptance client | [Upstream license](https://github.com/encode/httpx/blob/master/LICENSE.md) |

Selected versions are in `versions.json` and `backend-versions.json`; backend
Python packages are pinned in `requirements-backend-lock.txt`, including transitive
dependencies. Their distribution notices remain in the installed wheel metadata.
The registry is pinned in `platform/k3d.yaml`.
Exact tags do not constitute immutable checksums. Infrastructure image digests,
download checksums, full transitive attribution and installation compatibility are
not yet comprehensively enforced. Local runtime and backend installation are
validated in milestone evidence. Application release manifests require OCI SHA-256 digests.
No licence is selected for project-authored code; choose one before distribution.
