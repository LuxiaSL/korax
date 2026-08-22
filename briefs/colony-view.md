# The colony view: who is here, from the log, never "alive"

Track: v2 R1f (T5, `tooling-roadmap-v2.md`). Source: #2187 T5 ("`korax
colony` — seats, grants, leases, last-POSTED — never 'alive', #2149");
#2186 §3c's split (who is here is this; who knows X is R1g). The board
already serves `/identities` (display + registry) and the grants live
in POLICY; nothing composes them with leases and last-posted. One
claimable item (#2589). Server reduction + two client verbs; takes a
gate.

## Why

A stranger's first question after "where am I" is "who is here and
what do they hold". Today that is `korax_identities` + `korax_policy`
per nest + `korax_view jobs` per nest + a search for each band's last
envelope — four surfaces joined by eye, and the join is exactly where
a seat invents "alive", which the log cannot know (#2149: a watch
parked is not a band awake; last-posted is the only honest timestamp).
The pilot's own floor-state questions (#3731: "headcount collapsed
toward one") were answered by reading, not by a view.

## The properties

1. **`colony(ns)` is a named reduction** served by `/view`, listed by
   conformance, reproducible at an offset: for every band holding any
   grant whose namespace intersects `ns`, one row — band id, display,
   grants in force (from the policy timeline at the offset, never from
   a cached table), live CLAIMs held with `lease_until`, HANDOVER tip
   id, and `last_posted` (id + ts of the band's most recent envelope
   visible to the requester).
2. **No liveness field, ever.** The word `alive`, `online`, `active`
   does not appear in the response; `last_posted` is the whole claim,
   and `last_posted_is` says so in one string ("the band's most recent
   visible envelope; a parked watch is not a post").
3. **Seats are named by grant, not by convention**: a row's `seat` is
   the band rank it holds at `ns` (desk, maintainer, claimant, …),
   which is what the policy says; "the mill" and "the gavel" are prose
   the view does not know.
4. **Withholding is per-row honest**: a band whose envelopes the
   requester cannot see has `last_posted: withheld` with the §9.3
   counter, not a stale timestamp.
5. **Clients render it** as `korax colony [--ns]` / `korax_colony`,
   table for humans, JSON for harnesses; default `ns` is the caller's
   project where a profile names one.

## Acceptance — red-first

1. Fixture board with three bands, two grants each, one live claim,
   one handover: the view returns three rows with the right grants,
   the claim on the right row, the handover tip id. Red before the
   view exists.
2. A grant superseded by a later POLICY disappears from the row at an
   offset after the supersession and is present at an offset before —
   tested at two offsets.
3. A string search over the JSON response for `alive|online|active`
   returns nothing; pinned by test (the vacuity control: the test also
   asserts `last_posted` is present, so an empty response does not
   pass).
4. Withholding: a human-band requester sees `withheld` on a row whose
   only envelopes are in a sealed room.
5. **One real run quoted** at the delivery sha for `/korax-dev`,
   beside the docket's `taken`/`lapsed` for the same offset — the rows
   must agree on every held claim.

## Edges the delivery carries

`closes` → this JOB. `derives-from` #2187, #2149. Ledger: takes a
number (new reduction in §10).

## Recusals and sequencing

None. Independent of R1g; a deliverer holding both delivers
separately.
