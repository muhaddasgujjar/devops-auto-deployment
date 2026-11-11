# Milestone 9: laptop transfer preparation

This milestone prepares portable source and an independent-machine acceptance
path. It adds no progress points: the scoped MVP remains **83%** until independent
reproduction or the outstanding human prerequisites are actually accepted.

Deliverables are the [transfer guide](../machine-transfer.md), read-only
`scripts.machine_inventory`, verified `scripts.export_transfer`, and
[target acceptance worksheet](../target-machine-acceptance.md). No hosted remote,
paid service, external notification or new lab deployment is introduced.

The exporter requires a clean commit, refuses an existing destination, creates a
Git bundle of all refs, verifies it and performs an independent temporary clone,
full fsck, clean-worktree check, HEAD/tree comparison and referenced-object checks.
The receipt records the exported source SHA and bundle SHA-256. Runtime archives,
credentials, ignored raw results and container images are not bundled. Export
receipts are recorded separately after the exported source commit; a bundle
cannot include its own final hash receipt.

The laptop inventory is only a reference, not a claim about the other machine.
Setup notes now reflect schema `0003_monitoring`, separate backend dependencies
and serialized local Jenkins operation. Fresh-state initialization is separate
from isolated historical archive verification.

Two integration prerequisites remain explicit: the old ledger cannot silently
adopt a new Rollout UID/Jenkins sequence, and fresh-machine recovery requires
new accepted target enrollment evidence. The existing target recorder depends
on ignored laptop artifacts. These are not solved by cloning Git or copying a
database. Continuing the old ledger needs an explicit migration; a clean runtime
needs fresh target acceptance. See the transfer guide for the boundaries.

Interviews, supervisor acceptance, second-user pilot and desktop/narrow visual
review remain open. No browser automation was attempted in this milestone.
