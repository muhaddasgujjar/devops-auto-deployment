# Overall progress and early-stage completion plan

Superseded after the user confirmed both chats are one project. See
[merged project status](merged-project-status.md) for the combined estimate and
one-week solo plan. This document preserves the earlier checkout-only assessment.

Assessment date: 9 November 2026. **Approximately 20% of the full MVP is delivered with traceable evidence.** This is a weighted engineering estimate, not a measurement of hours spent, a production-readiness rating, or a claim that 20% of the original calendar has elapsed.

## Scoring basis

Score only the integrated, authoritative checkout and its traceable evidence. Give no runtime completion credit for a template, cached container image, or an unverified historical report. The separate Linux snapshot contains valuable implementation effort, but its reuse requires contract adaptation and fresh acceptance evidence.

| Workstream | Share of full MVP | Earned percentage points | Evidence and remaining work |
|---|---:|---:|---|
| Requirements, architecture, resource/user validation | 10 | 7 | Scope, exclusions, acceptance criteria, architecture, and hardware findings exist; interviews/capacity/pilot outstanding |
| Source provenance and repository baseline | 5 | 5 | Foundation hashes checked, historical lineage inventoried, reuse contracts documented, local Git baseline established |
| Reproducible lab and workload | 15 | 6 | Native/container checks and a two-pod manual baseline passed; provisioning, TLS registry, secret lifecycle and fresh-machine setup remain |
| Real CI and artifact supply chain | 15 | 0 | No accepted current-source commit-to-build/test/scan/push trace |
| GitOps release delivery | 15 | 0 | No accepted current-source environment-commit-to-Argo reconciliation trace |
| Automatic release analysis and recovery | 15 | 0 | Fault modes exist; no current integrated recovery/no-data/recovery-failure validation |
| Monitoring, notifications and persistence | 10 | 1 | Sample metrics exist; monitored release pipeline, dashboards, alert delivery and persistence remain |
| Product API, database, UI and access control | 10 | 0 | No validated implementation in this checkout |
| Final evaluation, reproduction and handoff | 5 | 1 | Local test receipts/runbooks exist; repeated comparative trials, backup restore and second-user handoff remain |
| **Total** | **100** | **20** | **Approximately 80% remains** |

The rubric is an explicit planning judgement. Fix the weights until scope changes; award points when the corresponding acceptance evidence is available. A single-node lab is not production HA. Full production readiness is outside this MVP denominator.

## Findings checked during this assessment

- All 11 source hashes in the November 3 foundation manifest still matched. That supports the relevance of the earlier 8 native tests, 3 Docker scenarios, and 2-ready-pod manual check; it does not mean those live checks ran again today.
- Historical Linux snapshot commit and cleanliness were checked and the tracked source inventoried read-only. See [source reconciliation](source-reconciliation.md) and its [receipt](evidence/source-reconciliation.json).
- Important mismatches were identified: workload path, fault names, metric names, Docker build context, version keys, namespace, scrape labels, and policy semantics. Blind copying would break the integration.
- No remote backup is configured. A local commit makes changes recoverable locally; it does not protect against disk loss.
- No interviews or second-user pilot are recorded. No team capacity or additional lab machine is confirmed.

## Priority zero: close early gaps first

| Early gap | Action | Owner | Status / exit condition |
|---|---|---|---|
| Competing source lineages | Select this checkout as authoritative; preserve the historical snapshot; record explicit porting contracts | Engineering | Audit and reconciliation decision completed |
| No repository checkpoint | Commit reviewed source/docs/evidence locally using the configured Git identity; exclude secrets and scratch state | Engineering | Local baseline established; verify `git log` and clean status |
| No transparent overall progress | Use the stable rubric and acceptance gates above | Engineering | Completed; future scores require evidence |
| Host capacity decision | Use the existing WSL runtime for serial lightweight checks. Avoid running Jenkins, portal, database and full monitoring concurrently on the 8 GB host | Engineering/user | Lean local profile selected; additional Linux/lab capacity still unconfirmed |
| Interviews | Conduct five interviews using the existing worksheet; retain uninterested answers | User with real participants | Open; engineering can continue, but market demand must remain unvalidated |
| Team availability | Record actual contributors, weekly hours and skills; reschedule work accordingly | User | Open; no calendar commitment until confirmed |
| Academic requirement interpretation | Preserve rolling updates as baseline and explicitly document blue/green as an extension | Engineering/supervisor | Baseline preserved; supervisor review remains open |
| Off-device source backup | Select intended Git host/account and set up a reviewed remote without exposing credentials | User/engineering | Open; no remote or publishing destination assumed |

