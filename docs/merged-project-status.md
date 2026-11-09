# One project: merged status and solo delivery plan

Update, 10 November: the later laptop session restored live core health and GitOps
connectivity and added lean startup. See [laptop-first work](laptop-first.md).
The failure observations below remain the dated merge-time evidence.

Date: 9 November 2026. User confirmed the old and new chats describe the same project and will work on it solo for a full week.

## Completion estimate

**Approximately one-third complete: use 33% delivered / 67% remaining for planning.** This is a weighted implementation estimate, not measured labor, an SLA, or an assurance that the remaining work fits in seven days. The previous 20% assessment excluded the older Linux implementation because its relationship to this checkout had not been confirmed. The increase recognizes restored, tested work; it is not a claim that 13% of new product features were written today.

The original MVP denominator is unchanged. Partial points acknowledge integrated code with tests/schema evidence; full points require end-to-end acceptance. Historical experiment descriptions are retained with their dates, but do not substitute for current live validation.

| Workstream | Weight | Earned points | Current evidence and gap |
|---|---:|---:|---|
| Scope, architecture and resource/user validation | 10 | 8 | Scope established; solo one-week availability confirmed; interviews and supervisor review open |
| Unified source and provenance | 5 | 5 | Both Git lineages retained; canonical source selected; merge conflicts resolved; old foundation isolated |
| Lab and workload | 15 | 7 | Containers/workload previously exercised; merged configs validated; current lab is unhealthy |
| CI and artifact supply chain | 15 | 3 | Jenkins/scanning/publishing implementation restored; merged-source live execution pending |
| GitOps | 15 | 3 | Digest-only renderer and temporary Git publication tests pass; actual Application is not Synced |
| Analysis and recovery | 15 | 3 | Analysis templates and harness restored; dated local trials documented; fresh healthy/fault trials pending |
| Monitoring, alerts and persistence | 10 | 3 | Metrics, Prometheus configuration and revision checks restored; current endpoints unavailable; persistence/alerts remain |
| Product API, database and interface | 10 | 0 | Database container alone is not implementation evidence; usable source/API/UI not present in either merged Git tree |
| Evaluation, reproduction and handoff | 5 | 1 | Tests, runbooks and dated observations available; repeated evaluation and complete reproduction remain |
| **Total** | **100** | **33** | **About two-thirds remains** |

## What was actually merged

- New foundation lineage begins at `76057b1`; relocation checkpoint `355cd6f` keeps its workload under `examples/foundation/` and tests under `tests/test_foundation.py`.
- Older lineage is preserved at `492d52d79097486646cfaa3fba135b6515e77259` on `codex/legacy-history`. It was transferred via a local Git bundle, not by replacing the running Linux snapshot.
- The final merge joins both parents on `codex/foundation-baseline`. Jenkins, GitOps publisher, release renderer, analysis templates, monitoring, lab lifecycle, tests, and third-party attribution are part of the same source tree.
- Canonical workload remains `python -m demo.app`, work endpoint `/`, modes `healthy`, `error`, `latency`, `startup`, and the original `demo_requests_total`/`demo_request_duration_seconds` metrics. Existing CI and PromQL therefore keep one consistent contract.
- `versions.json` keeps canonical engine pins and separately names `foundation_python_image` for the historical fixture. The isolated fixture keeps its own endpoint/modes and is not deployed by the canonical pipeline.
- Shared README, Git attributes, ignore rules, architecture and versions conflicts were resolved. Secrets, database contents and kubeconfigs were not imported into Git. No remote was created or pushed.

The canonical root Docker context includes only the intended demo files through `.dockerignore`. The standalone fixture can be built separately with the instructions in `docs/runbooks/local-demo.md`.

## Validation and issues found

