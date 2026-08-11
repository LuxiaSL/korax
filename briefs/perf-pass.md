# Brief: the perf pass — measure from the operator's lane in

JOB for the operator's #1391: loads are slow on average and sometimes
hang, from their browser inward. **This JOB measures; it does not
redesign.** The storage question the operator raises is real and is
explicitly NOT authorized here — this JOB gathers the evidence that
decision needs, and any db/storage change is its own PROPOSAL, gated,
with these numbers as its input.

## Scope: the whole path, outside in

1. **The operator's lane**: perch page load and per-tab fetch
   timings, measured in a real browser against the LIVE board
   (read-only) and against a seeded local board (the #1363 loop, if
   landed by then) — so board-size effects separate from code
   effects.
2. **The routes**: server-side timing per endpoint the perch and
   clients actually hit (`/read`, `/view/*` including `docket`,
   `browse`, `flight`, `/feed`, `/search`, `/whoami`). p50/p95 over
   repeated light probes, N small enough to be polite to a live
   board.
3. **The recorded suspects, confirmed or acquitted with numbers**:
   - the 865,589-byte default board read quill measured at #1357 —
     response SIZE as a latency cause from the operator's lane;
   - browse's per-requester scoring (#1308's named-not-solved risk);
   - `visible_log` / access-filter construction cost per request;
   - sqlite's single-writer lock under parked long-polls
     (`board.wait_for`'s one Condition) — contention between reads,
     writes, and waits;
   - **the hangs**: "sometimes never" is a different defect than
     "slow" — establish whether it is long-poll starvation, proxy
     timeout, lock convoy, or something else, with at least one
     reproduced-and-traced instance before naming a cause.
4. **What it costs to know**: if instrumentation must be added to
   measure honestly, it is timing-only, behind the existing logging,
   and flagged to the mill if server-touching.

## Deliverable

A FINDING on the log: numbers per surface, the bottleneck list RANKED
by operator-felt impact, and a costed shortlist of remedies — each
tagged as light-track, JOB-sized, or design-gate-required. If the
numbers indict storage, say so plainly and stop; the redesign
PROPOSAL is the next piece, not this one.

## Constraints

Read-only against the live board; no load tests that degrade it; no
fixes smuggled in (slate's #1355 refusal is the standard). Local
reproduction preferred for anything invasive.
