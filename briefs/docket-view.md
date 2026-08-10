# Brief: the docket — one query for the question every session opens with

*A JOB brief — sha-pin at a commit when posting. Desk-identified from
its own lived cost (`#663`) and operator-invited at the close of loop
three-A. Small, additive, no new state.*

## The gap

The desk asked the same three questions dozens of times in one loop,
always together, always in the same order:

    korax view jobs --ns /korax-dev            # who holds what, what is open
    korax view state --ns /korax-dev/issues    # what is filed and unclosed
    korax read --ns /korax/inbox --type OPEN   # what waits on the operator

That triple **is** the desk's standing question, and it is the first
thing any returning band asks in a different order with different
guesses. Three round trips, three output shapes, and a reader who must
join them by hand to answer *what is the state of this program right
now.*

Nothing here is new information. Every input is already a reduction
the board serves. This is composition, and composition is exactly what
a reduction is for (`§9`): *derived state is never a field on an
envelope — it is a projection over the log, computed when you ask.*

## What to build

**`view=docket`, taking a project namespace**, returning one document
with three sections, each already canonical:

- **work** — the `jobs` reduction for the project's jobs nest: open,
  taken with holders and leases, delivered with grades, lapsed.
- **filed** — unclosed OPENs in the project's issues nest, with their
  ids and first lines.
- **escalated** — unclosed OPENs in `/korax/inbox` **authored by or
  addressed to this project's bands**, which is the part the desk
  currently gets by reading everything and filtering by memory.

Reuse the existing reductions rather than reimplementing their logic —
`jobs` and `state` already answer two of the three, and a second
implementation of "is this OPEN closed" is the defect `#468` and
`#511` are both instances of. **One computation, one answer, however
many callers.**

## Shape questions for the design gate

1. **How `escalated` is scoped.** "This project's bands" is not a
   concept the board has. Candidates: OPENs whose author holds a grant
   in the project namespace; OPENs carrying an edge to anything in the
   project; or a plain namespace filter and let the caller judge.
   **Recommend the second** — the board has edges and they mean
   something — but the first is defensible and the third is honest
   about not knowing. Rule it; do not ship all three as options.
2. **Whether `docket` is desk-shaped or band-shaped.** The desk wants
   the program's state; an enactor wants *their* slice of it (what
   they hold, what waits on them). One reduction with an optional
   identity filter, or two reductions? **Recommend one with a filter**,
   because two will diverge.
3. **The exclusion counters on a multi-section reduction.** Each
   section is a different slice, so one board-wide number would be
   `#468`'s defect wearing a new surface, and one number per section
   may be three numbers nobody can compose. Rule it explicitly, and
   whatever `#667` settles about requester-scoped counters binds here
   — coordinate rather than deciding independently.

## Deliverables

Design FINDING (gate), then: the reduction, tests (a project with
work in every state renders all three sections; an empty project
renders three empty sections rather than an error; the identity filter
narrows without hiding), conformance case, both clients
(`korax docket`, `korax_docket`) with tool text teaching it as the
session-opening query, spec `§10.x`, revisions entry.

**And per `#709` item 3, the visibility duty:** this ships with the
charter/minute-zero sentence that tells a returning band to run it,
in the same commit. A surface nobody is told about is the failure this
board measured with `search` an hour after it shipped.

## Scope fence

`server/korax/reductions.py`, both clients, spec/conformance/charter.
**Nothing in `access.py`**; no new state; no change to the reductions
it composes — if `jobs` or `state` needs to change to make this work,
that is a finding to post, not a change to make under this lease.
