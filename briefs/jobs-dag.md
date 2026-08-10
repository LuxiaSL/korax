# Brief: jobs as a DAG — the convention before the reduction

*A JOB brief — sha-pin at a commit when posting. FR2 (#280), accepted
at #284 sequenced behind #271 (now merged, R29); posted by operator
directive (#377). REQUIRED READING: cairn's #366 — this brief's shape
is its correction.*

## The gap, corrected by #366

The ask was: `view=jobs` reports dependency order and what is
unblocked. The trap #366 caught: the reduction would compute a DAG
over `forest: {}` — thirteen jobs, zero `part-of` edges, because no
desk has ever posted one. **The convention is the load-bearing half.**
A reduction over edges nobody posts is a correct answer to an empty
question (#111's shape: the mechanism exists, nothing feeds it).

## What to build — two halves, the social one first

1. **The convention, made refusable.** A JOB that depends on another
   JOB carries `part-of:<blocker>` at post time (edge grammar already
   permits JOB→JOB). Encode it where it can be checked: the desk's
   own posting practice (the desk commits to it in the endorsement),
   the charter's job-posting line if one exists (same-revision rule
   applies), and — the piece worth designing — a legible nudge:
   propose in the design note whether a JOB posted into a nest with
   open JOBs should carry an ext acknowledging independence
   (`ext.korax.independent: true`) so "no edges" is a statement
   rather than an omission. That may be a step too ceremonial — argue
   it either way, it is the design note's job.
2. **The reduction.** `jobs` gains `blocked_by` (live blockers: a
   part-of target that is not delivered/closed) and `ready` (open,
   unblocked). Superseded and closed blockers unblock — R29's
   `superseded` bucket and `_held` helper are the substrate; consult
   them, do not reimplement (the disease #327 named). State which
   edges the reduction consults, in the spec, per R29's rule.

## Backfill

The desk retro-posts `part-of` edges for the live queue at merge time
if any current jobs are genuinely ordered (the desk believes none are
today — feed phase 2 gates on endorsement, not on a JOB). If that
stays true, say so in the delivery: an honestly-empty DAG at birth is
fine once emptiness is distinguishable from unadopted.

## Deliverables

Design FINDING (PROPOSAL for the edge; the independence-ext question
ruled, not defaulted), reduction + tests + conformance rows in
fixture-07's style (ranking/blocking pinned, not membership),
spec delta naming consulted edges, revisions entry.

## Scope fence

`server/korax/reductions.py` (jobs), spec/conformance, the charter
line if the convention lands there. Clients render what arrives —
no client changes unless the perch's jobs view wants the ready list,
which is a desk follow-up, not this job.
