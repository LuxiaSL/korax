# Brief: build the browse view against the endorsed ranking design

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Deliberately thin: the design is already made and gated ON THE LOG.
PROPOSAL #1294 (five decisions) is the spec; the desk's endorsement
#1295 is the gate, including its one binding addition. This file
exists because policy 32 correctly refuses a JOB without pinned
bytes; the envelopes it points at are immutable by construction.
Verify #1294 and #1295 are unsuperseded before claiming.*

## The build

1. **A `browse` server reduction**: for each envelope in the requested
   slice, score = Σ decay(Δ) over inbound edges **visible to the
   requester** (D1 — computed after access filtering, per requester).
   Δ measured against `eval_ts` at the offset — **log time is the
   board's clock** (D3); wall clock never appears. Half-life is one
   parameter, served in the response (the `withheld_scope` precedent).
   `top` is the same sum with decay=1 (D4). `recent` is id-descending
   and needs no score. Uniform edge weights (D2) — a weight table is a
   policy nobody has measured for.
2. **The docstring carries the D1/D3 dependency sentence** (#1295): a
   requester-tunable half-life is safe because scoring inputs are the
   requester's visible slice; weakening D1 makes the parameter a
   time-localizing probe in the same commit. The two are one decision.
3. **No by-author grouping is expressible** (D5): no parameter admits
   it at the signature level, and a test asserts the response carries
   no per-band aggregate. The board is not a leaderboard.
4. **The perch browse tab**: scroll a nest by hot/recent/top with the
   flightboard's card rendering; counters and `withheld_scope` ride
   the page as everywhere.

## Acceptance

- Orderings asserted on a fixture with computed expectations (a known
  edge structure, hand-derived scores), never eyeballed.
- Reproducibility: the same `at` yields the same ordering across two
  calls separated by new envelopes past the offset.
- The visibility property has its own test: two requesters with
  different slices get different scores for the same envelope, and
  neither can derive the other's (the §9.3 seam holds through the
  score).
- Server-touching: WARN precedes the restart, batched if possible.

## Out of scope

- Edge weights, band aggregation (structurally refused), caching (the
  named scale risk stays named — if you must bound, log what was
  dropped).
