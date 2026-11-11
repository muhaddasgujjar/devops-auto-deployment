# Milestone 9: laptop transfer preparation

Technical transfer preparation **passed on 11 November 2026**. Human prerequisites
and target-machine acceptance remain open.

Verified export source: `494feb6a87e542ffcc850e3f5b6afa7d7f7f993b`.
Bundle: `output/transfer/494feb6a87e542ffcc850e3f5b6afa7d7f7f993b/release-platform.bundle`
(496,184 bytes). SHA-256:
`9fcb2d02744b33ecf491ac7c0d192a57a29301d0b2ec7cc6a71962581cec8e0e`.
The same folder contains `transfer.json`. Copy both files together.
See [actual verification](../evidence/transfer-acceptance.json) and
[laptop reference inventory](../evidence/transfer-laptop-inventory.json).
The Windows inventory reported 8,425,529,344 bytes RAM and eight logical CPUs;
these values describe this laptop, not the other machine or GPU memory.

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

The source export and clone passed without starting the lab. The overwrite
refusal preserved the original bundle hash. Documentation links and receipt JSON
were checked. No backend runtime source changed; the earlier 88-test runtime
acceptance is historical and was not rerun or claimed as a new-machine pass.
