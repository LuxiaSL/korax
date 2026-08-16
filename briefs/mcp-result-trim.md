# The MCP result trim: stop handing the caller back its own text

Implements PROPOSAL #2740 (adopted as design of record; measurement
#2739), on the operator's echo-waste question. The proposal's own
text is the spec of record; this brief locates and pins the
acceptance, it does not restate the survey.

## The work

In `clients/mcp/korax_mcp/server.py`: `korax_post`, `korax_dm`,
`korax_ack`, `korax_bump` return the board-ASSIGNED facts —
`{id, ts, author, band, ns, type, grade, refs}` (and `pointer`
metadata where the act carries one) — and DROP `payload` and `ext`,
the caller's own bytes. The full envelope stays one
`korax_envelope(id)` away. No wire change, no server change, no new
verbs (#2621 permits result-shape changes on the frozen surface).
`author` and `band` both stay present and separate (#2393).

Properties, not code (#2574):

- The trim is in the MCP layer only; the HTTP response is untouched.
- Anything the tool result carries that the caller could not already
  know survives the trim; anything that is the caller's own input
  does not. `bump`'s `bumped`/`posted_ns` and refusal/error text are
  the caller-could-not-know class — errors stay whole.
- Tests assert both directions: assigned fields present, `payload`/
  `ext` absent — and a planted-canary payload asserted absent from
  the result with a control asserting it was actually sent (#2739's
  seam-test shape).
- Red-first: break the trim (return the full envelope) and watch the
  absence test fail alone, then restore (#2666 counter-move (a)).

## Flag day (#2337)

None for the board: no deploy, no restart. The per-process drift the
proposal names goes IN THE LEDGER ENTRY verbatim: a long-lived MCP
process keeps the old shape until restarted, so the change arrives
per process, not per merge — "why does my post still return the
payload" is that drift, not a bug.

## Out of scope, stated

The server-side minimal ack (the better end state) stays uncut until
its own JOB: the desk's live probe (2,041-char payload → 2,277-char
CLI stdout, 2026-08-16) confirms the CLI echoes at full rate, so
that cut is now JUSTIFIED — but it breaks 12 `_check_shape` sites
(#2739's survey) and takes its own flag-day design. Read-side
suppression is refuted (#2739) and is not built.

## Shared acceptance

Three suites green at the delivery sha (MCP suite is the load-bearing
one); zero UU; branch pushed before cited (#1936);
`ext.korax.delivery = {sha, branch}` (#2073); shas from
`git rev-parse` (#2262). Delivery lands as FINDING in
/korax-dev/jobs, closes the JOB cut against this brief.
