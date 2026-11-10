# Milestone 6: authenticated real-data portal

10 November 2026. Local implementation, PostgreSQL/session tests, packaged CI
gates and installed-service acceptance passed. Visual-review scope and shutdown
are recorded with the acceptance evidence below.

The React/TypeScript interface now reads the same durable state API as the
collector. It shows desired versus stable release, searchable release/build
history, immutable source/image identities, recorded scan/SBOM hashes,
candidate analysis and HTTP observation quality. Audit entries require an admin
session. Users can copy identities and download a normalized release record.
There are no promotion/recovery action buttons.

Sessions use opaque HttpOnly/SameSite cookies, bounded server memory, key-hash
role checks, same-origin login and CSRF protection for cookie-authenticated
writes. The application does not persist role keys in browser storage/bundles.
Expiry, logout, restart invalidation, login throttling and body limits are
covered. Existing API-key clients and signed collector callbacks still pass.

| Gate | Accepted evidence |
|---|---|
| Core/demo regression | 54 tests pass |
| PostgreSQL/API/session/worker | 47 tests pass, no skips |
| Frontend presentation | 5 tests pass; missing scans/metrics and excluded samples stay explicit |
| Build | TypeScript and Vite compile successfully; Windows and Linux produce the same three asset hashes |
| Negative Jenkins gate | Build 5 runs 48 tests with exactly one intentional failure; no scan/SBOM or registry tag |
| Positive Jenkins gate | Build 6 passes 47 tests, boots UID 10001, verifies served portal hashes and unauthenticated data denial, then scans/publishes |
| Dependency gates | Production npm audit and Trivy OS/Python scan report zero HIGH/CRITICAL findings |
| Installed local service | Same verified bundle served by immutable snapshot; read audit denied, admin audit allowed, CSRF enforced, logout revokes access |
| Real collector compatibility | Supervised collector observes current build 17 through existing read/HMAC contracts; desired/stable both 17, state version 15 at the initial live acceptance |

Reviewed CI and installed API source:
`8d1faef9b1039031e1587032dcf9fe3b70b37802`.
Published image:
`localhost:5001/release-state@sha256:aee2bb83a397b9d989bf0af9c4bda2e23b1a9284578e1ff5604da67a6a3601db`.
OCI config digest:
`sha256:7f3c2a60174f287ee2f8ade38cfca12d9c559d55aa897a68d5fc79ca011a93dc`.
Frontend input fingerprint:
`d0adc3427da0f3111c3b83b6bacaaa5898984579c29470a941cda6fbf3ea8d7a`.
The runtime OS/Python CycloneDX SBOM has 63 components; bundled JavaScript is
covered by its npm lock/audit receipt, not claimed as part of that Trivy SBOM.

The final API-only installation check used environment version 31, with the
collector deliberately stopped and freshness correctly reported as stale.
Desired/stable remained build 17, with 10 releases and 11 builds. The earlier
current-observation receipt uses the first portal snapshot, whose backend and
compiled JavaScript are identical to the final one; the final change adjusts CSS.

## Evidence and operation

- `docs/evidence/merge-validation.json`: 54 core/demo tests.
- `docs/evidence/backend-tests.json`: 47 PostgreSQL/session/worker tests.
- `docs/evidence/frontend-tests.json`: 5 presentation tests with raw TAP hash.
- `docs/evidence/backend-ci-acceptance.json`: independent negative/positive
  Jenkins, registry byte/digest, runtime identity, scan, SBOM and frontend proof.
- `docs/evidence/portal-service-acceptance.json`: real installed-service checks.
- `docs/evidence/portal-live-observer-acceptance.json`: earlier live collector/UI
  compatibility proof with current observation, retained separately from the
  final static-bundle installation check.
- `docs/evidence/portal-visual-review.json`: observed browser scenarios and the
  explicit final-visual-recheck limitation.
- `docs/evidence/portal-build.json`: final compiled asset/source hashes.
- `docs/evidence/portal-closeout.json`: stopped services/containers, preview
  cleanup and agreement between CI, installed service and compiled bundle.
- [Portal runbook](../portal.md): build/start/stop, credentials and session limits.
- [Progress and next milestone](../progress-after-portal.md): weighted estimate
  and the ordered post-promotion recovery plan.

Milestone 5's 32-test/older-image receipts are preserved separately as
`backend-tests-milestone5.json` and `backend-ci-milestone5.json`. Its service
restart/restore proof remains historical. The new backend job does not deploy
the demo; the proven demo job/source and environment Git are unchanged.

API, collector, working PostgreSQL, cluster, CI and registry are stopped after
acceptance. Persistent volumes, backups and immutable source snapshots are
retained. The disposable fixture preview database/config was cleaned up; the
earlier database on 5433 remains untouched. Repository commits remain local.

## Practical limits

This is a local single-environment MVP: loopback HTTP, one API worker and
process-local sessions. Restart signs users out. TLS, external SCM/PR isolation,
SSO/multi-tenancy, remote hosting and fresh-machine reproduction remain open.
History is bounded to the latest 100 records in each list. Original artifacts
remain in CI archives. Visibility does not provide post-promotion recovery.

The existing k3d post-start log wait timed out; the independent Kubernetes
controller readiness gate subsequently passed. Installed-service verification
initially raced API startup; the checker now waits for readiness within a fixed
30-second deadline. Neither was counted as successful until its real gate passed.

Real Chrome review covered read-role audit denial, admin audit entries, current
versus stale observations, release search, build 5's failed CI/no-release state,
and release 12's excluded 538-second sample gap. Pausing the disposable preview
API showed an outage warning while retaining records; resuming restored refresh.
Desktop, a 371-pixel emulated viewport and a narrower actual window were inspected.
The final CSS adjustment constrains flex children/document overflow while tables
retain their own horizontal scrolling. Its final visual reload was blocked by
the Windows tool's inability to confidently verify the current browser URL.
Browser automation ended immediately; the final CSS build/package/API checks
passed separately. No final screenshot or automated browser-suite result is
claimed. Existing-profile extension CSP errors were visible during inspection;
the portal's source contains no external scripts, styles or image URLs.
