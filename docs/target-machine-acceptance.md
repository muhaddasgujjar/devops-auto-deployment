# Independent machine acceptance worksheet

Status: **not run**. Source transfer verification does not complete these gates.
Keep receipt files under a new target-specific output directory, with UTC times,
reviewed commit, image digest, actual outcomes and all failed/excluded attempts.

| Preparation field | Actual target value |
|---|---|
| Source SHA and matching copied bundle hash | Pending |
| Linux/WSL OS, architecture and Python | Pending |
| Host RAM / visible Linux RAM / CPUs / free disk | Pending |
| Docker/systemd, pinned tool comparison | Pending |
| Port collisions resolved / clock checked | Pending |
| Resource limits and serial/concurrent profile | Pending |
| Private credentials recreated / archive hashes verified | Pending |

| Gate | Required proof | Result |
|---|---|---|
| Source | Independent clone/fsck and exact commit/tree | Pending on target |
| Core/schema | Run validation and upstream manifest schemas | Pending |
| Backend | Fresh migration, restricted grants and full real-PG suite | Pending |
| CI | Intentional failure cannot publish; positive runtime/scan/SBOM/digest identity matches | Pending |
| Healthy delivery | Real target Jenkins build, Git commit, Argo sync/promotion and matching HTTP responses | Pending |
| Rejection | Bad candidate rejected; serving stable identity and responses preserved | Pending |
| Recovery prerequisite | New healthy target evidence explicitly enrolled; no laptop UID/build-order substitution | Pending engineering/evidence |
| Recovery | Real post-promotion fault restored via Git with matching traffic and durable actors | Pending |
| Notifications | Actual firing/resolution, receiver outage, replay and one inbox receipt per ID | Pending |
| Persistence | Exact historical samples survive pod replacement with unchanged PVC/PV identity | Pending |
| Restore | New isolated DB/Git/API/TSDB/receiver match archive; source unchanged and temporary resources cleaned | Pending |
| Visual/human | Desktop/narrow recovery and monitoring review, real pilot/interviews/supervisor decision | Pending |
| Closeout | Owned services stopped, data preserved, unrelated services untouched | Pending |

Use the commands and measurement limitations in the existing milestone runbooks.
Keep old laptop receipts as historical references. Fresh-machine reproduction,
TLS, isolated external builds, SCM triggers and repeated performance distributions
have separate acceptance; none is implied by completing this worksheet.
