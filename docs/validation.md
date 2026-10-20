# Validation record

Checked on 20 October 2026, Windows, Python 3.14.3:

| Check | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 12 passed |
| `python -m scripts.validate_manifests` with optional validation dependencies | 18 resource/config documents passed pinned upstream schemas |
| `bash -n scripts/bootstrap-lab.sh` using Git Bash | Passed |
| `python -m compileall -q demo scripts tests` | Passed |
| `git diff --check` | Passed |

The HTTP tests start real local servers. They cover healthy responses, revision
metadata, errors with healthy probes, readiness failure, latency histograms,
probe exclusion, concurrent request accounting, external JSONL evidence, and
invalid runtime configuration. Rendering tests cover immutable digest enforcement,
injection rejection, deterministic output, and the separate rolling baseline.

Schema checks use official k3d configuration JSON Schema, Argo Rollouts and Argo CD
CRDs, and Kubernetes 1.35.9 OpenAPI definitions. They validate rendered releases,
the rolling baseline, monitoring, the Argo application/project, and k3d config.
The validator translates OpenAPI v2's custom IntOrString format for JSON Schema.
Schemas do not prove PromQL behavior, controller behavior, or resource admission.

Versions were checked against upstream release metadata; the chosen k3s image tag
exists and Kubernetes 1.35 is in Argo CD 3.5's documented test range. The entire
combination has not been exercised together.

At the initial foundation checkpoint, Docker build/scan/push, registry pulls,
controller behavior, Jenkins and GitOps had not been run. Ubuntu and the lean
cluster were subsequently installed. See [live validation](live-validation.md)
for the container, scan, telemetry, promotion, and abort evidence. Jenkins execution,
Argo CD synchronization, and formal repeated benchmarks remain unverified.

Never interpret local tests or static manifest checks as a successful live rollback.

## Virtual environment verification

On 20 October 2026, created `.venv` with Python 3.14.3 and installed
`requirements-validation.txt` plus its transitive dependencies inside it.
`pip check` passed; all 12 tests and 18 schema checks passed using
`.venv/Scripts/python.exe`. The environment occupies approximately 14.4 MiB
of file contents on disk and is ignored by Git. The previous temporary
`.tools/validation` package directory remains unused because automatic approval
review blocked its cleanup. Cached schemas remain in `.tools/schemas`.

At setup time the host reported 8,228,056 KiB total visible RAM and 804,912 KiB
free physical RAM (about 0.77 GiB free). A venv isolates installed packages and
does not run a background service or reserve RAM. It is recommended for this
project; concurrent Docker/cluster/build processes are the material RAM concern.

The subsequent live milestone installed a separate Linux venv at
`/opt/release-lab/venv`, reran twelve tests/eighteen schema checks in both
environments after the live fixes, and passed Linux `pip check`. See the linked
live validation report for all controller trials and the deliberately retained
failed pilot results.
