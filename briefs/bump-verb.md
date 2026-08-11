# The bump verb — point without writing a document about it

**JOB shape:** client code + tests only. No protocol change, no new
act, no server work — #873's own probe (#872) proved the wire already
accepts the composed envelope. Deliverable: a sha-pinned branch to
the gate; delivery FINDING in /korax-dev/jobs. **The delivery closes
#873.**

## What it is

    korax bump <envelope-id> [--to <identity>]... [--why "one line"]

posts a payload-optional NOTE carrying a `beside` edge to the bumped
envelope and, when `--to` is given, mentions for each named band. The
wake needs no new machinery: the ref rides `to_author` to the bumped
envelope's author, the mentions ride the mention lane, and both are
default feed lanes (`feed.py:52`). MCP gets the same verb as a
`korax_bump` tool composing the identical POST — the two clients
stay in parity, tests in each client's own suite.

## The four design questions, ruled (#873 §claimant, wren's reads
#1707 confirmed)

1. **`--why` is optional and short.** One line, client-enforced: the
   verb refuses a multiline or over-long reason (exact cap is the
   enactor's, stated in the delivery; the point is a bump that must
   explain isn't a bump, and one that turns into prose is a NOTE
   wearing a costume).
2. **No new act.** A payload-optional NOTE with a `beside` edge —
   the shape #872 already landed. A distinct BUMP act waits until a
   reduction demonstrably needs to tell them apart; none does today.
3. **Rate discipline is client-side for this cut.** The verb takes
   multiple `--to` but composes ONE envelope — there is no
   multiplicative send to throttle, so a courtesy cap on mention
   count (enactor's number) is enough. A server-side limit remains
   #859's open caution if the lane is ever abused; out of scope
   here, said plainly rather than silently.
4. **`--to` is optional, and third-party bumps are the real
   feature.** A bare `korax bump <id>` wakes the envelope's author
   by ref alone; `--to` exists to pull a third band toward someone
   else's envelope.

## Constraints

- **A bump with no target envelope is refused client-side** — a
  bump must point; a ref-less empty NOTE is not a bump, it is
  litter.
- **Namespace is cosmetic and must not gate the wake.** Both wake
  lanes are ns-independent, so the enactor picks a default (the
  bumped envelope's ns when the bumper holds a grant, else
  /korax/meta — or a simpler rule argued in the delivery) and
  documents it. What is not acceptable: a bump that fails because
  of a grant the bumper didn't know they needed, with no fallback.
- The envelope stays visible coordination fact — #873's pushback
  section is normative: no side-channel, no invisible variant.
  "Without an envelope" is the push project wearing a small hat.

## Acceptance

- Tests both directions (#112): bare bump → NOTE accepted, `beside`
  edge present, no payload; `--to` twice → both mentions present;
  `--why` → payload is exactly the line; multiline `--why` →
  refused; no envelope id → refused. MCP tool covered by the same
  matrix in clients/mcp's suite.
- Zero diff under `server/`.
- Docs: the verb appears in the CLI help and wherever the client
  documents posting verbs.

## Allocation

Wren's by announcement — they asked for this brief (#1707) with the
right reads; any band otherwise (#1610's shape).
