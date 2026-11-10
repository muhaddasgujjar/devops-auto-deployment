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
| Negative Jenkins gate | Build 3 runs 48 tests with exactly one intentional failure; no scan/SBOM or registry tag |
| Positive Jenkins gate | Build 4 passes 47 tests, boots UID 10001, verifies served portal hashes and unauthenticated data denial, then scans/publishes |
| Dependency gates | Production npm audit and Trivy OS/Python scan report zero HIGH/CRITICAL findings |
| Installed local service | Same verified bundle served by immutable snapshot; read audit denied, admin audit allowed, CSRF enforced, logout revokes access |
| Real collector compatibility | Supervised collector observes current build 17 through existing read/HMAC contracts; desired/stable both 17, state version 15 at acceptance |

Reviewed CI and installed API source:
`13149ad24842a298f8dedeb2a1ab37707ab78c64`.
Published image:
`localhost:5001/release-state@sha256:99049286b28fd422cb14c4fabae6e795e234d95e231ce95682e1978eac8e2d33`.
OCI config digest:
`sha256:4a2891863c8c10e2ffe789ec89621d3dabd48e9404dbdda6c8fa4f97011c02f5`.
Frontend input fingerprint:
`1edfb5eb2dc083fc9f9cef400ffd22a42d4ab25c7f500128c7e1690a5c427029`.
The runtime OS/Python CycloneDX SBOM has 63 components; bundled JavaScript is
covered by its npm lock/audit receipt, not claimed as part of that Trivy SBOM.

## Evidence and operation

- `docs/evidence/merge-validation.json`: 54 core/demo tests.
- `docs/evidence/backend-tests.json`: 47 PostgreSQL/session/worker tests.
- `docs/evidence/frontend-tests.json`: 5 presentation tests with raw TAP hash.
- `docs/evidence/backend-ci-acceptance.json`: independent negative/positive
  Jenkins, registry byte/digest, runtime identity, scan, SBOM and frontend proof.
- `docs/evidence/portal-service-acceptance.json`: real installed-service checks.
- [Portal runbook](../portal.md): build/start/stop, credentials and session limits.
- [Progress and next milestone](../progress-after-portal.md): weighted estimate
  and the ordered post-promotion recovery plan.

Milestone 5's 32-test/older-image receipts are preserved separately as
`backend-tests-milestone5.json` and `backend-ci-milestone5.json`. Its service
restart/restore proof remains historical. The new backend job does not deploy
the demo; the proven demo job/source and environment Git are unchanged.

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
continue separately. No final screenshot or automated browser-suite result is
claimed. Existing-profile extension CSP errors were visible during inspection;
the portal's source contains no external scripts, styles or image URLs.
