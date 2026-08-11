# Brief: the perch architecture question — a design JOB

JOB for the operator's #1342 §2. **The deliverable is a PROPOSAL on
the log** (the #1294/#1352 shape), gated by the gavel — not code. Any
build is jobbed separately after the gate.

## The question

Keep the single-file perch and solidify it, or split it into
independently-upgradeable pages. The operator's constraint (#1342):
the perch is their frequent, human-facing interface to an AI-managed
board, and it currently reads as a tossed-together MVP with few
per-tab affordances.

## Facts to design against (verify at claim time, not from this file)

- One self-contained ~1600-line file, `server/korax/perch.html`,
  served from disk PER REQUEST (`api.py:415`); no build step; for
  client-side changes the merge is the deploy.
- R74 shipped committed conflict markers in that file under 540 green
  tests; R75's guard (`node --check` over the whole script,
  `test_perch_script_parses.py`) is the only structural defense.
- Any split changes the mill's deploy leg. **The mill has offered
  (#1346 §3) to state the deploy shape of a proposed split BEFORE it
  is built — the proposal takes that offer and quotes the mill's
  statement as an input.**

## The proposal answers, at minimum

- Boundaries: per tab, or a shared shell with panels — and what
  stays shared (token handling, board client, styling tokens).
- Build step or none, weighing that a build step deletes the
  merge-is-the-deploy property the current file has.
- Migration: incremental (tab by tab) or rewrite, and what happens to
  the R75 parser guard under the chosen shape.
- How §3 (mobile) and §4 (style, `~/projects/aethera-server/`-
  inspired per the operator) land ON the chosen structure instead of
  fighting it.

## Sequencing (ruled)

Mobile (§3) is jobbed after the dev-loop JOB lands; the style pass
(§4) after this design is gated. Neither is open work yet.
