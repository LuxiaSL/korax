# The live-feed test asserts what #1639 bought: dwell, observed by an instrument that names itself

Cut on the operator's word (2026-08-16 ~11:00Z) from the #2897 thread:
the CI red at run 31940108170, quill's measurement campaign
(#2901→#2908→#2930→#2951), and the desk's rulings adopting each clause
as it was earned (#2910 §2, #2912, #2932 §2, #2936, #2940, #2947,
#2952). The measurement thread is the material of record; where quill's
final finding (pending at cut time) amends a cited figure, the log's
latest supersedes this brief's citation without a recut. One claimable
item (#2589). Properties, not code (#2574).

## What this changes, stated per #2337

This CHANGES WHAT THE TEST MEANS. The shipped
`test_the_feed_goes_live_and_survives_a_restart` samples
`dataset.state` at 300 ms and asserts presence of `restarting` — an
instrument measured blind to sub-interval states (miss rate tracks
`1 − dwell/300ms`; a displayed 60 ms state is missed 80% of the time,
#2908 §2), whose failure text asserts a cause it cannot reach. From
this delivery forward the test asserts DWELL. The interim
undecidable-red posture (#2911/#2912) retires when this lands.

## The properties

1. **Transitions are RECORDED (MutationObserver), so a red says which
   world happened** — sampler-blind overwrite, no-goodbye, or genuine
   race — instead of leaving the reader to guess. The rig control:
   MutationObserver caught a displayed state 15/15 in every dwell cell
   including 60 ms (#2908 §2).
2. **The assertion is on DWELL, not presence.** `restarting` must hold
   long enough for a human to read — that is the property #1639 §2
   actually bought. Threshold: builder picks inside the 1–10 s bracket
   with rationale; the measured distribution is bimodal (median 33.7 s
   or ~6 ms over 62 runs, nothing between, #2930 §5), anchored by the
   ~34 s noticeDelay.
3. **Record-then-assert-presence is REFUSED** — refused on argument at
   #2910 §2/#2912 §2 and on data at #2930 §5: it would have turned
   report-18 (a real 6 ms flash a user cannot read) GREEN. The brief's
   builder demonstrates this refusal in the fixture (see acceptance),
   not merely cites it.
4. **The instrument states its own parameters in its own output** —
   the principle, with five current instances (#2952): core count
   (nproc or equivalent, per run); the observation interval; a capture
   loop that exits by exhausting its cap SAYS SO in the failure message
   (patience-exhausted and stable-end-state are different facts,
   #2946 §4); per-test durations (`--durations=0` on the CI browser
   leg invocation, #2949 §5); collected test count — BOTH halves, per
   #2963: the expectation asserted per invocation (a guard that
   validates once does not protect a loop whose world can change under
   it — quill's own v2 guard failed exactly this way), and the
   actually-ran count parsed from the leg's own summary. Intent and
   fact; neither alone suffices (#2951 §3, #2963).
5. **The failure message states the observed world and never a cause
   the instrument cannot reach.** The shipped message ("the goodbye
   page lost its race with the dying socket") was false on both
   clauses in the one observed instance (#2930 §2).

## Scope

`server/tests/test_perch_live_feed_browser.py`, its driver JS, and the
CI browser-leg invocation in `.github/workflows/ci.yml` (durations
flag, environment print). NOT `tools/gate.sh` (briefs/gate-scope.md's)
and NOT `server/korax/perch/js/tabs/feed.js`
(briefs/perch-feed-poller-fix.md's).

## Acceptance

- **report-18's world is the adjudicating red-first fixture**,
  reconstructed under 2-CPU pinning (the defect fired 1/24 pinned and
  0/44 at 16 cores — prove the repair under scarcity or prove it where
  the defect does not live, #2932): the shipped design fails it with
  a false message; a record+presence variant passes it (shown, then
  deleted — the refusal made observable); the delivered design fails
  it with a correct message.
- Every parameter in property 4 evidenced in the delivery's own output
  quotes, not asserted in its prose (#2957 §1's standard).
- Three suites green at the delivery sha; zero UU; branch pushed
  before cited (#1936); `ext.korax.delivery = {sha, branch}` (#2073);
  shas from `git rev-parse` (#2262).
- Delivery lands as FINDING in /korax-dev/jobs, closes the JOB and
  carries `closes` on ISSUE #2897 — with attribution of run
  31940108170 recorded as permanently open per #2950, repaired but
  never attributed.

## Allocation

Any enactor claims; the mill gates (#2503). Quill holds the
measurement (#2901) and its final finding feeds the fixture; holding
the measurement does not reserve the build.
