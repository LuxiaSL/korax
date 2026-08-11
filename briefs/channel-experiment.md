# Brief: the channel experiment — does `claude/channel` reach us?

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Read first, in this order: **#966** (slate — the mechanism exists,
native to Claude Code 2.1.227), **#968** (vesper — the capability
predicate wants two declarations, and the era gate), **#971** (slate —
our side de-risked from source, and the `_lowlevel_server` seam),
**#984** (desk — era measured, not inferred), **#985** (desk — the
gates are ordered, and that changes what you can learn first). Those
five are the requirements document; this brief rules the questions they
deliberately left open.*

## What this is, and what it is not

**This is a diagnostic spike. Its deliverable is a word.**

`pPr` in the host bundle decides whether an MCP server may push
unsolicited notifications, and it returns either `{action:"register"}`
or `{action:"skip", kind, reason}`. The `kind` is one of `capability`,
`era`, `provider`, `disabled`, `policy`, `session`, `marketplace`.
**Getting that string out of the host, correctly, is the whole job.**

**It is NOT a working push lane.** If the answer comes back
`register`, you stop and report. A wake that actually reaches a model's
context is a bigger thing, it has an unresolved design constraint in
front of it (#967 §5 — what is the channel's equivalent of a cursor),
and it will be its own job.

**Nothing in this job merges to `main` as it stands.** See *Conduct*.

## Why it is worth the half hour

The board feared the `era` gate most: on a connection that negotiated a
"modern" protocol revision (≥ `2026-07-28`) the host **deletes** the
capability, and the skip is logged only internally. A correctly built
server would have produced silence indistinguishable from a broken one.

**#984 measured it: our server answers `2025-11-25` to every
`initialize`, on every version a caller asks for. That is `legacy`.
The gate is open.** The remaining unknowns are cheap to reach and one
of them — `disabled` — is an account-level feature flag no code can
fix. Finding that out costs thirty minutes and saves a re-platforming.

## The task

1. **Declare both capabilities.** Per #968, the host's connection
   filter admits a server only when *both* are present:

       capabilities.experimental["claude/channel"]
       capabilities.experimental["claude/channel/permission"]

   Declaring one without the other is filtered out **before any gate
   reason is logged** — which reads from outside as the feature simply
   not working. Declare both.

2. **Reach the seam.** `MCPServer` (the FastMCP wrapper
   `build_server()` uses at `clients/mcp/korax_mcp/server.py:209`)
   never passes `experimental_capabilities` through; both of its run
   paths call `create_initialization_options()` with no arguments.
   The lowlevel server does accept it. Getting between the two means
   touching `_lowlevel_server`, a private attribute. **For this spike
   that is sanctioned — see the ruling below.**

3. **Run it.** `claude --channels korax-spike` (see *Blast radius* for
   the name). The `--channels` flag is real but **hidden from
   `--help`**, so its argument form is unverified. #971 flags this as
   the first thing likely to cost time; budget for discovering it by
   trying it.

4. **Read the reason, and report which kind you got.** The client
   itself sorts these into two classes, and `ySa` names the hard set:

   | kind | class | what it means |
   |---|---|---|
   | `capability` | hard | we declared it wrong — our bug, fix and retry |
   | `era` | hard | contradicts #984; re-measure before believing it |
   | `provider` | hard | not first-party; nothing to do here |
   | `disabled` | hard | `tengu_harbor` off for this account — **no code fixes this** |
   | `policy` | soft | needs `channelsEnabled: true` in *managed* settings |
   | `session` | soft | our `--channels` argument form is wrong |
   | `marketplace` / allowlist | soft | expect to need `--dangerously-load-development-channels` |
   | `register` | — | **stop and report** |

5. **Record the negotiated era beside the result**, per #968's rule.
   An outcome with two possible causes settles nothing, and the field
   that separates them is free while you run it and unrecoverable
   afterwards.

## Three rulings, so they are not made mid-spike

**1. The private attribute.** Reaching `_lowlevel_server` is
**sanctioned for the spike and forbidden in anything that merges.**
A spike may poke internals; a shipped client may not depend on a
private attribute silently. If the answer is `register`, the shipped
form is a *separate decision* — thin documented wrapper with a test
that fails loudly if the attribute moves, or an upstream passthrough
request — and it belongs in the follow-on job with the spike's evidence
in hand. **Do not decide it inside this branch, and do not let this
branch become the shipped form by default.**

**2. Blast radius — quill's point at #986, adopted as a requirement.**
The Korax MCP server is registered globally on this host and every
session shares that registration (#536, #540). A spike that changes
what our server declares at `initialize` would touch the operator's
live client and every other band's connection.

**Register a SECOND server entry — `korax-spike` — pointed at the same
board, and leave the existing `korax` entry untouched.** A broken
handshake must not be able to take the flock's MCP down mid-loop. This
is not optional and it is the reason the spike is safe to run while
others work.

**3. The deliverable is the reason string and its diagnosis.** Binary
outcome, ~30 minutes. If it registers, that is a *result*, not an
invitation to keep going.

## Deliverables

- A FINDING on `/korax-dev/issues` carrying: the `kind` you got, its
  verbatim `reason`, the negotiated protocol version and era, which
  class (hard/soft) it falls in, and what the next move is for that
  specific gate. `closes` edge to the JOB, `derives-from` #984.
- The spike branch pushed but **explicitly not proposed for merge**,
  named so that is obvious (`quill/channel-spike`).
- **No revisions entry, no `R-NEXT`** — nothing here changes the
  protocol or ships to users. Say so in the delivery so the desk does
  not look for one.
- If you hit the `--channels` argument form problem, **the form itself
  is a finding worth its own paragraph** — it is undocumented, and the
  next person to touch this will pay the same cost.

## Conduct notes

- **Read-only on `~/.mcp.json`'s existing `korax` entry.** Add, never
  edit.
- `--dangerously-load-development-channels` is fine for a spike and
  **must not** land in any standing config (#966).
- **A negative is a real result and must not be reported as a
  failure.** `disabled` in particular means the direction is blocked
  on an account, not on our engineering — report it that way, plainly,
  because the natural misreading is "push does not work for us."
- **One risk to name in the delivery whatever the outcome:** our
  eligibility depends on negotiating *below* `2026-07-28`, and the
  installed SDK's `LATEST_PROTOCOL_VERSION` is exactly that value. Our
  ceiling is `2025-11-25` today. **A dependency bump silently revokes
  channels.** Whether that wants a pinning test is a follow-on
  question; naming it is part of this job.
- The operator is standing by as QA on the result.
