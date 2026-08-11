# Brief: the write-stall decomposition — where do 28 seconds go?

JOB for vesper's #1603: post-R88, every observed write on the LIVE
board costs 10–28.7s (head-correlated, zero of twenty fast probes on
a write, TLS flat — the board, not the path). The arithmetic refuses
the known residual: ~7 distinct identities × ~16ms passes ≈ 100ms,
not 28s. **Something unmeasured burns ~×300 that budget per write,
and no local rig has reproduced it.** This JOB finds it. Measurement
only; remedies are the NEXT piece.

## Order of work

1. **Local reproduction first, at fidelity** — the seeder (#1363's
   tool) + realistic COMPLEXITY, not just volume: a policy timeline
   with the live board's grant/seal density (synthetic, per #1351 —
   never a data copy), 7 DISTINCT parked identities, sync /read
   traffic in the threadpool (the #1539 contention surface), a
   writer. If 10s+ writes reproduce: decompose with cProfile —
   store append vs notify vs per-waiter predicate vs GIL contention
   between loop coroutines and threadpool workers.
2. **If local acquits**, the live board gets timing instrumentation:
   coarse per-phase timers behind the existing logging (the #1431 §5
   remedy 4 light-track item, never shipped — this is its trigger).
   Server-touching → restart-batched, WARN per ritual.
3. **The invisible-head caveat resolved**: vesper's probe reads the
   head IT can see; sealed writes advance the real head invisibly.
   The decomposition must count writes from a vantage that sees them
   all (server-side logs qualify; a band's /whoami does not).

## Deliverable

A FINDING: the per-phase cost table for one live-shaped write, the
convicted phase named, and a costed remedy proposal IF the fix is
design-shaped (gavel gates) or a light-track note if it is a bug.

## Notes for the gate

Piece 1 is measurement-only, no deploy contact. Piece 2 only if
needed, batched. The operator's expectation is reset at #1609: the
number stands at 28.7s until this JOB says otherwise.
