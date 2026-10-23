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
| React / React DOM | Releaseboard UI | https://github.com/facebook/react/blob/main/LICENSE |
| Vite | Local frontend build tooling | https://github.com/vitejs/vite/blob/main/LICENSE |
| Lucide | UI icons, installed package licence retained in frontend notices | https://github.com/lucide-icons/lucide/blob/main/LICENSE |
| FastAPI / Starlette / Uvicorn | Local product API and HTTP runtime | https://github.com/fastapi/fastapi/blob/master/LICENSE |
| SQLAlchemy / Alembic | Product metadata and database migrations | https://github.com/sqlalchemy/sqlalchemy/blob/main/LICENSE |
| Psycopg | PostgreSQL driver | https://www.psycopg.org/psycopg3/docs/basic/install.html |
| PostgreSQL official image | Retained local product database | https://www.postgresql.org/about/licence/ |

Selected versions are in `versions.json`; registry is pinned in `platform/k3d.yaml`.
Exact tags do not constitute immutable checksums. Infrastructure image digests,
download checksums, full transitive attribution and installation compatibility are
pending live installation. Application release manifests require OCI SHA-256 digests.
No licence is selected for project-authored code; choose one before distribution.

The local CI profile additionally pins the Jenkins base-image digest and all 59
installed plugin versions/archive checksums in `ci/plugins.lock.*` and
`ci/plugins.sha256`. Argo CD Core's upstream manifest checksum is enforced by
its installer. This does not complete the remaining infrastructure-image digest lock.

The product database image is digest-pinned in `versions.json`. Product Python
versions are locked in `apps/api/requirements.lock.txt`; frontend dependencies and
integrity hashes are recorded in `apps/web/package-lock.json`. Installed frontend
runtime licence texts are included in `apps/web/public/third-party-notices.txt`.
