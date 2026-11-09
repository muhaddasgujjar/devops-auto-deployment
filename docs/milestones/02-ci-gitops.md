# Milestone 2: merged-source CI and GitOps acceptance

Completed 10 November 2026 (Asia/Karachi): **local, manually triggered CI-to-GitOps acceptance passed**. External SCM triggers and production readiness remain separate gates.

## Accepted result

Jenkins build **8** passed for source `05d553b044d566ce06fca3205db0632fe0328c77`. It ran the 36 tests in that release snapshot, scanned with Trivy 0.76.0 and a freshly downloaded database, generated its SBOM, pushed digest `sha256:02c43fb87712b706213ae04282c23801f4d565b0a24e7d988f25c66fafd26799`, and published environment commit `14b3ae8e2d3c6393047738bc62ee57e683dc0d44`. Argo CD synchronized that exact commit, Rollouts analysis succeeded, and the stable service returned revision `05d553b044d566ce06fca3205db0632fe0328c77-jenkins-8`.

The controlled passing run recorded **849 stable observations, all HTTP 200**. It kept CI idle throughout runtime observation. The earlier build-7 trial's one timeout is retained and is not included as a passing trial. These finite checks through the Kubernetes API proxy do not establish a production availability SLO.

The successful CI run took **45.262 seconds**, after database preparation and with image caches available. The complete observed trial ran from 19:59:00 to 20:03:07 UTC; database maintenance, previous attempts and initial downloads are separate. Do not compare the 45-second CI component alone against a full release-stability deadline.

`docs/evidence/ci-gitops-acceptance.json` cross-checks source identity, actual scanned image/config identity, registry digest, environment commit, Argo synchronization, successful analysis for the serving hash, service selector, final response, and the matching-source negative gate (build 5). The evidence verifier was also run against the failed-availability trial and correctly rejected it. Raw artifacts and failed attempts remain in ignored `output/` directories; sanitized history is committed in `docs/evidence/ci-attempt-history.json`.

The current working-source suite has **39 passing tests**, including observer startup/queue regression cases added after the release snapshot. **18 schema checks** pass. These counts are deliberately distinguished from the 36 tests Jenkins ran in the immutable application release snapshot.

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

Keep CI state constant while runtime observations are being collected. Do not stop/start it during a trial. End the full lab session with `scripts/lab.ps1 -Action stop` only after capture completes.

## Additional issues found during execution

- Jenkins can return a queued item with `executable: null`, and its authenticated endpoint can reset connections during startup. The observer now handles that queue state and waits for readiness; authentication errors still fail immediately. Regression tests cover both cases. One early observer exited before collecting build 4's expected intentional failure; build 5 repeats that gate successfully for patched source `05d553b044d566ce06fca3205db0632fe0328c77`.
- Build 6 passed the scan and registry publication but could not clone environment Git: the root-owned public `known_hosts` file was mode 0600 and unreadable by UID 1000 in the agent. Only that public trust-anchor file was corrected to mode 0644, root-owned and read-only in the container. Private keys and their directory remain restricted. The setup script now reproduces this permission correctly.
- Build 7 passed CI and promoted the release, but the observer recorded one three-second timeout among 746 stable-service requests. The timeout coincided with CI shutdown; causality was not established. This run fails the strict availability gate and is retained. A controlled repeat leaves CI idle throughout observation, with identical client timeout and acceptance thresholds. Controller success alone is not an availability pass.

## Remaining scope

External SCM/webhook configuration, a separate build machine, shared TLS registry, fresh-machine installation, repeated availability distributions, post-promotion recovery, product API/UI, and durable evidence ingestion remain separate gates. Do not infer their completion from this acceptance job.

Next local priority: fresh runtime-failure/rejection tests against this integrated path, then durable release/evidence API and restart reconciliation. Keep the other machine migration deferred as requested. The lab is stopped after final verification to release laptop RAM; the accepted release and credentials persist locally.
