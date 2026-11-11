# User pilot and supervisor scope review

Status: **not conducted / not approved**. This is a worksheet for real people,
not a record of completed validation. Keep the five interviews in
[user research](user-research.md) separate from this task-based pilot.

## Second-user pilot

Use a disposable copy of the real records and its read-only fixture key, rather
than sharing the working lab's operator credentials. Explain that this is a
local release-platform prototype and obtain permission to record task outcomes.
Use a participant code and role; personal contact information is unnecessary.
Let the participant attempt each task before explaining the answer.

Participant code: **pending** · role: **pending** · date: **pending**

| Task | Evidence to look for | Observed result / help needed |
|---|---|---|
| Identify desired and serving versions | Environment view and observation freshness; CI success is separate from promotion | Not conducted |
| Explain a rejected candidate | Candidate decision and unchanged serving stable identity | Not conducted |
| Find an excluded experiment | Build 12's excluded client observation and sampling gap | Not conducted |
| Compare a failed and successful recovery | Origin 18's terminal failure versus origin 20's accepted recovery to build 16 | Not conducted |
| Explain alert state versus delivery state | Monitoring view: firing/resolved alerts, delivered notices and retry counts | Not conducted |
| Inspect evidence without admin rights | Read role can inspect history but cannot view admin audit or mutate delivery/recovery | Not conducted |
| Use the recovery/monitoring views in a narrow window | Readability, accessible labels, scrolling and no clipped primary controls | Not conducted |

Record task completion, approximate time, confusion in the participant's own
words, and the help provided. Ask which single change would make the product
more useful. Keep negative findings. Record bugs as concrete reproducible steps
and retest changes with the participant; do not turn developer screenshots into
second-user approval.

Pilot outcome: **pending** · accepted improvements: **pending**

## Supervisor decision

Present the original proposal/PRD, the rolling baseline, the current architecture
and the actual milestone receipts. Request a dated decision on:

- Whether blue/green is accepted as an extension while retaining the original
  rolling-update comparison.
- Whether the single-environment, manually started, local self-hosted MVP meets
  the agreed project boundary.
- Whether two functional fault/recovery examples are sufficient for the current
  demonstration, with repeated timing distributions still outstanding.
- Which remaining work is required for assessment: independent-machine setup,
  isolated builds, TLS, external SCM triggers, interviews and final evaluation.
- Whether the local notification receiver is sufficient for the demonstration;
  actual external delivery needs a separately chosen destination.

Supervisor decision: **pending** · date: **pending** · conditions: **pending**

Do not mark these items completed or award their remaining progress points until
the actual participant feedback and supervisor decision have been recorded.
