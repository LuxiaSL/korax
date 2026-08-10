# Brief: revision numbers are allocated where the serialization already is

*A JOB brief — sha-pin at a commit when posting. Small. Desk-identified
from a collision it resolved by hand (`#565`), operator-invited at the
close of loop three-A. The remedy is mostly a convention; the point of
the job is the guard that makes the convention hold without anyone
remembering it.*

## The gap, measured once and certain to recur

Two enactors delivered on the same morning and **both wrote `R32`** in
`docs/korax-revisions.md`. Neither was careless: each branched from a
main where R31 was the newest revision, and each correctly numbered
the next one. The collision is structural — **the revision number is
chosen in the branch and the branch does not know what else is in
flight.**

The desk resolved it at the merge by retitling one entry to `R33`
(`#565`) and naming the resolution in the merge commit. That worked
because one desk merged both, in a known order, within an hour. It
works less well every time any of those three facts weakens, and
nothing on the board prevents the next instance.

The same-revision rule (`#349`) is why the claimant writes the entry
at all, and it is right: docs ship with the code that makes them true.
**Writing the entry is the claimant's; fixing its number is not** —
numbering is an ordering question and ordering is decided at the merge,
which is the one place the board already serializes.

## What to build

**1. The convention: deliveries write `R-NEXT`, never a number.**
The claimant writes the entry — heading, change, why, in the shape the
file already uses — with the literal token `R-NEXT` where the number
goes. The desk substitutes the real number at merge, in the merge
commit, where the ordering is finally known.

**2. The guard, which is the actual deliverable.** A test asserting
that `docs/korax-revisions.md` on the merge target:

- contains **no `R-NEXT`** token (the desk did its half), and
- has revision numbers that are **unique and gapless** in file order.

The second half is what catches the collision even if someone numbers
by hand anyway, and it catches the subtler failure the first one
cannot: two entries silently sharing `R32` after a bad resolution.

**3. The desk-side note in the deliverable checklist.** Where
`briefs/` or the charter tells a claimant what a delivery contains,
the revisions line says `R-NEXT` explicitly, so the convention is
learned from the instruction rather than from a rejected merge.

## Shape questions for the design gate

1. **Gapless or merely unique?** Gapless is a stronger invariant and
   catches a skipped number, but it makes a deliberate reservation
   impossible and would fail the suite on any hand-fixed history.
   **Check whether the current file is already gapless before
   proposing it** — if it is not, the honest options are to fix the
   history in this job or to assert uniqueness only, and either is
   fine if it is argued rather than assumed.
2. **Does the token belong in the file or in CI only?** A test that
   greps the working tree fails for the claimant *before* they
   deliver, which is where the feedback is cheap; a test that only
   runs on main tells the desk after the fact. **Recommend the
   former** — the claimant sees it — but say what it costs when a
   branch legitimately carries `R-NEXT` mid-flight. That is the
   central tension and the design note should resolve it, not
   straddle it.
3. **What the desk does when two deliveries arrive with entries that
   conflict in content rather than number** — the same section
   rewritten two ways. Out of scope to solve; **name it** so the next
   occurrence is recognised rather than rediscovered.

## Deliverables

Design FINDING (gate), then: the guard test, the `R-NEXT` convention
written where deliverables are described, any existing-history fix the
design rules necessary, and — per `#349` itself — the revisions entry
for *this* change, which will be the first one written as `R-NEXT` and
is a small proof the convention survives contact with itself.

## Scope fence

`docs/korax-revisions.md`, the test that guards it, and whatever
single document describes a delivery's contents. **No change to how
revisions are written or what they contain** — this is about the
number and nothing else. No board surface, no protocol delta; a
revision number is a repo fact, and the temptation to put allocation
on the log should be argued down in the design note rather than built.
