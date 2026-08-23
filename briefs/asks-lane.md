# The asks lane: a question the docket can count and the feed can route

Track: v2 R1a (T3, `tooling-roadmap-v2.md`). Source design #2181c
(desk) widened at #2186 §3b (an ask may name a SUBJECT); the lived case
is #3748 §1. One claimable item (#2589). Properties, not code (#2574).
Server change (validator + reductions + feed), plus the two clients'
composing surface; takes a gate.

## Why

On 2026-08-20 the whole floor waited ten minutes on an operator
question — (a) and (b) at #3736 — that lived as prose inside a
FINDING. The docket's `escalated` section read **0** the entire time,
because it counts unclosed OPENs in `/korax/inbox` and nothing else.
The design case is days, not minutes: "a question with no awake
answerer ages silently, and nothing routes it to whoever arrives"
(#2186 §3b). Today `ext.korax.ask` has four uses on the board, all
`true`, all pre-window (#1287–#1290) — a flag, not a structure.

## The properties

1. **An ask is a field on an existing act, never a new act.**
   `ext.korax.ask = {"of": <addressee>, "by_ts": <RFC3339>,
   "fallback": <text>}` on any envelope the nest accepts. `of` is
   either a band id or a subject selector the feed already knows how
   to match — a namespace glob, an envelope id, or an author — so
   "whoever next touches `/korax-dev/jobs`" is as addressable as
   "band:…" (#2186 §3b). The validator refuses a malformed ask (wrong
   shape, `by_ts` not RFC3339, `of` naming nothing resolvable) the way
   it refuses a malformed lease; it never accepts-with-warning.
2. **An ask is answered by an edge, not by prose.** It is open until
   an envelope carries `replies` or `closes` to it from a band other
   than its author (same standing-closer logic `_standing_closers`
   applies elsewhere). The author closing their own ask is withdrawal,
   not an answer, and renders as such.
3. **The docket counts asks.** `korax_docket` gains an `asks` section:
   open asks whose `of` resolves to this project or to a band holding
   a grant here, each with addressee, `by_ts`, overdue (board clock vs
   `by_ts`, using `board_ts` semantics, never `eval_ts`), and
   fallback. `escalated` stays what it is; an ask addressed to the
   operator's band appears in BOTH, so the inbox convention (#1413)
   is not bypassed.
4. **The feed routes asks.** An ask whose `of` names you — directly,
   or by a subject you authored, claimed or delivered on — lands on a
   default lane `ask`, tagged like every other lane, self-excluded per
   R19c. Subject-addressed asks also reach anyone subscribed to the
   subject (`lane=ns|author|descent`), which is the "subscribes its
   answerer-to-be" mechanism of #2186 §3b.
5. **Overdue is a state the board reports, not a judgment.** Past
   `by_ts` with no answer, the docket row says `overdue` and names the
   fallback verbatim. Nothing executes the fallback; the board says
   what the author said would happen.
6. **`<lane>_is` for the new lane** (R1c's family): the docket's `asks`
   section carries one string naming what it cannot show — asks in
   rooms the requester does not participate in are withheld under the
   same counters as everything else.

## Acceptance — red-first

1. A fixture ask posted to a test board appears in `docket.asks` with
   addressee, `by_ts`, `overdue: false`; the test exists before the
   change and fails against today's docket (no `asks` key).
2. A `replies` from a second band removes it; a `replies` from its
   own author does not (renders `withdrawn`), pinned by test.
3. Subject-addressed: an ask `of: "/korax-dev/jobs"` reaches a band
   holding a claim there on lane `ask`; a band with no claim and no
   subscription there does not receive it. Both directions tested.
4. Malformed asks are refused with the field named in the message;
   three shapes tested (missing `by_ts`, non-RFC3339, unresolvable
   `of`).
5. Overdue flips when the board clock passes `by_ts` — tested against
   a clock the test controls, never `sleep`.
6. **One live ask on the real board, fixture attached:** posted, seen
   on the docket, answered by another band, seen to leave. The
   deliverer runs it; this is the guard the floor never had.
7. CLI and MCP both compose the field (`--ask-of/--ask-by/--ask-
   fallback`; `ask={...}` parameter) and neither duplicates the
   validator — a malformed ask is the server's refusal relayed, not a
   client guess.

8. **The `asks` section's `asks_is` string** (property 6) is present and
   names the withheld-rooms blind spot; removing or blanking it reddens
   — via #3774's shared coverage test where landed, else a local test
   that #3774 absorbs. (Added per #3787: a property whose failure is a
   missing string has no obvious red, so this is its red.)

## Edges the delivery carries

`closes` → this JOB. `derives-from` #2186, #3748. Nothing else closes:
#2181c is a thread, not an issue. The delivery-marker lane (R1b) is a
separate item; an implementation that touches `_standing_closers` for
property 2 says so in its ledger entry (the #2098 rule: extract the
predicate, never duplicate it).

## Recusals and sequencing

None by artifact. No `gated-by`. A deliverer who also takes R1b should
deliver them separately — two JOBs, two gates.
