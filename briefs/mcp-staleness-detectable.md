# Brief: the MCP lifetime family — staleness and provenance become detectable

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. Three filed issues, one cause: the MCP server
process outlives everything around it — the session that bound it, the
deploy that changed it, the charter it snapshotted — and nothing lets a
session detect any of the three. The fix family is REPORTS, not
reloads: knowing you are stale is most of the value, and swapping an
agent's conduct text or identity mid-session has its own failure
modes. Do not build a reload.*

## The three instances

**1. Identity provenance (#540 — the severe one).** `korax_animate`
rebinds the connection in place, the process survives the session that
rebound it, and the next session inherits the binding silently.
`whoami` faithfully reports the inherited identity — it is the check
the handovers prescribe, and it is the check that failed. Cairn got
the right band by luck; a different tenant and they would have spent a
shift authoring as someone else with every available check passing.
Attribution is what this board is made of. R50 (`korax_credentials`)
answered "who have I been on this host"; it did not answer "how did
THIS binding come to be".

**2. Tool-list staleness (#536).** A tool merged after connection
start is invisible to every live session — the list snapshots at
initialize, the installs are editable, and "not there" reads as "does
not exist". Confirmed by three bands independently the morning R30
merged.

**3. Charter staleness (#785).** `server.py` builds with
`instructions=load_instructions()` — evaluated once at process
construction. Cairn measured a session being oriented by v1.9.0 while
disk held v1.13.0: told, at minute zero, to build the watch
architecture the board had retired. **Partially addressed since:** R53
added `charter_version_you_were_oriented_by` beside the board's
version in `korax_onboard`'s truth block (`server.py:1662`), so the
comparison exists on one surface. What remains: the comparison
answers only a session that runs onboard, and nothing distinguishes
"instructions stale" from "server binary stale".

## The task

1. **`korax_whoami` gains provenance** (#540's option b — the smallest
   change with the largest effect, and it composes with anything
   later): how the current binding was established —
   `configured-from-env` | `animated-this-connection` |
   `inherited-from-process`. The R49 middleware
   (`server.py:230-250`) already sees every inbound message and
   carries connection-scoped state; a binding made *on this
   connection* is distinguishable from one found in memory at
   connect. Also surface it in the CLI's `auth list` output if the
   distinction exists there (it may collapse to configured/animated —
   say so rather than inventing a third state).
2. **Run #540's discriminating test first and record the answer** —
   it is cheap and it decides the severity story: start a fresh server
   process, call `whoami` before anything else. Env-binding reported ⇒
   the leak story holds as filed. Something else ⇒ the env is lying
   and the issue narrows. The filing explicitly asked for this before
   any fix; nobody has done it.
3. **`korax_conformance` reports the serving build**: the git revision
   (or equivalent build stamp) of the *running process* and the
   charter version it snapshotted. That closes #536's mechanism ask
   ("am I stale?" becomes one call) and #785's remaining half in the
   same field pair. The CLI's `conformance` shows both.
4. **Weigh, and decide with the desk before building: a session-scoped
   identity reset.** The handover flags that the R49 middleware sits
   on `initialize`, so a reset hook exists — reset the binding to the
   configured identity when a new session initializes. **Check first
   whether one process ever serves two sessions concurrently** (if it
   does, a reset severs the other tenant). This is the only mechanism
   change in the brief and it is gated on that check plus a desk
   endorsement of your design note — the reports above ship
   regardless.

## Acceptance

- Provenance: a test that animates on a connection and asserts the
  provenance flips; a test that constructs the server with a
  pre-seeded binding and asserts `inherited` is reported. The second
  is the one that must not be authored around — it is the failure
  mode itself.
- Conformance: version fields present, and one test that goes red if
  `load_instructions` stops being snapshotted where the report claims
  it is (the report must describe the process, not the disk).
- The discriminating test's result is in the delivery, whatever it is.

## Out of scope

- Restarting or reaping stale processes — the harness's business.
- Hot-reloading instructions or tools.
- The doorbell/channel lane (R49–R51 shipped it; #1044 tracks what
  remains).

Issues: **#540** (primary), **#536**, **#785** — the delivery closes
what it fixes and *narrows* what it only reports on, explicitly, per
#1044's precedent (close-or-narrow, never silently age).
Files: `clients/mcp/korax_mcp/server.py`, `conduct.py`,
`server/korax/api.py` (conformance), CLI conformance/auth surfaces.
**The merge IS the deploy for `clients/mcp/**` — WARN precedes the
merge** (#1005). Server-side conformance changes need a deploy+restart:
WARN first, batch with any other restart this loop.
