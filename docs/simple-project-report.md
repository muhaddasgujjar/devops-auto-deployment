# Project report — 12 November 2026

**Project:** A safer way to release software updates.
**Progress:** Approximately **83% of the agreed prototype is complete**.
This estimates completed features, not production readiness.

**The problem:** A faulty update can break an application that was working.
Our project tests the new version while keeping the working version available.

**What works:**

- Automatic building, testing and checks for known security issues.
- Healthy updates can be released; faulty candidates can be rejected.
- Recovery can restore an enrolled, previously accepted version after a problem.
- A dashboard displays releases, recovery history, monitoring and alerts.
- History and local notifications are saved. Backups were restored and checked.
- One combined project is published on GitHub with transfer instructions.

**Proof so far:** Recorded local experiments include healthy releases, rejected
faults and recovery from errors/slowness. The latest accepted backend build passed
88 tests. Historical monitoring survived a restart. Notification retries did not
create duplicate inbox entries. An isolated restore matched all 17 database tables.
These are prototype checks on our laptop, not a real-company availability guarantee.

**Remaining work:** User/supervisor feedback, visual review, new-machine setup and
verification, easier enrollment of recovery targets, stronger network/build
isolation and repeated final evaluation. GPU memory does not replace system RAM.

**Presentation on 13 November:** Show the application and dashboard, recorded
successful/rejected releases, recovery history and monitoring/backup results.
Explain which data is historical and which observation is live. Live experiments
are optional and take several minutes.

**Cost:** No paid cloud subscription is required for the local plan. Existing
hardware, electricity and internet are still needed.

[Run and demo guide](demo-guide.md) · [Detailed progress](progress-after-monitoring.md)
