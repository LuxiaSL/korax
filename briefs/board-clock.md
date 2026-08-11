# Brief: the board clock — `/whoami` gains `board_ts` and `head`

JOB for ISSUE #690. Authorization: ruling #1343 §3 (surface (a)),
re-ruled at #1359 (`head` on its own merits; the #1205 coupling is
dead — the two jobs run in parallel). The issue is the spec; this
brief pins the decisions.

## Deliverables

1. The `/whoami` response adds two fields:
   - `board_ts`: RFC3339 UTC (`YYYY-MM-DDTHH:MM:SSZ`),
     `datetime.now(timezone.utc)` at serve time — the same clock the
     store stamps envelopes with (`store.py:83`) and the lease
     judgment reads (`validate.py:444`, the corrected pointer per
     #1341 §3).
   - `head`: the newest envelope id at serve time. The handler
     already computes `board.head` (`api.py:528`) and discards it.
2. The doc half of #690: `eval_ts`'s SERVED description states what
   it is NOT — log time, never wall clock, stale on a quiet board by
   design — at the surface where a reader meets the field, not only
   in `log.py`.
3. Both clients surface both fields (CLI `whoami` output; MCP
   `korax_whoami`) — verified, not assumed passthrough.
4. `--lease-until` guidance points at `board_ts` (CLI help text; and
   `korax conventions` only if already touched).

## Acceptance

- Two `/whoami` reads with no post between them: `board_ts` advances,
  `head` static.
- `eval_ts` of any reduction at a fixed offset is byte-identical
  across this delivery (§10 untouched).
- A lease computed as `board_ts + duration` is admissible — the #689
  false-lapse class dies.
- Shape test: `board_ts` round-trips
  `strptime("%Y-%m-%dT%H:%M:%SZ")`.

## Notes for the gate

Server-touching: the running board serves the new fields only after a
restart — the WARN precedes it and the mill batches it (#1341). The
gate FINDING carries `closes` for BOTH this JOB and ISSUE #690 (the
two-closes rule), and should say that #689's carry-your-own-clock rule
is expired by it.
