# Local release portal

The React/TypeScript portal is served by the same FastAPI process as the state
API. It reads PostgreSQL-backed evidence; it contains no sample release fixtures.
Overview distinguishes desired candidate from recorded stable revision. Releases
and builds show the latest 100 records, with search and decision filters. Details
retain candidate analysis, image/commit identities, original artifact hashes and
excluded HTTP observation reasons. Download record exports the normalized API
record; original scan/SBOM files remain in the CI archive. Admin sessions alone
can read audit entries. No promotion or recovery controls are exposed.

## Build and run

From the repository in Windows PowerShell:

```powershell
npm ci --prefix frontend --ignore-scripts
npm test --prefix frontend
npm run build --prefix frontend
```

From the same repository in Ubuntu/WSL, with the provisioned backend environment:

```sh
/opt/release-lab/venv/bin/python -m scripts.backend_runtime start
/opt/release-lab/backend-venv/bin/python -m scripts.install_backend_services
systemctl start release-state-api.service
```

Open http://127.0.0.1:8090/ and enter your role's key from the protected local
credential store. The operator provisions/distributes these keys; the portal
does not create accounts or display keys. Do not put keys in URLs, screenshots,
source, shell arguments or public logs. The immutable service installer requires
committed backend/frontend source and a compiled bundle matching those exact
source inputs and asset hashes. A stale or changed bundle fails installation.

Starting the API alone displays the most recently recorded state. For current
cluster observation, start the lean lab, refresh the one-hour observer token and
start the collector using [the service runbook](backend-hardening.md). No cluster
or Jenkins is needed simply to inspect retained records. Stop services/database
after use to preserve laptop memory:

```sh
systemctl stop release-state-collector.service release-state-api.service
/opt/release-lab/venv/bin/python -m scripts.backend_runtime stop
```

## Sessions and truthfulness

The API exchanges a role key for an opaque HttpOnly, SameSite=Strict cookie.
Only its hash, the key hash and a CSRF token are retained in bounded process
memory. The portal does not use localStorage/sessionStorage for credentials.
Browser password managers may independently offer to save a typed key; this is
outside the portal's storage behavior. Cookie-authenticated writes, including
logout, require exact loopback Origin and a CSRF token. API-key clients and HMAC
collector callbacks retain their existing contracts. Every request checks the
current server role; hiding a navigation item is not an authorization boundary.

Sessions expire after one hour or 15 minutes without authenticated requests.
Visible-tab polling counts as activity. Restarting the single API worker signs
everyone out; multi-worker/shared sessions and production TLS are future work.
Key/role configuration is loaded at API startup. Restart after changing it;
there is no public account-management or session-revocation console.
Loopback HTTP is this milestone's scope. Remote login origins are rejected.
Ten sign-in attempts per minute per client address are allowed; request bodies,
session count and throttle memory are bounded. There is no public registration.

Records refresh every 15 seconds while the tab is visible, with a ten-second
timeout per request. API failures retain the last complete loaded snapshot and
show an explicit warning. Source unavailable, historical and stale observations
are different states. Only a current observation is captioned "Serving traffic";
older evidence is "Last recorded stable". Missing scans stay unknown, empty
metric vectors stay "No result", and excluded HTTP samples stay excluded.
Lists are bounded snapshots rather than an unlimited searchable archive.

## Verification and packaging

`scripts.validate_backend` exercises real PostgreSQL with restricted roles,
including cookie/role/CSRF/origin/expiry/rotation and credential non-disclosure.
Frontend presentation tests cover missing evidence, empty metric vectors,
units, excluded samples and freshness. `scripts.accept_portal` checks the actual
installed service with protected keys, comparing every served asset hash and
verifying read/admin permissions and logout. It prints no keys or cookies.

The backend Docker build compiles/tests the portal with pinned Node and npm lock
dependencies. A production npm HIGH/CRITICAL audit blocks publication. The final
non-root Python image contains compiled assets, without Node, node_modules or
test fixtures. CI boots that exact runtime, verifies served asset hashes and
unauthenticated data denial, then runs its existing OS/Python scan and SBOM gate.
An npm audit covers the compiled application's dependency graph; Trivy's runtime
OS/Python SBOM does not claim to enumerate bundled JavaScript modules.

`scripts.preview_portal` is an optional visual-QA helper. It restores a disposable
copy of real records and accepts public fixture keys defined in that script.
Those keys are never installed in the real service. Run with the protected
`RELEASE_BOOTSTRAP_CONFIG_FILE` set, inspect port 8093, and stop with Ctrl+C/SIGTERM.
Cleanup drops only its generated preview database/config; the real database is
unchanged. A backup remains in ignored output. This helper is not a deployment.
SIGKILL, host shutdown or a forced WSL stop can interrupt that cleanup. Preserve
the generated config/database for diagnosis and verify its exact fixture identity
before removing an abandoned preview; never clean the main database or volume.

The frontend is MIT-licensed React/React DOM with Vite and TypeScript tooling.
No cloud account, paid model, external font, image service or subscription is
required. Existing hardware, storage and electricity remain real operating costs.
