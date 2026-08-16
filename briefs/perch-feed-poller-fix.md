# The duplicate live-feed poller: one loop survives a pause/resume, by construction

Cut on the operator's word (2026-08-16 ~11:00Z) against ISSUE #2909
(quill), reproduced independently by the mill at #2911 §1. One
claimable item (#2589). Properties, not code (#2574). The measurement
thread (#2908/#2930/#2955) is the material of record; the log's latest
supersedes any cited figure without a recut.

## The defect (all three facts verified twice, #2909 + #2911)

`server/korax/perch/js/tabs/feed.js`: `feedLiveStop` (:276) sets
`FEED_LIVE = false` and cannot cancel the in-flight `/feed` poll (no
`AbortController` anywhere under `perch/js/`, 17 files); `feedLiveLoop`
(:253) re-tests the flag only AFTER the up-to-50 s await returns;
`feedLiveStart` (:268) guards on the flag, which cannot see a loop
that is merely awaiting. So pause-then-resume inside a poll window
leaves the old loop alive forever beside the new one, and every cycle
can add another. Reachable by an operator with two clicks; 40/40
instrumented runs had two polls open at SIGTERM. Consequences beyond
tidiness: two writers on one status element; the shared
`FEED_FAILURES` counter (:186) lets one loop's success zero the
other's backoff (defeats #1370); each leaked poller doubles the
parked-poll load #1395 measured as the board's dominant cost.

## The properties

1. **After the fix, a pause/resume cycle inside a poll window leaves
   EXACTLY ONE live loop**, proven by a test that fails red on the
   unfixed code first (#2666 counter-move (a)).
2. **The mechanism is the builder's choice, posed not presupposed**
   (#2909's survey): a generation token (smaller — each loop captures
   a counter; both the `while` and the post-await check compare
   against current) or an `AbortController` per loop (cancels the
   socket immediately, but `poll()` in `plumbing.js` is shared and its
   own comment (:205) forbids fusing a deliberate abort with
   `offline` — the trap is named; do not step on it silently). The
   delivery states the choice and its reason.
3. **This delivery does NOT claim to fix the CI flake** (#2932 §1,
   ruled): in report-18 the zombie loop SUPPLIED the goodbye the tab
   displayed while the fix-kept loop's socket was severed (#2930 §3).
   The delivery carries `closes` on #2909 and MUST NOT carry `closes`
   on #2897. A fix that quietly converts sampler-blindness reds into
   no-goodbye reds has moved the defect, not fixed it.

## Acceptance (the #2955 three-clause form, verbatim of record)

Goodbye delivery re-measured **to a poll of the same age as the one
the fix keeps** (the fresh-loop construction — page reload, go live,
the shipped driver's 1200 ms wait — with the poll-age control shown:
measured age beside the ~1206 ms target), **under the scarcity where
the defect fires** (2-CPU pinning, applied not described), **with
`NO_GOODBYE_RECEIVED` counted explicitly** — the counter's value
including its zero quoted in the delivery. Per #2957 §1 the gate
requires these EVIDENCED in the delivery's own output, not asserted
in its prose; a "measured single-loop delivery, 24/24" sentence
without the poll-age control is indistinguishable from the arm #2955
discarded.

Plus the standing set: three suites green at the delivery sha; zero
UU; branch pushed before cited (#1936); `ext.korax.delivery = {sha,
branch}` (#2073); shas from `git rev-parse` (#2262).

## Flag day (#2337)

None for the board: perch JS is a client-side asset — the deploy's
client legs pull, no server restart (#261). Note in the ledger entry:
open tabs run the old JS until reloaded, so the fix arrives per
tab-reload, not per merge.

## Allocation

Any enactor claims; the mill gates (#2503). Delivery lands as FINDING
in /korax-dev/jobs, closes the JOB and ISSUE #2909.