The early technical organization gaps can be closed locally. Interviews, access to other hardware, and external academic acceptance require real human input. Do not invent them or block all implementation while they are pending. The second-user installation pilot is scheduled after a reproducible installer exists.

## Ordered implementation gates

Effort ranges are focused engineering days, not calendar promises. Capacity, familiarity and available hardware can change them substantially. They do not replace the unconfirmed two-person/week-hours assumption in the original assessment.

### Gate 1: finish source adoption and lab reproducibility (2-4 days)

Port reviewed Linux components into this checkout in small changes. Adapt the sample image builder, load endpoint, metrics queries and fault-mode mappings together. Add reviewed tool versions and an idempotent inventory/preflight that verifies the selected context, ports, disk and memory. Avoid a second cluster. Establish local TLS registry/push/pull trust, scoped permissions, secret handling and a configuration backup plan.

Exit: another clean checkout can run the supported setup procedure; every node can pull the sample image by registry digest; no secrets enter Git; previous workload ownership is preserved. Do not count a pre-existing running cluster as reproducible provisioning.

### Gate 2: connect the real CI/GitOps path (4-6 days)

Configure a trusted source branch, isolated Jenkins execution, tests, image build, scan policy/SBOM, registry publishing and digest resolution. Use a separate environment Git repository with restricted publisher and reader identities. Argo CD owns reconciliation; Jenkins does not apply the same workloads directly.

Exit: a real source commit traces through build ID, scan result, image digest, environment commit and observed deployment. A failing unit test leaves the environment revision unchanged. Distinguish a local manual acceptance job from an SCM-triggered job. Retry/concurrency controls must prevent stale publication.

### Gate 3: observability and recovery vertical slice (3-5 days)

Scrape candidate/stable revisions, enforce minimum traffic and fresh samples, choose explicit promotion/abort thresholds, retain stable capacity, and integrate a local notification receiver. Validate healthy, error, latency, unready, missing traffic and telemetry-outage cases. Define post-promotion coverage and failed recovery behavior.

Exit: healthy promotion and faulty candidate rejection with independent stable-service observations, exact decision evidence and measured timings; no automatic pass on absent telemetry. Only then describe automatic recovery as implemented.

### Gate 4: custom product API and interface (7-10 days)

Build FastAPI/PostgreSQL models and migrations, role enforcement, durable event deduplication, per-environment serialization and restart reconciliation. Add onboarding, release history and recovery-evidence screens. Link to CI logs/monitoring rather than rebuilding them.

Exit: a second supported application can be onboarded; unauthorized mutation is denied; duplicate/stale events cannot change the wrong release; restart recovers observed state. The existing database container alone is not credit for this gate.

### Gate 5: hardening and final evaluation (4-6 days)

Make evidence/metrics persistent; verify backup restoration and credential rotation; run comparative repeated trials against manual and probes-only baselines; report sample counts and p50/p95 timings. Reproduce on a fresh environment and perform the second-user pilot. Fix documentation from actual observations.

Exit: reproducible installation, measured limitations, restored backups, evidence-backed final report and handoff. No claim of guaranteed zero downtime or production HA from finite lab tests.

## Next working session

Start Gate 1, using the reconciliation table as the porting checklist. Keep the portal out of scope until the commit-to-running-release and recovery paths have real evidence. Update this assessment after each gate, not after merely creating files.
