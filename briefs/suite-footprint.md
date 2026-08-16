# The suite footprint — measured, not felt

Cut from the mill's proposal (DM'd 2026-08-16, arithmetic restated
in the JOB), on the operator's #2248 steer: every band pays the
suite cost on every delivery, tonight's gate paid it three times,
and nobody has ever measured where it goes. ~1252 tests in ~103s at
the R125-R127 gate target is ~83 ms/test for a suite that is almost
entirely in-memory — high enough to want an explanation, cheap
enough to get one locally.

The hypothesis worth testing (the outside read's O2(a), scoped down
to what needs no production rig): if the test fixtures build boards
through `load_all()`/`filter_log` — the same whole-log
materialisation the outside read flags — then per-test cost is a
local, deterministic SYMPTOM of that shape. Confirming or refuting
that is the deliverable; fixing it is not.

**This is not O2(a).** The production read-tail measurement stays
declined behind its named precondition (parked-count via `ss` at
:7420 + endpoint-mix journal sample, #2262). This job touches no
production system and its result neither discharges nor weakens
that precondition.

## The work — MEASURE ONLY

- `pytest --durations` across all three suites at a stated sha, with
  the invocation quoted beside every number (#1221: a suite number
  describes a sha and an invocation, not a session).
- Fixture-level accounting: how many tests build a board, what each
  build costs, which fixtures are shared vs per-test.
- A count of tests whose path pays `load_all()` — measured (import
  hook, profiler, or instrumented build), not grepped-and-guessed.
- **The distribution, not just the total** — a long cheap tail plus
  one expensive shared fixture and a flat 80ms-everywhere suite are
  different diagnoses with different remedies, and the guess this
  replaces must not survive as a summary.
- The report states what it did NOT measure (CI runner variance, the
  mill's doubled-invocation ritual, production reads — all out).

## Constraints

- No optimisation, no behaviour change, no "harmless" fixture tweak
  riding along — §15's discipline: this document is the "before."
  Any fix that falls out arrives on the board as its own item.
- Coordinate with the gate: do not run a competing pytest on this
  host while the mill is measuring a delivery (the mill's own
  courtesy tonight, adopted as a rule of this job).

## Acceptance

- Every number reproducible from a stated command at a stated sha.
- Distribution + fixture accounting + `load_all()` count present.
- The not-measured list present.
- Delivery lands as FINDING in /korax-dev/jobs (evidence:
  repro-attached), closes the JOB. No suites need re-running for a
  measurement that changes no code — but the delivery names the sha
  it measured and confirms zero diff against it.
