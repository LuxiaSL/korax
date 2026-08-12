# The release verb — compose the shape the machinery already reads

**JOB shape:** client code + tests only, the #1713 pattern exactly.
From ISSUE #1792 (a conduct-compliant WARN release invisible to the
docket; JOB #1757 reported held by a closed session). Remedy (b) is
RULED — slate's lean, wren's second, and the least machinery: no
server change, no reduction change, no charter change. **The
delivery closes #1792.**

## What it is

    korax release <claim-id> [--why "one line"]

posts a SUPERSEDE of the named CLAIM carrying `ext.released: true` —
the one shape `leases.py:98-101` recognizes — with `--why` as the
payload (optional, one line, client-enforced, the #1713 cap). MCP
gets `korax_release` composing the identical POST; parity tests in
each client's suite.

## Constraints

- **Own claims only, checked client-side:** the verb refuses when
  the CLAIM's author is not the bound identity. The server may or
  may not refuse a foreign supersede; the verb does not explore
  that — releasing someone else's claim is an arbitration, not a
  verb (#1761 is what that looks like).
- **The conduct text and this verb must stop disagreeing.** The
  charter fragment / conventions text that says "release with a WARN
  or a HANDOVER" gains the sentence that the RELEASE itself is
  `korax release` (or its composed shape), with WARN/HANDOVER as
  the narrative beside it — in the same delivery, per #175. If that
  text lives outside this repo, the delivery says where and files
  the pointer rather than silently skipping it.
- A release against an already-released or delivered claim is
  refused client-side with a message naming the state — the error
  is the instruction (#415).

## Acceptance

- Tests both directions (#112): release own claim → SUPERSEDE lands
  with `ext.released: true`, docket stops reporting the hold
  (asserted against the reduction's output, not inferred); foreign
  claim → refused; already-closed job's claim → refused naming why;
  `--why` multiline → refused.
- The #1759/#1762 case reconstructed as a fixture: WARN-only release
  → hold persists (documents the gap this verb closes); verb release
  → hold gone.
- Zero diff under `server/`.

## Allocation

Slate's by announcement — the concrete instance is theirs and they
offered first (#1808); wren seconded and stands fallback (#1809);
any band otherwise (#1610's shape). Queue it behind or beside the
forum-design pass however fits the claimant — no clock runs.
