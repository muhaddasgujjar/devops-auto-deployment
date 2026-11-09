# Source baseline and reuse decision

Superseded by the actual history-preserving merge described in
[merged project status](merged-project-status.md). The older implementation is now
canonical; the foundation sample was relocated under `examples/foundation`.
The table below records the pre-merge differences, not outstanding duplicate projects.

Audit date: 9 November 2026.

## Authoritative source

Use this Windows Git repository for new work. Retain `/opt/release-lab/source-snapshot` at its existing commit as a historical integration reference. Do not replace it, switch an existing Jenkins job to this checkout, or copy its folders over the current source. Local baseline version control is required before any CI adoption. A remote backup is a later configuration step; a local commit is not an off-device backup.

The foundation baseline is versioned on `codex/foundation-baseline`. Repository attributes keep text checkouts in LF format so Windows Git settings cannot silently alter Linux scripts and the runtime receipt hashes. Scratch files, kubeconfigs and private keys are excluded.

The read-only audit records the historical commit, worktree cleanliness, file hashes, and collisions in `docs/evidence/source-reconciliation.json`. The November 3 receipt manifest covers 11 foundation files; all matched at the start of this audit. This establishes source continuity for those receipts, not runtime health on November 9.

The README was subsequently updated with progress links. The audit lists that documentation change separately and gates its exit status on the ten runtime/test/configuration files, preserving the historical receipt hashes rather than overwriting them. The new source-audit utility is outside that historical validation set.

## Reviewed integration mismatches

| Contract | Historical snapshot | Current authoritative checkout | Required integration change |
|---|---|---|---|
| Application entry | `demo/app.py` and `python -m demo.app` | `demo/app/server.py` | Change CI build context/entry, not a directory overlay |
| Dockerfile | `demo/Dockerfile`, root build context | `demo/app/Dockerfile`, app context; required PYTHON_IMAGE argument | Read current versions.json and supply the base digest |
| Fault modes | `error`, `startup` | `errors`, `unready` | Map scenario inputs explicitly |
| Workload endpoint | `/` | `/api/work`; `/` is metadata | Send analysis load to `/api/work` |
| Request counter | `demo_requests_total` | `demo_work_requests_total` | Update PromQL, load clients, and analysis tests together |
| Duration histogram | `demo_request_duration_seconds` | `demo_work_duration_seconds` | Update histogram query and test latency boundary |
| Revision labels | Added by historical pod scrape configuration | Sample emits revision label itself | Define scrape relabeling/honor_labels so revision identifies the actual candidate |
| Namespace | `demo-dev` | Disposable `release-foundation` baseline | Create a deliberate GitOps target; do not silently adopt an owned workload |
| Policy | Historical analysis uses failureLimit 0 | Proposed baseline discusses repeated failures | Choose one policy, update SRS, and test exact abort semantics |
| Version file | Keys for CI, controller, scan, and cluster tools | Sample-image/base pins only | Add reviewed engine/tool pins before using historical installers |
| SCM branch | Historical Jenkinsfile requires `origin/main` | Local baseline has no configured remote | Configure trusted branch and verified remote before calling this SCM-triggered CI |

The old Jenkinsfile has useful serialized stages, scan gates, digest publication, and an SSH environment publisher. The old manifests and scripts can shorten the next milestone, but they do not work unchanged against the current workload contracts. Historical cached images or database containers do not establish a completed current API or portal.

## Porting order

1. Preserve both lineages and create a local Git baseline for this checkout.
2. Adapt the image builder, load client, and Prometheus queries as one reviewed contract change.
3. Add a current-version tool inventory and a dry-run environment renderer that requires an immutable registry digest.
4. Validate one test/build/scan/push path against a dedicated local environment repository. Require a failed test to prevent publication.
5. Hand that directory to Argo CD and run healthy/error/no-data trials. After handoff, CI must not directly apply the same workload.

No production identity, secret, Git remote, registry endpoint, or completed customer interview is inferred from the historical setup.
