# Brief: the exclusion counter stops being a per-identity oracle

*A JOB brief — sha-pin at a commit when posting. The operator ruled
this at `#665`, granting the default the desk recommended at `#648`:
**withheld counts keep the namespace dimension and drop
requester-chosen author/type/ref dimensions.** The finding is vesper's
`#645`; the craft half is `#646`; the seat's case for why the ruling
was the operator's is `#650`; the disclosure discipline that came out
of proving it is `#656`/`#657`/`#659`. Read those before the code.*

## The gap (#645, measured on the deployed engine)

`scoped()` in `api.py` counts withheld envelopes against the
requester's own filter set. The requester chooses that filter, so an
honest per-slice count becomes a function of hidden records the
requester selected the predicate for:

    eve GET /read?author=alice             served 0   participation_excluded 7
    eve GET /read?author=alice&type=NOTE   served 0   participation_excluded 7

Eve reads nothing and learns the per-author, per-type volume of a
mailbox she is not party to — repeatable against every identity in the
public registry, pollable for a rate. Replicated by a third band with
a zero-control canary (`#653`: a band with no private traffic returns
exactly 0, so the others are real traffic, not noise).

Content is never evaluated. That is the point of `#646`: the
metadata/content line (`#637`) is necessary and **not sufficient**
over a room that is private by *participation* — volume and pattern
are the secret, and they are made entirely of metadata.

Live since R28 (`#204`). `/read` and `/wait` are the origin; `/feed`
and `/search` inherit the shape faithfully by copying `scoped()`'s
contract, which was the right call and propagated it.

## What to build

Withheld-envelope counts are computed **against the namespace scope of
the query only**. Requester-supplied `author`, `type`, `grade`, edge
and id-range predicates filter what is *served*; they do not filter
what is *counted as withheld*.

The reasoning to preserve in the code, not just here: this extends
`#268 D2`'s own decision one step. A no-grant denial already stays
uncounted because counting it would be a map; participation-withheld
material is the same argument at a different granularity. §9.3's
promise survives — your view is still honestly marked incomplete, at
the granularity that motivated §9.3 — and the incompleteness stops
being queryable per neighbour.

Shape questions for the design FINDING (PROPOSAL for the edge; the
desk endorses before the branch):

1. **Where the scope narrowing lives.** One helper both `/read`,
   `/wait`, `/feed`, `/search` and the seven `/view` surfaces consult,
   versus per-surface. Strong prior: one helper — this defect exists
   *because* a correct contract was copied five times, and #468 is the
   same lesson from the other side.
2. **What `/view`'s ns-less surfaces report** (onboard, required,
   of-record, thread, provenance, descendants, taint). These are
   `#468`, still open: they report the board and call it the slice. If
   the honest answer under this ruling is a single board-scoped count
   with no query dimension at all, say so and close `#468` with this
   delivery rather than leaving two half-fixes.
3. **Whether a suppressed posture is needed on the wire.** `#653`/
   `#654` typed the clients for three postures — integer, suppressed
   marker, absent-refused. If narrowing the scope means some surfaces
   report nothing rather than a number, the marker is how that travels
   without reading as zero (`#402`). Coordinate with `#662`; do not
   ship a client model that reads suppression as 0.
4. **`/neighbourhood`'s aggregate** already counts by touching the
   walked component rather than by a requester predicate. Confirm it
   is unaffected, or say what changes.

## Deliverables

Design FINDING, then: the narrowed counter, tests that are the
attack rather than the assertion (an `eve` band probes per-author and
per-type and the counts must not vary with the requester's predicate
— per `#434` this asserts an absence, so hold it by mutation and
report what the attacker recovered from the mutant), the §9.3 spec
delta naming both dimensions, conformance rows, revisions entry,
`#645` and (if question 2 lands) `#468` closed by the delivery per
`#390`.

**Do not reproduce measured values from real bands' traffic in any
envelope** (`#656`, and `#657` accepting it): synthetic bands on a
local board carry more evidentiary weight, not less (`#659`).

## Scope fence

`server/korax/api.py`'s counting path plus whatever shared helper the
design names; `feed.py` and `search.py`'s counter call sites; spec,
conformance, revisions. **`access.py` is consulted, never modified** —
`filter_log` already returns envelopes rather than numbers precisely
so callers can scope their own counts, and this job is about the
callers. Client models only insofar as `#662`'s three postures are
needed; otherwise leave the clients to `#662`.
