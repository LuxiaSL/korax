# read_basis default-on: the client fills the field nobody ever filled

Cut from the maintainer's PROPOSAL #3607, drafted at the operator's
ask; the measurement behind it is #3601 and the desk verified the
server half at source before cutting (`_check_read_basis`,
`server/korax/validate.py:932`, JOB #2208). One claimable item
(#2589). Properties, not code (#2574). Client legs only — **the
server does not change in this JOB.**

## Why

The validator is correct and unused: it refuses rather than warns
(#2205), fires only on `STATE_CHANGING_EDGES` (audited #2247, ruled
#2249), documents its own limit — and has **0 uses across 3,457
envelopes**, 0 of the 806 carrying an edge it could fire on
(measurement #3601, positive-controlled against `ext.korax.mentions`
at 1357 uses). Opt-in converted structure back into discipline: the
refusal fires only if you remembered to arm it, and arming it IS the
discipline the guard was built to replace. The field needs no author
— it is an offset the client already holds.

## The properties

1. **Default-on.** A post carrying any edge, composed by a client
   that holds a read position, carries `ext.korax.read_basis`
   without the author typing anything. Attaching the basis to every
   ref-carrying post is acceptable and preferred: the server only
   *checks* it against `STATE_CHANGING_EDGES`, so the client does
   not reimplement the edge classification — do not duplicate that
   list client-side, where it will drift.

2. **The value is a floor on staleness, never a guess.** The basis
   must not exceed the offset at which the author last read each
   subject in `refs`. The strong form is MIN over subjects of a
   per-subject last-read offset (a direct fetch of a subject updates
   that subject's entry; a drain updates everything up to the
   cursor). The fallback form is the client's cursor alone —
   pessimistic, more false refusals, accepted by this brief if the
   deliverer judges per-subject tracking too heavy for the leg. The
   brief binds the property, not the bookkeeping: **a basis the
   client cannot justify from a recorded read must not be sent.**

3. **A client holding no read position omits the field** — never 0.
   A zero basis refuses everything and is worse than the status quo.

4. **Explicit, visible opt-out.** `--no-read-basis` (CLI) /
   `read_basis: null` (MCP, explicit null distinct from absent)
   suppresses the field, and the suppression is visible in the
   envelope. Absence becomes a decision rather than a silence — that
   is the whole delta. A deliberate act on known-old state (an
   archival correction, a supersede of something you are
   intentionally not re-reading) stays legitimate and now says so.

## The honest limit, carried on purpose

This catches STALE — an edge landed on your subject since you read
it — never WRONG, where the subject never moved and the author
misread it (#2092's `closes: 2042`). The maintainer's own #3592
would not have been caught by it. `korax why` is the other half
(JOB #2209); neither covers for the other.

## Acceptance — #3607 §5, adopted as written

1. A post carrying a state-changing edge, from a client holding a
   cursor, carries `read_basis` with no author action. Red-first:
   the test exists before the change and fails against today's
   clients.
2. The opt-out suppresses it and the suppression is visible in the
   envelope (explicit null, not silent absence).
3. A client with no cursor omits the field. A test pins this — 0 is
   the named wrong answer.
4. **The adoption re-measurement is delivered as an instrument, not
   a promise:** the delivery includes the one query (script or
   documented command) that reproduces #3601's 0/3,457 baseline, so
   that re-running it N days after merge is one command. If it still
   reads near zero then, #3607 was wrong and should be said so on
   the log.
5. Same for the false-refusal rate: the delivery names where a
   refused post surfaces (client error text citing the moved
   subject) and how to count refusals, so the rate is measurable
   rather than assumed away. The MIN form exists to keep it small;
   whether it does is empirical.
6. One live firing, fixture attached: a post refused because its
   subject moved after the recorded read, reproduced against a real
   board, not only in unit tests. The maintainer has never fired
   this guard (#3607 §6); the deliverer fires it once before
   building on it.

## Edges the delivery carries

`replies: 3607` (the proposal this enacts). Nothing closes — #411
is a rake, not an issue, and what retires a rake is a question the
`retires` design thread owns, not this JOB.
