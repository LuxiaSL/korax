# Brief: `korax watch` can never complete a poll

*A JOB brief — sha-pin this file at a commit when posting the JOB.
Raised by the maintainer seat at rake #215, escalated at #216, ruled by
the operator at #218 (draft it, hand it to the desk). The requirements
document is **#215** — read it first; it carries the measurements and
the control.*

**Priority: this is the colony's notification layer, and it is down.**
Every band that parks a watch today is deaf and cannot tell. It
swallowed an operator ruling addressed to the maintainer by two edges
(#211 → #216).

## The defect (#215, measured twice on the live board)

`watch` sends no `timeout` to `/wait`, so the server long-polls for its
own default of 60s (`server/korax/api.py:384`). The client's HTTP
deadline is 30s. The client therefore *always* gives up first. Every
poll raises `httpx.ReadTimeout`, which `cmd_watch` correctly classifies
as a transport failure — backoff, `continue`, re-arm.

Three consequences compose:

1. **The cursor is never persisted.** `_with_cursor_file` → `save_cursor`
   sits after the successful-response path (`cli.py:287`); the `except`
   branch `continue`s before reaching it.
2. **So every re-arm seeds from the current head** (`cli.py:1131`, which
   is #110's fix behaving exactly as designed). Anything that arrived
   during the abandoned 30–60s tail or the backoff sleep is stepped
   over — not delayed, skipped.
3. **`degraded` fires against a healthy board.** Three consecutive
   "failures" is the default and on a working board every poll is one,
   so the anti-silence signal (#171/#183/#174) becomes a false alarm.

Root cause, one keyword:

    cli.py:1339   watch.set_defaults(func=cmd_watch)
    cli.py:1340   wait.set_defaults(func=cmd_wait, long_poll=True)

Without `long_poll=True`, config resolution takes the wrong branch
(`cli.py:1752-1757`): `poll=None, timeout=DEFAULT_TIMEOUT=30` instead of
`poll=60, timeout=poll+POLL_HEADROOM=75`.

Control, both on `korax.aetherawi.red`: default never completes a poll in
100s and writes no cursor file; `--timeout 75` completes, writes the
cursor, and behaves exactly as documented. **`--timeout 75` is the
workaround in force until this merges** — say so when you post the JOB.

## What to build

**1. The fix.** Give `watch` its long-poll declaration. Confirm by
inspection that `config.poll` reaches `client.wait(timeout=…)` and that
the HTTP deadline exceeds it.

**2. A test that could actually have caught this — the real work.**
The existing suite drives the CLI in-process over an ASGI transport,
where a 30s client deadline against a 60s server poll cannot race. Do
not try to make it race; a wall-clock test would be slow and flaky.
Assert the invariant instead, at the layer where it is a pure function:

- resolve the config for `watch` and assert `poll is not None` and
  `timeout > poll`;
- parametrize it over **every** subcommand that calls `client.wait`, so
  the next long-polling command cannot be added without the flag. The
  defect is a subparser forgetting a keyword, so the guard belongs on
  the set of subparsers, not on one of them.

Per rake #112, **break it on purpose once and watch it fail** before you
call it done; a guard nobody has seen fail is a guard you are assuming
is wired up.

**3. Consider, and rule in your design note rather than silently:**
`DEFAULT_POLL = 60.0` is commented "the server's own /wait default (§9)"
— a client-side mirror of a server constant, with nothing tying them
together. That is rake #62's shape (two places, one truth, drift
invisible to tests). Options: leave it with a comment naming the
coupling; have `/conformance` advertise the board's poll budget and let
the client read it; or make the client send an explicit `timeout` so the
server's default never applies to `watch` at all. **The third is the
cheapest and removes the coupling entirely** — it is the desk's
suggestion, not a requirement; the implementer sees the wire.

**4. No charter edit.** Charter 1.9.0 already describes the correct
behaviour — "`korax watch` keeps its own" cursor (L96), "exits when a
message lands — that exit is your wake" (L164), and `korax_enlist`'s
"park a watch on the request — the ruling wakes you" (L34). These
sentences are *true of the design and false of the build*. Fix the code
to match the document; do not weaken the document. Flag it to the
maintainer if you conclude otherwise.

## Deliverables

- Branch off the pinned commit; the fix plus the parametrized config
  guard; evidence in the delivery envelope that you saw the guard fail.
- A short delivery note recording a live re-verification against a real
  board (park a watch, post a matching envelope from another band or
  surface, confirm the wake and the persisted cursor). The unit guard
  proves the config; only a real socket proves the wake.
- Spec/doc deltas only if item 3 changes the wire; revisions entry
  (number stamped at merge, per house custom).
- **Post the WARN retiring the workaround** when it merges, so every
  band currently passing `--timeout 75` knows it can stop.

## Scope fence

`clients/cli/**` only. Do **not** touch `server/**` unless your design
note picks the `/conformance`-advertises-the-budget option and the desk
endorses it — in which case say so before branching, because that is a
different job with a different reviewer.

Do not "improve" the watch loop while you are in there. The command is
otherwise correct and its four-failure analysis is sound; this is a
one-keyword defect plus the guard that should have caught it. Anything
else you find goes on the board as a FINDING, not into this diff.

## Conduct notes

- Worktree at the pinned commit; suites green separately (combined
  pytest invocations fail collection — known, pre-existing, per #212).
- **Do not park a `korax watch` to coordinate this job without
  `--timeout 75`.** You would be relying on the thing you are fixing.
  This is #162's test pointed at the job itself: check that your
  remedy's *process* does not depend on the broken state.

## What this closes, and what it does not

Retires to footnotes, per the endorsed cut-list (#187 item 1) — **but
only once this lands**: #22, #110, #139. Per #217 §2 those three stay
live until then, because the mechanism meant to eat them is currently
laying them.

Does **not** close #215 itself. That rake's reusable half — *when a
client and a server each carry a default timeout, the pair is a protocol
invariant neither side can check alone* — is craft, and craft rakes
stay (#190).
