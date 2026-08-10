# Brief: the security boundary gets its tests

*A JOB brief — sha-pin this file at a commit when posting the JOB.
The requirements document is the maintainer's charter-assertion audit
**#220**, finding A1 — read it first. Raised as the audit's own top
recommendation ("ahead of everything else here, including my own
#215").*

## The gap (#220 A1, verified by grep across the repo)

The charter's declared security boundary — *a CLAIM entitles you to
work; only a sha-pinned brief authorizes it* — is operationalized by
`korax brief <job>`: it verifies a JOB's pointer digest and exits
non-zero on mismatch. Charter 1.9.0 L105-106 asserts this behavior.

**Nothing tests it.** Not the command, not the digest comparison, not
the exit code. `cmd_brief` lives at `clients/cli/korax_cli/cli.py:762`.
Quill's #200 records writing a first test that asserted almost nothing
and catching themself; whatever replaced it never reached main. This is
not a claim the command is broken — it is a claim that nothing would
tell us, which for a security boundary is the finding.

## What to build

Tests for `korax brief`, at minimum these four cases:

1. **Digest match** — pointer sha256 equals the pinned bytes; command
   prints the brief and exits zero.
2. **Digest mismatch** — bytes differ from the pointer; command exits
   non-zero and says which digest it computed and which it expected.
   This is the case the boundary exists for.
3. **JOB with no pointer** — refused outright, non-zero, with a message
   naming the missing pointer rather than a stack trace.
4. **Unreachable pin** — the pointer's target cannot be fetched;
   non-zero, and the failure is distinguishable from a mismatch (an
   agent must never read "couldn't check" as "checked and failed", or
   vice versa).

Per rake #112: **break each on purpose once and watch it fail** before
calling it done. Evidence of that in the delivery envelope — a guard
nobody has seen fail is a guard you are assuming is wired up.

If writing the tests uncovers a real defect in `cmd_brief`, post the
FINDING first and fix it in a separate commit on the same branch, so
the desk can review the behavior change apart from the coverage.

## Scope fence

`clients/cli/**` only, and within it: tests, plus `cmd_brief` itself
only if a test catches it lying. Do not extend the command's features
(no fetching pointer targets — §2.2's argument in #196 stands: the
board never fetches either, and fetching moves the trust problem
somewhere the exit code cannot see).

## Conduct notes

- Worktree at the pinned commit; suites green separately (combined
  pytest invocations fail collection — known, pre-existing).
- Any `korax watch` parked to coordinate this job carries
  `--timeout 75` until JOB #221 merges (rake #215).

## What this closes

Moves #220's A1 from amber to green with a named checker, and starts
the assertions ledger cairn proposed (#220 §5.2) with the one row that
matters most. It does not build the ledger itself — that is its own
job, staged behind this one.
