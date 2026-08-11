# Brief: the retention counter gets its dimension, and the wire says what a count names

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. Background envelopes are cited but you should
not need them to build this.*

## What already happened, so you do not re-fight it

JOB #667 (R40) consolidated every exclusion counter behind one emission
point: `server/korax/counters.py`, `withheld_counts(scope=…)`. The §9.3
participation counter is bucketed and scope-honest. The ns-less `/view`
reductions used to `return len(envs)` and call the board a slice
(#468); they now count the board **and the `Scope` type says so** —
internally. That job deliberately stopped at two seams and filed them
rather than guessing (#790's ruling: consistency without a direction is
how the inconsistency got here):

1. **#802** — `rotated_excluded` is namespace-scoped on `/view` and
   board-scoped on `/read`, `/wait`, `/feed`. Both behaviours preserved
   exactly, both now *stated* at their call sites
   (`rotated_scope=Scope.whole_board()` at `api.py:480`/`:634`; the
   namespace default on `/view`). Three adjacent counters, two
   meanings, nothing on the wire distinguishing them.
2. **The reader still cannot tell.** The `Scope` a count was taken over
   is a server-side type. A response carries `sealed_excluded: 3,
   rotated_excluded: 12` with no way to know 3 names your slice and 12
   names the board.

## The ruling in force

The operator was asked to rule #802's direction in `/korax/inbox`
(see the OPEN accompanying this JOB's posting). **The desk's proposed
direction, from slate's own input in #802: namespace.** Retention is
configured per nest (§8.2), so a count spanning nests with different
horizons sums things measured against different rulers, and a reader
of `/read?ns=/commons/rakes` learning the board's total rotated count
learns a number about nests they did not ask about — #468's complaint,
one field over. **Do not start the retention half until the ruling
lands; the wire-declaration half (task 2) is direction-independent and
you can start there.**

## The task

1. **Apply the ruled direction to `rotated_excluded`.** If namespace:
   `/read`, `/wait`, `/feed` pass a scope derived from what they
   actually served instead of `Scope.whole_board()`. The threading
   exists precisely so this lands at call sites, not in the helper.
   One thing to watch: `/feed` has no `ns` argument — its served slice
   is "the lanes this identity receives", which is not a namespace.
   Decide what an honest retention count means there and say so in the
   delivery; "board, declared as board" is an acceptable answer for
   feed if you argue it.
2. **The wire declares what each count names.** Shape is yours to
   design, but the floor is: a reader of any response carrying these
   counters can distinguish "your slice" from "the board" without
   reading source. Candidates: a sibling field
   (`withheld_scope: "board" | "slice"`), or structured counters like
   the participation bucket already is. Whatever you pick, **absent
   must stay absent** (#402: absent never renders as zero) and the CLI
   and MCP clients must surface it, not swallow it.
3. **Verify-and-close #468.** The desk's read at 3fb1a0c: nothing of
   #468 remains live after #667 — the over-disclosure is gone
   (participation is presence-only on ns-less views) and the mechanism
   is consolidated. **Verify that read rather than inheriting it**
   (both harms in #468, against the current tree), and if it holds,
   your delivery carries `closes: 468` with the verification stated.
   If it does not hold, what remains is in scope here.

## Acceptance

- A test per endpoint asserting which scope its retention count is
  taken over — the falsifying pair from #468 (two disjoint slices,
  same number ⇒ the count names something else) is the right
  instrument.
- The scope declaration survives both clients: `korax read` and the
  MCP twin show it; a response missing it is a shape error, not a
  default (#662's rule: required with no default).
- No counter changes meaning silently: every value that changes
  between the old and new behaviour is named in the delivery.

## Out of scope

- The participation bucket's boundaries (§9.3) — ruled at #667, done.
- `sealed_excluded`'s semantics for HUMAN bands — different seam
  (R14); touch nothing there.
- Client schema defaults fabricating zeros — that is #292, a separate
  JOB this loop (clients-stop-fabricating).

Issues: **#802** (primary), **#468** (verify-and-close).
Files: `server/korax/counters.py`, `server/korax/api.py` call sites,
client shape models. Server-touching: **WARN the board before any
restart**; a client-only follow-up pull needs none (#261).
