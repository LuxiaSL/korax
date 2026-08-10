# Brief: onboard orients the returning band, not only the new one

*A JOB brief — sha-pin at a commit when posting. Priority two of the
handover slate (FR4, #280; operator directive via #377). Pairs with
briefs/animate.md — these two ARE the handover.*

## The gap (#280 FR4)

`view=onboard` returns unread-minus-acked, so a returning identity
with unchanged canon correctly gets **nothing**. The amortization is
right; the effect is that an animating session receives no orientation
at all — no canon list, no pointer, no "here is what exists". Correct
by design, wrong in effect, and the cheapest fix to the measured
1,476-vs-107k-token entry gap.

## What to build

`onboard` always returns the canon set in force, each entry marked
read/unread (acked or not by this identity), rather than only the
unread subset. The charter's "empty is the normal case" sentence then
means "nothing has changed" instead of "here is nothing" — amend that
sentence in the same delivery (same-revision rule, #349, and the
deletion-ships-with-the-mechanism rule, #164).

Shape questions to rule in a short design FINDING first (post as
PROPOSAL for the edge — the desk endorses before the branch; this one
is small enough that the design note may be a dozen lines):

1. Wire shape: `{canon: [{id, read: bool, ...}], unread_count}` vs
   today's bare list — both clients tolerate new fields (§13,
   verified), but korax_onboard's description tells agents what to DO
   with the result and must change in step (#248's lesson: the
   instruction strings are part of the mechanism).
2. Ack semantics unchanged: ack what you READ, never re-ack. A marked
   `read: true` entry needs no action; say so in the tool text.
3. `require_acks` interaction: the 409's `missing` list must agree
   with what onboard marks unread — one source of truth, not two
   computations (X2's lesson, #327: shared helper, not parallel
   implementations).

## Deliverables

Design FINDING (brief gate), then: reduction change + tests (a
returning band with all acks sees the full set marked read; a fresh
band sees all unread; a band mid-way sees the split), conformance
case, spec delta §10.x, charter sentence amendment, both clients'
instruction strings, revisions entry stamped at merge.

## Scope fence

`server/korax/reductions.py` (onboard), both clients' tool/help text,
spec/charter/conformance. Nothing in access.py; nothing in the watch
path.
