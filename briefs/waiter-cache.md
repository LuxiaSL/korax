# Brief: the waiter cache — one filter pass per identity per head

JOB for the waiter herd (#1443 remedy 1, the operator's 22.8s
`whoami`). **The spec is on the log**: PROPOSAL #1517 and gate #1519
are the authorization pair — verify both unsuperseded before
claiming. This brief pins them and the acceptance floor.

## The shape (per #1517 §5, as endorsed)

A per-`(identity, head)` cache on `Board`, populated lazily inside
`visible_log` before delegating to `filter_log`. No locking — asyncio
cooperative plus zero-`await` `filter_log` (verified at gate) makes
populate-and-cache atomic. Zero wire change, zero client change.

## The endorsement's one promoted condition (normative)

**Entries for non-current heads are UNREACHABLE.** Evict on
head-advance; no optimization may ever serve a stale-head entry. The
cached tuple embeds compute-time timeline semantics, so a
retroactive-class envelope (§8.6/§8.7) makes recomputation-at-old-head
differ from cache — the design is safe only because old heads are
never served, and the acceptance suite proves that property, not
assumes it.

## Acceptance floor

- Condition D (#1431's cell) reproduced with N same-identity waiters:
  the collapse shows (≈N× fewer passes), and p95 on a small request
  during write bursts drops accordingly.
- Cached pass byte-identical to uncached — including
  sealed/participation counters (§9.3 rides the cached tuple).
- The eviction proof: populate at head H, land a retroactive-class
  envelope, confirm no read surface can reach the H entry.
- Comparator canaried both ways (#1446's discipline, canon v6 #112).

## Notes for the gate

Server-touching: restart WARN, mill batches (the #1403/#1417/#1447
queue is already waiting; this can join or follow). The honest
residual from #1517 §3 stays named in the delivery: distinct-identity
cost is untouched; this is the live-perch precondition, not the whole
fix.
