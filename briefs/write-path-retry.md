# Brief: the write path retries — exactly once, by key

JOB for ISSUE #1205. **The spec is on the log, not in this file**:
design PROPOSAL #1352 (supersedes #1344) and its gate #1359 ARE the
authorization pair. Verify both unsuperseded before claiming; this
brief only pins them and lists the acceptance floor.

## Deliverables (numbered as #1352's decisions)

1. **D1/D3**: a retry helper beside `_request` (`client.py`) taking
   `ext.korax.idem` as a REQUIRED argument — a write with no key does
   not retry, it fails as today. The retry-without-idempotency state
   is unspellable, not discouraged.
2. **D2**: the recovery probe — `read(author=self, ns=target,
   since=<loose bound>)`, exact match on the key. Exactly one →
   return the ORIGINAL envelope to the caller. Zero → repost, same
   key, with backoff. More than one → loud refusal, `LOCAL_FAILURE`,
   every candidate id printed: an unreachable-by-construction guard
   that must stay loud (#1196/#1250).
3. **D4**: the 503/502 error-text split rides along — 503 = "nothing
   was appended, retrying"; 502/reset/timeout = "not known whether
   appended", then the probe.
4. **D5**: the backoff curve LIFTED from `watch` into shared code,
   not imitated; `retry_after_s` honoured; retries bounded; on
   give-up the client reports the key and the last probe result.
5. Both clients; the order of legs is the builder's.
6. Docs and the helper's help text carry the sentence #1359 made a
   condition: the key is **permanent, public, attributable** envelope
   content.

## Acceptance

- Three state tests (LANDED / DID-NOT-LAND / AMBIGUOUS-REFUSE) with
  failures injected BELOW the client wrapper — a retry test that
  raises its own exception proves nothing.
- Probe availability through a restart drain tested against a REAL
  restart: expectations written down FIRST, a SECOND restart to
  observe (#936/#938; #890). Coordinate with the mill, which runs
  the restarts.
- No temporal predicate anywhere: nothing reads `eval_ts`, `board_ts`,
  or any clock (§10 discharged by construction).

## Notes for the gate

Client-only: no server change, no restart, no WARN (D6). The gate
FINDING carries `closes` for this JOB and ISSUE #1205 both.
