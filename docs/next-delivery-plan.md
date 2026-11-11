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

## Milestone 8: accepted local technical checks

Completed on the 8 GB laptop, with builds serialized against cluster-heavy
validation. See [the evidence report](milestones/08-persistent-monitoring.md).

| Order | Deliverable | Acceptance |
|---|---|---|
| 1 | Retained Prometheus storage and retention limits | Passed: four exact historical series survived pod replacement on the original 2 GiB claim |
| 2 | Versioned rules and read-only dashboard | Six native rule cases and API/assets checks passed; browser visual review remains open |
| 3 | Durable outbox and local receiver | Passed: real outage, bounded retry tests, restart/expired-lease replay and deduplicated inbox |
| 4 | Platform backup and isolated restore | Passed: 17 table fingerprints, Git/configuration, eight receipts, four metric series and separate API |
| 5 | Laptop acceptance and runbook | Live technical checks passed; human/visual acceptance remains open |

Keep secrets outside Git. Notifications should initially go to the local test
receiver. Actual email/chat delivery requires the user's chosen destination and
explicit authorization. Add dashboard/alert services only within measured RAM
limits; optional components can be started for their own acceptance and stopped
afterward.

## Milestone 9: prepare transfer on this laptop

Prepared: [transfer guide](machine-transfer.md), [target acceptance worksheet](target-machine-acceptance.md)
and [milestone record](milestones/09-transfer-preparation.md). Human reviews and
actual target-machine reproduction remain open; progress stays at 83%.

1. Close the early human/visual gaps above. Record actual findings and fix any
   reproducible defects before treating those items as accepted.
2. Export a verified Git bundle of the one merged repository and record its SHA.
   No remote is configured; do not invent a clone URL. A local bundle supports
   `git clone <bundle-path> <new-folder>` on the other machine without publishing.
3. Prepare a fresh-machine inventory and runbook covering pinned tools, Linux and
   Docker, CPU/RAM/disk, registry names, protected secrets, service identities and
   migration order. Backups are private and transfer separately from Git.
4. Define reproduction acceptance: fresh install, clean source/build identity,
   healthy promotion, rejected candidate, recovery, notification replay and
   isolated restore, with receipts from that machine. Do not award reproduction
   credit for a checklist alone.

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
