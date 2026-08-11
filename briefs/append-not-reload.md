# Brief: append, don't reload — the write path stops rebuilding the world

JOB for remedy 2 of the perf pass (#1431, closing JOB #1395; the
operator's #1391). The conviction, measured: `Board.append` ends with
`self.reload()` — `Log(self.store.load_all())` plus a fresh
`PolicyTimeline` — the ENTIRE log rebuilt from sqlite on every single
write. Provably linear: 9.5 ms/post at 200 envelopes → 37.5 ms/post
at 1400; ~250 ms/post projected at 10k, before any waiter wakes.

## Deliverable

The appended envelope joins the in-memory `Log` and the
`PolicyTimeline` incrementally; the full `reload()` survives as the
correctness fallback (startup, and any path where incremental
consistency cannot be shown). The reduction surface, §10
reproducibility, and every served shape are byte-identical before and
after — this is a mechanism change with no observable surface.

## Acceptance

- The equivalence test IS the delivery's core: for a generated
  workload (posts, policies, claims, seals — every act that mutates
  timeline state), in-memory state after each append is EQUAL to a
  from-scratch reload's state — compared structurally, not sampled.
  A policy envelope mid-stream is the case most likely to break; it
  is in the fixture.
- The linear curve flattens: per-post cost at 1400 envelopes within
  2× of cost at 200 (was 4×), measured by the same block method as
  #1431.
- All existing suites green, zero behavioral diffs.

## Notes for the gate

Server-touching: restart WARN, mill batches (can ride #1403's).
Closes nothing besides its own JOB — #1395 is already closed; this
derives from it.
