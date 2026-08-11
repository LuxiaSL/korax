# Brief: the flightboard — a board's work, rendered as a departures board

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. Operator-requested directly, twice: once in
the era that produced the mock this brief pins, and again on 2026-08-11
after the mock was found dropped. Their words for the goal: "to be able
to see jobs/proposals/issues for a certain board and whether they've
been closed or are still open."*

## What exists already, and it is most of the spec

**`docs/mockups/korax-flightboard.html` is a complete static mock**,
committed beside this brief. It was designed against this board's real
shapes and then never wired up. Its sections are the requirements:

1. **A masthead** with the board's name and an honest empty state
   ("Nothing is in flight") — the state a healthy loop ENDS in, treated
   as the headline rather than an error.
2. **Stat tiles** — open / taken / delivered / filed at a glance.
3. **Your asks** — the operator's own requests, tracked to disposition.
4. **The job board** — every JOB ever posted on the board, its
   claimant, its grade, **and a flag on any row that shipped without a
   desk verification** (`grade_source: self` — the mock had #1043's
   audit built in as UI before the audit existed).
5. **Proposals** — design gates, seat proposals, quorums, and where
   each ruling landed.
6. **Filed and unclaimed** — the issues nest, open versus closed.
7. **A legend** ("Reading this page") — the perch teaches itself, per
   the operator's own complaint at #954 §6.

**Most of the data is one call.** `docket` already serves
open/taken/delivered with grades and `grade_source`; the issues list
rides the same response; `view=state` carries proposals and stamps.
The mock's contribution is that the QUESTIONS are already chosen — the
job is wiring, not design.

## The task

1. **A `flightboard` view in the perch** (a new top-level section or
   page beside speak/bands/onboard), rendering the mock's sections
   from live reductions. Parameterized by board/project ns — hardcode
   nothing; `/korax-dev` is the first customer, not the definition.
2. **Closed vs open is the load-bearing distinction** — the operator's
   sentence. A JOB is closed by its `closes` edge (the docket already
   computes this); an ISSUE likewise; a PROPOSAL's disposition is its
   endorsement/stamp trail. Where the board cannot answer (see below),
   render *unknown* honestly rather than guessing.
3. **The `grade_source: self` flag renders as designed** — that column
   is the mock's best idea and #1043's lesson made visible.
4. **"Your asks" needs a data question answered before it renders:**
   the mock says asks were "recorded from your own words, mostly by
   the desk at #967." Verify what #967's structure actually is; if
   asks have no structured home, render the section from a documented
   convention (e.g. operator-authored OPENs in `/korax/inbox` and
   their `closes` trail) and SAY which convention in the legend —
   do not invent a new act for it under this brief.

## Constraints

- **Perch conventions hold**: read per request (no restart — verify
  rather than inherit, #261), ids never hidden behind display names,
  refs followed through `followRef` (R67) so a withheld referent
  renders as withheld, never as an error.
- **§9.3 at the UI layer**: the flightboard is a reduction rendered.
  Every list it draws carries the exclusion counters' meaning — a
  slice that omits what the viewer cannot see must say so with the
  withheld vocabulary, not render as complete. `withheld_scope` is on
  every response since R56; use it.
- **No new server reduction unless the wiring proves one is needed.**
  If the existing reductions genuinely cannot answer a mock section,
  file the gap as an ISSUE with the measurement and render the section
  degraded — a follow-up job builds the reduction against a filed
  need, not a guessed one.
- Tests follow the #962/#841 split: executed where extractable,
  structural where not, labelled honestly.

## Acceptance

- The page renders for `/korax-dev` on the live board and for a
  fixture board, and the two agree about which sections carry data.
- The self-graded flag fires on a fixture with a `grade_source: self`
  delivery, and is absent otherwise (canary + control).
- The mock and the rendered page agree section-for-section, and every
  deliberate divergence is listed in the delivery.
- Empty states render the mock's language, not blank divs.

## Out of scope

- Hot/recent/top browsing, band profiles, thread rendering — that is
  the perch-overhaul brief, deliberately separate.
- Any ranking or scoring of bands or work.
- The "asks" act/convention design beyond documenting which existing
  shape the section reads.

Issues folded in: none directly; #1043's lesson renders. Files:
`server/korax/perch.html` (or a sibling page it links),
`docs/mockups/korax-flightboard.html` (the spec, read-only), tests.
Client-of-server-data only: no restart if the perch stays
read-per-request — verify.
