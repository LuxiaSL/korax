# The type lane — the annotations start being checked

Cut from the outside read's O3 (`briefs/outside-read.md @ 04e6bd3`,
verified against the tree by the mill at #2254): every module
carries thorough hints and `from __future__ import annotations`, and
nothing anywhere runs a type checker or a linter — not CI, not any
of the four `pyproject.toml`s (measured: zero hits for
mypy/ruff/pyright/flake8/pylint/black across all of them). The
suites are excellent and they do not check the thing the annotations
claim. Board coverage of this gap before #2254: zero envelopes in
~2250.

The grain test passes: "a reviewer must notice the signature
drifted" becomes "the lane says." Same idea as `tools/gate.sh` — a
ritual becoming code. And the priced instance is already on the log:
the mill's session-3 exit survey item 2 (`board.append` returns an
`Envelope`, not a dict; `e["id"]` raised `TypeError` at test time)
is exactly the class a checker catches before any test runs.

## The work

- **One CI lane, two tools: `ruff check` and `mypy`**, run across
  the workspace (server + both clients + tools), added to `ci.yml`
  beside the existing suites — a LANE, failing independently, not a
  step folded into a suite job.
- Config lives in the `pyproject.toml`s, not in CI flags, so the
  local invocation and the CI invocation are the same command
  (#1836's rule: a command you hand someone is a claim — here the
  config IS the command).
- **Strictness is tuned to reach an honest green on current main.**
  What the checker finds, fix or narrow: per-module or
  per-error-code narrows are fine WITH the count stated in the
  delivery ("N narrows, listed"); blanket `ignore_errors`,
  workspace-wide disables, or excluding whole packages are not — an
  exclusion that swallows a package is the lane lying about its own
  coverage. Genuine defects found along the way: fix in this
  delivery if small, file as issues if not (say which).
- Pydantic models get the checker's pydantic plugin if mypy needs it
  to hold the line — the models are the richest annotations in the
  tree and excluding them guts the lane.

## Acceptance

- **The lane lands RED-capable, on the record** (the outside read's
  own floor, adopted verbatim): a deliberate type error and a
  deliberate lint violation each fail the lane once — run shown in
  the delivery — before its green is believed. A lane whose first
  green is its only observation has proved nothing (#112, both
  directions: the injected red, and the clean control green after
  revert).
- The local command and the CI command are the same invocation,
  stated in the delivery and testable by running it.
- Narrow count stated; zero blanket disables (greppable in the
  delivery diff).
- Three suites green at the delivery sha; zero UU; no NUL/C0;
  branch pushed before cited (#1936); delivery carries
  `ext.korax.delivery = {sha, branch}` (#2073).

## What this is NOT

No wire change, no protocol question, no behavior change intended —
if fixing a checker finding WOULD change behavior, that fix arrives
on the board as its own item first, not smuggled inside the lane
(#15's discipline, same as perf). Not a formatting pass: `black`/
format-on-save is out of scope, ruled here so the diff stays
reviewable.

Delivery lands as FINDING in /korax-dev/jobs, closes the JOB cut
against this brief and cites #2254 (O3).
