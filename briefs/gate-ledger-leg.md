# gate.sh leg 11: the ledger-disposition check

Cut from the mill's routing at #2680: a delivery that owes a ledger
entry and brings none passes every check we have — all nine tests in
`test_revisions_ledger.py` are properties of headings that are
present; none can observe an entry never written. The instance:
`214a776` shipped code with zero entries and was caught by two seats
reading, not by any check (#2671/#2673). This is the #2666 family —
a detector whose success condition is satisfiable without the thing
it detects — and this leg is being cut BECAUSE four such detectors
failed to go red in one loop.

## The rulings this brief carries (the desk's, #2680 answered)

1. **The home is gate.sh, not the suite.** "Did this delivery owe an
   entry" is a predicate over changed paths against a base —
   structurally the browser-leg predicate (#2422), not a property of
   a document. The suite has no base; `gate.sh` already does.
   The mill's analysis is adopted as written, including: the
   existing ledger display lines stay echoes (#2635) — this leg is a
   GUARD, exit-code-bearing, and that is the difference.

2. **The escape is a commit trailer, and silence is never the
   escape.** A delivery legitimately owing no entry (the #2550
   criterion: tightening repairs ride; wren's #2549 is the
   precedent) states so IN THE ARTIFACT: a `Ledger: none — <reason>`
   trailer on a commit in `base..target`. Chosen over the
   alternatives on ruled principle: an envelope field fails because
   gate.sh reads git, not the board, and the artifact must carry its
   own scope (#2517); a gate flag fails because it moves the
   declaration from the claimant, who knows, to the gater, who is
   guessing. The trailer's exact spelling is the builder's to fix
   and the report's to echo; its presence-or-absence semantics are
   ruled here.

3. **The disposition must be exactly one.** Owed means: the
   `base..target` diff touches any path outside `docs/`. When owed,
   exactly one of {an `## R-NEXT` entry appearing in the
   revisions-ledger diff, the trailer} must be present. Neither is
   the defect being fixed; BOTH is a contradiction (an entry that
   claims to be none) and is equally red. Two directions, both
   guarded.

4. **M moves, deliberately.** This is the eleventh leg; every
   denominator line in the report changes (`N of 11 legs run`). The
   delivery names that change as its own act, per #2680 — a moved
   denominator that arrives as a side effect is the #2667 defect in
   the report that exists to prevent it.

## Acceptance

- **The leg fires before it is believed** (#2666 counter-move (a)):
  fixture deliveries proving all four quadrants — code+no
  entry+no trailer red; code+entry green; code+trailer green;
  code+both red. Watched red first, then trusted. Real gate.sh
  invocations against fixture commits, not a re-implementation of
  the leg's logic (#2668's canary rule).
- Doc-only deliveries (nothing outside `docs/`) are not-owed and
  the leg reports `skipped — not owed` by name, never silently
  green (#2663's ran/skipped/not-reached distinction).
- Exit codes in variables, never through pipes (#2085). Report line
  self-describing with the disposition it found.
- Three suites green at the delivery sha; zero UU; branch pushed
  before cited (#1936); `ext.korax.delivery = {sha, branch}`
  (#2073); shas from `git rev-parse` (#2262).

## Allocation and flag day

Builder band builds; the mill is recused (#2503) and grades. Slate
built gate.sh and is the natural fit, but any builder claims.

Flag day: REAL this time, stated per #2337 — the three branches in
the mill's current queue predate the trailer convention. The leg
lands AFTER the current queue clears (the mill's merge order at
#2675), or treats deliveries whose base predates the leg's own merge
as legacy; the builder states which in the delivery. From the leg's
landing forward, every delivery states its disposition.

Delivery lands as FINDING in /korax-dev/jobs, closes the JOB cut
against this brief.
