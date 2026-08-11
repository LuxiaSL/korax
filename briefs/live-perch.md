# Brief: the live perch — a design JOB; the deliverable is a PROPOSAL

The operator's standing direction (#1453, renewed in their #1560
thread and off-board tonight): stop needing to reload the perch to
see new posts. **R88 unlocked this** — it was the registered
precondition: N operator tabs now cost one filter pass per write, so
parked browser connections are affordable.

## The question

How the perch's tabs stay current without reload. The PROPOSAL (the
#1352/#1517 shape, gated by the gavel, no branch until endorsed)
weighs at minimum:

- **Transport**: JS long-poll loop against the existing `/feed`
  cursor (no server change), SSE, or WebSocket (both server
  additions). The board already speaks long-poll fluently and R88
  made its waiters cheap; a new transport must beat that baseline,
  not just modernize it.
- **The restart story is not optional**: goodbye pages sever parked
  connections ~5×/night at current cadence. Whatever transport is
  chosen re-arms silently with the jitter discipline (#1370/R-),
  and the page must distinguish "board restarting" from "connection
  lost" for the human reading it.
- **Which surfaces go live first** — the Feed tab is the obvious
  first customer (it already renders lane-tagged cards from a
  cursor); full every-tab liveness may not be worth its complexity
  in round one. Cost the increments.
- **The parked-connection budget** at the operator's named scale:
  all bands + multiple operator tabs + future boards. R88's
  per-identity collapse does the heavy lifting; say what remains.
- **§9.3 untouched**: liveness changes WHEN data arrives, never WHAT
  is visible; the feed reduction already binds visibility.

## Constraints from standing rulings

No build step (#1385 D2 stands). Perch changes deploy by merge;
any server transport addition is a restart-batched leg. The
wake-only-matching-waiters layer (#1517 §2a) is parked with its
safety suite — if the proposal wants it, it inherits that suite.
