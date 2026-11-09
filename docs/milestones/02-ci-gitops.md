# Milestone 2: merged-source CI and GitOps acceptance

Started 10 November 2026 (Asia/Karachi). Final results are recorded below after actual execution; job configuration alone is not a completed delivery proof.

## Acceptance boundary

Prove a reviewed merged source commit passes real Jenkins tests, image build, pinned Trivy HIGH/CRITICAL scan, SBOM generation, local registry digest publication, environment Git publication, Argo CD reconciliation and a healthy Rollouts promotion. Also prove an actual failing unittest blocks downstream build/publication and leaves environment Git unchanged.

This is a manually triggered local acceptance job on existing trusted hardware. It is not an external webhook, production SLA, remote build host, or TLS-registry validation. The existing localhost registry and Docker-socket agent remain explicit lab trust boundaries.

## Source and job configuration

- Initial source under test: `e2017ac5f3e04e5b2722ef71f7075fe741a45dfe`. The patched source commit is recorded separately in final acceptance evidence.
- Job: `release-merged`, with one trusted executor and serialized builds.
- Host snapshot: `/opt/release-lab/source-revisions/<source SHA>`; agent copy: `/opt/release-merged-source/<source SHA>`. Existing `/opt/release-lab/source-snapshot` is preserved.
- `scripts/prepare_merged_source.py` refuses a dirty checkout or a changed snapshot. It copies only committed Git source, not scratch files or secrets, and verifies the agent checkout identity.
- `scripts/configure_merged_ci.py` configures the reviewed acceptance pipeline from the selected Git commit using the authenticated local Jenkins admin API. It disables the older `release-main`/`release-local` jobs and removes their triggers before the agent starts.
- Removed the hard-coded external GitHub URL from the bootstrap defaults. A future external SCM job requires an explicitly configured source repository.
- Builds carry source SHA and build number into the image revision; environment manifests require a registry digest. CI has no kubeconfig or Kubernetes CLI. Rollouts owns candidate decisions after Argo CD sync.

## Negative test gate: passed

Jenkins build 1 ran the normal suite, then one intentionally failing unittest requested by `FAIL_TEST_GATE`. It returned FAILURE and archived only `output/source.json`. Build/scan/publish did not proceed. Environment Git stayed at `0401e6ceb244020af09c5c915241e038d64011bd` before and after. See `docs/evidence/ci-negative-gate.json`.

This is a synthetic local acceptance fixture, not a separate faulty application-source commit. It exercises the real Jenkins stage ordering and environment boundary; it must not be described as a production application regression.

## Measurement boundaries

The first healthy attempt (build 2) stopped because the default mirror's database download exceeded Trivy's five-minute timeout. No desired-state publication occurred. Its failed trial summary and console remain under `output/gitops-healthy-20261109T192922Z`. No availability samples were collected because this failure preceded the measurement boundary; zero collected failures must not be interpreted as an availability result.

Refresh the managed agent's database before a session with `python -m scripts.prepare_scanner`. This uses the official `ghcr.io/aquasecurity/trivy-db:2` repository with a 15-minute download budget, without skipping updates or changing severity policy. The image is still scanned by Jenkins afterward. See [Trivy database configuration](https://trivy.dev/docs/latest/configuration/db/). Record database update/download timestamps with the final image scan evidence. A successful database refresh alone does not count as a passing image scan.

Build 3 used the refreshed database and rejected the original pinned runtime: HIGH findings affected musl, musl-utils and zlib, with fixed package revisions reported. Its full scan is retained in `docs/evidence/ci-rejected-scan.json`. Publication was skipped. The official Python 3.14/Alpine 3.24 tag was resolved to a new immutable digest in `versions.json` and `demo/Dockerfile`; acceptance is repeated against that patched source, without an ignore list or severity relaxation.

To avoid scanner/resource contention in availability measurements, the observer starts stable-service sampling after CI completes and artifacts have been retrieved. The report explicitly excludes build/scan and Git-publication time from its availability observations. Candidate analysis timing and CI timing are separate. A green CI build means desired state was published; promotion still requires controller evidence.

Detailed local trial output is under ignored timestamped `output/gitops-*` directories. Commit only sanitized summary/provenance evidence, not credentials or raw infrastructure state. Positive results must correlate source commit, build, actual scanned image, environment commit, Argo sync revision, candidate analysis, and final served revision.

## Repeating the local acceptance

Commit reviewed changes first. Start the lab in lean mode and require healthy GitOps before attempting CI. Start the existing controller while the agent is stopped; wait for its authenticated API. Then prepare the source snapshot, configure `release-merged` using that source SHA, start the agent, and copy/verify its snapshot. Do not replace the old snapshot or containers to adopt the merged source.

Run `python -m scripts.verify_ci_gate` for the negative gate and `python -m scripts.gitops_trial healthy --job release-merged` for the healthy path inside the configured Linux venv. Keep only one trial running. Source and artifact evidence must identify the selected commit, even when later documentation commits exist.

After all Jenkins artifacts have been captured, CI can be stopped to free memory during runtime analysis. Do not stop it while a build or artifact download is in progress. End the full lab session with `scripts/lab.ps1 -Action stop`.

## Remaining scope

External SCM/webhook configuration, a separate build machine, shared TLS registry, fresh-machine installation, repeated availability distributions, post-promotion recovery, product API/UI, and durable evidence ingestion remain separate gates. Do not infer their completion from this acceptance job.
