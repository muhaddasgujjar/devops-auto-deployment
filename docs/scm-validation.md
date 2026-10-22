# GitHub-source delivery acceptance

These trials use the real `release-main` Jenkins job and the separate environment
Git repository. They supersede the earlier snapshot-only acceptance limit; they
remain single-host local experiments, not a production availability benchmark.
UTC evidence timestamps fall on 22 October 2026; completion is 23 October locally.

## Automatic source build and healthy promotion

Jenkins build 1 was started by its scheduled SCM poll, with the recorded cause
`hudson.triggers.SCMTrigger$SCMTriggerCause`. No manual build submission, Argo
refresh, rollout retry or manual promotion was used. The independent observer
waited for that build and supplied the synthetic candidate traffic required by
the experiment's minimum-traffic policy.

- Source: `56929baf3d545ed8781182514b250bc1bf268484` from GitHub `main`.
- Image: `sha256:a420e39025d72b8ebc2aac65bce13aaa53d56feee1144eb8c87987432c575928`.
- Environment commit: `2cf84d955f93f041444ccfce6ddfde93c833b45a`.
- Evidence: `output/gitops-healthy-20261022T184901Z`.
- Result: `candidate-promoted-through-gitops`, 2,845 stable HTTP observations,
  zero non-200 responses, and the matching source/release revision serving.

The build passed all 20 tests, the HIGH/CRITICAL vulnerability gate, SBOM creation,
digest publication and the environment push. Argo CD detected the new environment
commit through normal polling/cache expiry; Rollouts approved it after fresh
candidate-specific error-rate and latency analysis. The full report and scanner
database metadata are in the immutable evidence store. Observation started during
setup, so its duration/count is not a source-to-production latency benchmark.

## Fault rejection

The HTTP-error trial submits a controlled `DEMO_MODE=error` build using the same
GitHub source job. This fault is deliberately selected by a build parameter;
it is not a separate source commit. CI should publish the artifact, then the
candidate's analysis must fail while the previous healthy stable service remains
unchanged. A successful Jenkins build does not mean a successful deployment.

Build 2 passed the same 20 tests and scan gate, published image
`sha256:a7d33285070fca79b018919bff31d36e6257b16c72505281724958fd22b2c90d`
and environment commit `3b72660e37c666f6590fed096711d502b348ed6b`.
`output/gitops-error-20261022T190045Z` records
`candidate-rejected-through-gitops`, failed analysis and an aborted candidate.
All 754 stable observations returned HTTP 200; selector `579d4bff48` continued
serving the healthy `56929baf3d545ed8781182514b250bc1bf268484-jenkins-1` revision.
No manual promotion, workload apply or environment rollback was used.

Both trials are automatically archived outside the checkout. Their reports
distinguish the scheduled SCM cause of build 1 from the authenticated fault
injection request for build 2. The acceptance-record source commit is followed
by another observed SCM-triggered healthy release to leave desired and serving
state healthy after the rejected candidate. Its final report is retained under
`output/gitops-healthy-*` and the evidence catalogue.

## Setup defects found and fixed

An earlier setup had created an empty Jenkins job before failing on an unsupported
Git-plugin setter. Bootstrap now repairs existing incomplete jobs, constructs
GitSCM with an explicit main-branch list, and installs the polling trigger. The
live configuration was checked for the SCM definition, `*/main` and two-minute
schedule before observing the scheduled build. The constructor follows the
[Git plugin API](https://javadoc.jenkins.io/plugin/git/hudson/plugins/git/GitSCM.html).

The official Trivy database transfer through the Windows filesystem mount failed
with `Cannot allocate memory`. Streaming from Windows stdin to Linux and verifying
its SHA-256 there succeeded. `fetch_trivy_db --stage-in-wsl` now provides that
path; the importer reports actionable copy errors and still rejects expired data.
The database used here was updated at `2026-10-22T13:15:26Z` and expires at
`2026-10-23T13:15:26Z`. Scanning was never bypassed.

## Remaining acceptance

- Jenkins-driven latency, readiness, missing-traffic and telemetry-outage trials.
- Full controller/agent rebuild from all locks and fresh-machine reproduction.
- Serialization covering both jobs and the complete analysis/recovery lifetime.
- The later [post-promotion milestone](post-promotion.md) now verifies serving
  analysis, automatic recovery and explicit failed-write/restart/retry handling.
- Independent build host, verified TLS registry and off-machine backups.

The original engine-only fault evidence remains in [live validation](live-validation.md).
It must not be relabelled as GitHub/Jenkins acceptance.
