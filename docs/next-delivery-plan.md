# Next delivery plan

Continue with this single merged repository. Finish laptop acceptance before
cloning it to the other machine. Use existing hardware and local open-source
services; this plan requires no paid cloud account. Hardware, electricity and
network access remain the user's resources.

## Close early gaps first

1. Preserve milestone 7's passing error/latency receipts and excluded clock-invalid
   attempts. Verify time before further experiments. Recovery, database
   migration/restore rehearsal, restricted roles, scoped collection, backend CI
   and same-origin authenticated portal prerequisites are implemented and checked.
2. Conduct the five planned user interviews and a second-user portal pilot.
   Capture concrete tasks, observations, usability problems and acceptance in
   the repository's research records. Obtain supervisor agreement that blue/green
   extends the original rolling-update requirement. These need real people;
   generated responses cannot substitute for them.
3. Review the new recovery history screen with a second user at desktop and
   narrow widths. Build/API checks cover the extension; new visual acceptance
   remains open.

## Milestone 8: durable monitoring and local notifications

Implement one small piece at a time on the 8 GB laptop, with builds serialized
against cluster-heavy validation.

| Order | Deliverable | Acceptance |
|---|---|---|
| 1 | Retained Prometheus storage and explicit capacity/retention limits | A known metric range survives pod recreation; document limits and disk use |
| 2 | Versioned alert rules and a small read-only dashboard | Desired/stable identity, candidate rejection, post-promotion incident, recovery failure and telemetry loss remain distinct |
| 3 | Durable notification outbox and a local test receiver | One logical notification per transition, bounded retry/backoff, receiver-outage handling and restart deduplication |
| 4 | Platform backup manifest covering database, environment Git and declarative configuration | Restore into an isolated target and verify Git refs, incident/audit identity and API state; retain backup hashes |
| 5 | Laptop acceptance and operator runbook | Prove persistence, alert firing/resolution, unavailable receiver and restore; stop owned services and preserve data |

Keep secrets outside Git. Notifications should initially go to the local test
receiver. Actual email/chat delivery requires the user's chosen destination and
explicit authorization. Add dashboard/alert services only within measured RAM
limits; optional components can be started for their own acceptance and stopped
afterward.

## Then move to the other machine

Clone this repository rather than creating a second project. Recreate credentials
and use pinned dependencies there; do not copy runtime passwords, service tokens
or laptop SSH keys into Git. Follow the fresh-machine setup and verify CPU, RAM,
disk, Linux/container support and registry reachability. GPU capacity is not
required for the current release-platform workload.

Use that machine for the heavier checks: isolated trusted builds, TLS registry,
controller restart/concurrent delivery, external SCM configuration once its
repository is chosen, and a clean install/restore. Retain the laptop setup as a
reference until reproduction passes.

Finally run repeated, comparable healthy/fault/recovery experiments. Fix traffic,
resource limits and measurement boundaries, report all attempts and exclusions,
then calculate distributions. Two successful functional scenarios alone do not
justify p50/p95 recovery or availability claims.
