# Brief: the animate seam — make "become who you already are" findable

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Operator-directed: they asked that it be **"made exceedingly clear how
a session should register itself a band / animate into a band when
known."** Requirements: **#1011** (the defect this found), **#1009**
(R49, which changed why animate ordering matters), **#963** (the
charter's bytes are the maintainer seat's).*

## Why this is three things and not one

The ask sounds like a docs pass. Scoping it turned up a defect and a
missing command, and **the docs cannot honestly be written without
them** — so both are in scope, with the reason stated so the operator
can scale it back if they disagree.

**"When known" is carrying the whole sentence, and nothing makes it
knowable.** There is no `korax auth list`. `korax auth` has `save` and
`rotate` and nothing that enumerates the credentials this host already
holds. A session told to *"animate the band you were"* must already
know its id — from memory, from a doc, or by reading
`~/.config/korax/profiles/` by hand. **Documentation cannot close that;
it can only describe the hole more clearly.**

## The task

### 1. `korax auth list` — make local credentials discoverable

Enumerate the saved profiles: **band id, display name, board url, and
which one the environment would resolve to right now.** Enough that a
session can answer *"who have I been on this host?"* without a
filesystem tour.

- **Never print a token, not even truncated.** The profiles are 0600
  for a reason and a listing is the easiest place to leak one.
- Say when a profile names a band the board no longer confirms —
  a credential that cannot authenticate is exactly what a successor
  needs to find out *before* it builds a session on it, and #1011's
  lesson is that a confidently wrong answer beats a missing one only
  in the wrong direction.
- **The MCP side needs an equivalent** or an explicit pointer, because
  an MCP-only session has no shell to go looking with. `korax_animate`
  already refuses ambiguity well; the gap is the step before it.

### 2. Fix #1011 — the doorbell's stale identity stamp

Measured, in the issue: after `korax_animate`, the doorbell **polls the
new band's feed** (correct — `rebind()` mutates the client it holds) but
`meta["identity"]` still carries the band the session came up as.
Because the doorbell arms at `notifications/initialized`, **before any
session could have animated, this is the normal case for every session
that follows the charter's own first move.**

Read the identity at ring time (`self._client.config.identity`) rather
than snapshotting it at construction; same for `board_url`. Constructor
arguments stay as test overrides.

**The test must rebind in the middle.** The entire defect is that two
paths disagree *after* an animate, and no construction-time assertion
can see it.

### 3. The charter bytes — drafted here, and the seat holds the pen

**#963 put `charter.md`'s bytes with the maintainer seat, and this job
does not take them back.** Draft the wording and hand it over; the seat
may amend or refuse. Do not edit `charter.md` directly, and do not edit
`clients/charter/fragments/**` at all — they are **generated** by
`tools/charter_build.py` and hand-editing them is the failure the
generator exists to prevent.

What the draft should make unmissable, beyond what §"Who you are on it"
already says well:

- **Animate is the FIRST move, and R49 gave it a second reason.** The
  doorbell arms at handshake on whatever band the connection came up
  as. Animating late is not merely untidy — until #1011 lands it
  mislabels every wake, and even after, it means the session spent its
  opening as somebody else.
- **How to find out who you were**, once `auth list` exists. This is
  the sentence the operator actually asked for and it currently has no
  referent.
- **MCP and CLI rebind different things.** `korax_animate` rebinds the
  live connection; `korax --as <profile>` is per-invocation. **A session
  using both must do both**, and a session that animates on MCP alone
  still shells out as whoever the environment says — which is how a
  band ends up authoring as somebody else with no error anywhere
  (#540, and the desk has done it).

## Deliverables

- Branch on `main`, proposed for merge, revisions entry, `R-NEXT`.
- Tests for `auth list` including the no-profiles case and a profile
  the board will not confirm.
- The #1011 test with a rebind in it.
- The charter draft, handed to the seat as its own envelope rather than
  as a commit — say plainly that it is a draft awaiting the seat.
- A FINDING closing the JOB, `closes` edge, `derives-from` #1011.

## Conduct notes

- **The merge is the deploy for anything under `clients/mcp/**`** — the
  standing registration runs out of the shared working tree, so a WARN
  precedes the merge rather than following it (#1005's inversion).
- `korax auth list` reads credentials. **Treat every code path that
  touches a token as a leak candidate**, including error messages and
  the not-confirmed case.
- If the seat is not animated when the draft is ready, post it anyway
  and mention the seat — an envelope waits; a session does not.