1. **25 combined tests passed**: canonical and foundation HTTP behavior, rendering constraints, repository command restrictions, and idempotent publication to a temporary local Git repository. Receipt: `docs/evidence/merge-validation.json`.
2. **18 resources/configurations validated** against the selected upstream schemas. This checks schema compatibility, not a live deployment, image security, or plugin compatibility.
3. The initial combined runner failed imports because direct script execution did not add the repository root to Python's search path. The runner was corrected and all 25 tests passed afterward.
4. The restored Windows launcher now regenerates the existing cluster's ignored kubeconfig into this checkout rather than assuming it migrated from the old chat.
5. The lab doctor now preserves individual health results when optional Argo discovery fails, and explicitly reports a missing GitOps Application instead of treating absence as success.
6. **Current live health check failed.** The node was Ready without memory/disk pressure, but Rollouts and Prometheus lacked availability, stable and telemetry services had no usable endpoints, and Argo CD reported an unreachable SSH Git endpoint. Subsequent API reads also returned ServiceUnavailable. Receipt: `docs/evidence/merged-lab-health.json`. No successful fresh recovery or CI trial is claimed.

The older `docs/live-validation.md`, `docs/current-review.md` and CI integration guide describe historical work and setup, not a fresh full-stack pass. Their dated claims must not be treated as current runtime status. The authoritative source merge does not automatically retarget existing Jenkins jobs or replace their trusted source snapshot.

## Hardware and available time

The inspected computer still reports **7.8 GiB system RAM** and Intel UHD Graphics 620. No NVIDIA utility was found. The user reports a GPU with 16 GB RAM; this may refer to another machine, dedicated GPU VRAM, or available shared graphics memory. It has not been verified as usable from this workspace. GPU memory does not increase the RAM available to ordinary CI/Kubernetes services.

Plan for one contributor, with a seven-day work window; exact daily hours are not assumed. Use serialized builds and avoid heavy scans while measuring availability on the constrained local host. A GPU is unnecessary for the proposed product. If the user means a second machine with 16 GB system RAM, confirm access and allocate it as the build host. Existing hardware can avoid new hosting expenditure; no paid account is required for the lean lab.

## Seven-day plan: prioritize early unfinished work

| Day | Priority and deliverable | Completion gate |
|---|---|---|
| 1 | Source merge complete; diagnose/recover WSL/k3d/controller startup, registry and Git SSH service. Check pod events and container/runtime logs before changing configuration. Preserve cluster and data. Confirm actual system RAM and weekly capacity. | Node/controllers/services healthy; environment repository reachable; repeat start/status without masking failures |
| 2 | Run the merged canonical test/build/scan/push/publish path through Jenkins. Configure trusted source provenance and environment-repo credentials. Adapt the job explicitly to the merged checkout; do not silently overwrite the old snapshot. | Build/evidence links source SHA, scan, digest and environment commit; failed test/scan cannot publish desired state |
| 3 | Confirm Argo CD synchronization and Rollouts ownership. Run healthy, error, latency, readiness, no-traffic and telemetry-outage experiments in series. | Recorded candidate decisions and stable observations; no automatic pass on missing data; failed recovery escalates explicitly |
| 4 | Implement a minimal FastAPI/PostgreSQL release/evidence model, migrations, observation reconciliation and deduplication. Persist existing experiment evidence. | Restart retains history; duplicate/stale events do not create conflicting releases; secrets stay outside records |
| 5 | Build only onboarding, release history and analysis/evidence screens with real API data and basic server-side roles. Integrate a local notification receiver. | Second supported app can be onboarded; unauthorized mutation is rejected; release reason is visible |
| 6 | Test concurrency, observer restart, backup restoration, telemetry gaps and one recovery-failure case. Tighten resource/credential boundaries. | Repeatable evidence for the important failure paths; no fabricated/optimistic status |
| 7 | Fresh-checkout reproduction, repeated comparison trials, second-user demonstration and final documentation. | Working installation guide, actual measured results/limitations, attribution and demonstration recording |

This is an aggressive demo-MVP target. If day 2 or 3 slips, reduce UI scope and defer extra integrations; prioritize a reliable connected delivery/recovery demonstration. Do not call a partial demo the full original product. Production HA and arbitrary untrusted builds remain outside this MVP.

## Human work in parallel

Use the existing interview worksheet for five real interviews. Confirm supervisor acceptance of progressive delivery as an addition to the rolling baseline. Choose a private/off-device Git backup destination. Schedule the second-user pilot after installation works. These activities require actual people or account access; they have not been completed by generating documents.
