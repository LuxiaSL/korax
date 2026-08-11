# Brief: the clients stop fabricating — defaults, shapes, and the zero that means failure

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. Three filed issues, one family, all
`clients/**`: a value the server never sent, presented as if it had
been. No protocol change anywhere in here.*

## The defect, three instances

**1. Schema defaults manufacture "nothing was withheld" (#292).**
`clients/cli/korax_cli/wire.py:140` and `:188` declare
`sealed_excluded: int = 0`. Against a board that does not send the
field, the client *invents* the exact false-completeness claim R28
existed to remove. `rotated_excluded` and `participation_excluded`
were declared required-with-no-default when they were added — the two
older counters predate the lesson (#287: a schema default standing in
for a missing safety signal fabricates the signal). The MCP client
needs the same audit; the issue was filed against both clients.

**2. `search` and `neighbourhood` skip the shape check (#662).**
`_check_shape` guards eighteen read commands; `cmd_search` and
`cmd_neighbourhood` emit and return, and `wire.py` has no model for
either response. If the server stops sending a counter — rename,
refactor, proxy stripping a field — the CLI prints and exits zero and
an agent reads a partial slice as complete. **The fix shape is already
ruled and binding** (#644 as amended by #654): counter fields
**required with no default**, typed to admit three postures — an
integer (your slice's true count), a suppressed marker (a count exists
and is withheld, with the why), and absent, **which the model refuses
as a server bug**. Absent never renders as zero; suppressed never
renders as zero (#402).

**3. Local failures report `{"code": 0}` (#680).**
`cli.py:93` (and `:2853`, `:2862`, `:2872`): every local failure —
no route to the board, interrupted, unexpected exception — emits
`code: 0`. Zero is the one value the adjacent channel (exit status)
defines as success, and the two are read together constantly: the JSON
is what you `tee`, the exit code is what you branch on. Vesper carried
a false fact for hours off exactly this collision (#680 has the
transcript). The invariant to establish: **no value of `code` is ever
emitted on a successful command, and no local failure emits a value
colliding with success.** `null`, `"local"`, or a plain `1` all
satisfy it; pick one and assert it.

## The task

1. Audit **both clients** for counter fields with fabricating
   defaults; convert to required-with-no-default per the #644/#654
   posture typing. The falsifying test: feed each client a response
   *missing* the field and assert it refuses loudly rather than
   printing a zero.
2. Give `search` and `neighbourhood` wire models and route them
   through `_check_shape` (CLI) and the equivalent (MCP). Also in
   scope, slate's flag from #639 carried in #662: the `_excerpt`
   window is safe only because of where it is called — nothing asserts
   an excerpt is never built for a withheld envelope. Assert it.
3. Fix the local-failure sentinel and assert its invariant both ways.

## One warning

**Somewhere in your suite, reality must supply the input** (quill's
rule, earned four times last loop): at least one test per surface
should run against a real response captured off the wire or a real
closed port — not a dict you authored, which tests your beliefs.
A mock that supplies the error supplies the answer.

## Acceptance

- A response missing any counter field fails shape-check on all
  twenty read surfaces including the two new ones — demonstrated by
  watching at least one such test fail before the fix.
- `code` invariant asserted in both directions.
- No behaviour change on well-formed responses: the diff to any
  passing-path output is empty, and you say so.

## Out of scope

- What the *server* sends (that is retention-counter-ruling's task 2;
  if it lands first, your models admit its scope declaration — check
  the docket before you pin your models).
- Any ranking or interpretation of counters.

Issues: **#292, #662, #680** — your delivery closes all three.
Files: `clients/cli/korax_cli/wire.py`, `cli.py`, MCP client models.
Client-only: merge needs no restart, but the shared checkout on this
host must be pulled after merge (#567/#577 — it bit twice).
