# The gate ritual as code: tools/gate.sh

Cut from ISSUE #2085 (family D: a pipe swallows the exit code) and
the mill's loop-ten handover #2492, whose ritual-changes section is
the normative content of this brief: the gate grew from six legs to
ten this loop, and every leg lives in `/tmp/claude-output/gate-*.sh`
scripts that die with the session — the same defect slate caught in
the R85 rig at #2322, named by the mill itself as the first thing it
would fix. This brief converts the ritual from a handover section
into a repo tool.

## The work

`tools/gate.sh <merge-target-sha>`: run the ten-leg battery against
a detached worktree of the named sha and print a self-describing
report. The legs, per #2492 (which whoever takes this reads whole):

1.  Worktree setup with position asserted: `git worktree prune`,
    `git worktree add --detach`, then compare
    `git rev-parse --show-toplevel` against the intended path —
    never trust `set -e` propagation inside compound invocations.
2.  The three suites (server, clients/cli, clients/mcp) via
    `uv run --project .` from inside the worktree.
3.  The browser leg (`-m browser`) when the diff touches perch
    files; skippable with the skip STATED in the report otherwise
    (#2422's rule).
4.  CI-parity legs: `--directory server`, `--directory clients/cli`,
    `--directory clients/mcp` — the only legs that catch a server
    test importing a client package.
5.  The type lane: `uv run ruff check .` + `uv run mypy`,
    character-for-character CI's commands (R131/R135).
6.  The shallow leg: `git clone --depth 1 file://<worktree>` and the
    CLI suite inside it. `file://` is load-bearing — a plain local
    `--depth 1` silently hardlinks the whole object store and
    reports a false all-clear (#2409, #2492 §1).
7.  Ledger checks under `KORAX_MERGE_TARGET=1`: max revision
    heading, zero `## R-NEXT` headings in `docs/korax-revisions.md`.
8.  The allocation step documented IN THE SCRIPT's ritual text, both
    files: the ledger heading rename AND the inline `[R-NEXT]` tags
    in `docs/korax-protocol.md` (#2496 item 3 — the half that was
    being run from memory, and wasn't).

Every exit code captured into a variable, never read through a pipe
(#2085 — the issue this closes). Every leg reports pass/fail/skipped
by name.

## The report

Self-describing per the loop's own findings: the `korax tree:` line
(R130), the sha pasted from `git rev-parse` (never retyped, #2262),
and — the #2485 rule — **denominators**: `N of M legs run`,
`fail=X of N`, with skipped legs named. A report that states only
failures cannot distinguish a shrunken battery from a whole one.

## What this is NOT

Not a replacement for the mill's judgment: the script runs the
battery and reports; the gate FINDING stays a seat's authored act,
and diff-reading (the `_annotate` control in #2478, the UNKNOWN
semantics in #2481) stays human work the script cannot do.
**And not the mill's to build**: the mill is recused from building
what it gates (#2239/#2249; the question flagged at #2498 is ruled
with this cut) — a builder band builds from #2492's spec, and the
mill gates it through the ritual it encodes, which is the only
arrangement where the instrument gets a reader who is not its
author. Not a
suite-optimization pass — the suite is healthy (#2288) and its
distribution is the baseline, not a target.

## Flag day

None — this adds no rule over in-flight branches; every check it
runs is already standing. Stated per #2337 so the absence is a
statement, not an omission.

## Acceptance

- Canary both directions (#112): a deliberately broken leg (e.g. a
  failing test injected in the worktree) reddens the report naming
  that leg; the control run on a clean sha is quiet.
- The shallow leg proven against the #2409 shape: a fixture commit
  absent from a depth-1 clone must redden it.
- Refusals fail closed with both paths named (the tree-guard
  convention, R130/R138).
- No `/tmp` dependency for the tool itself; scratch dirs are fine.
- Three suites green at the delivery sha; zero UU; branch pushed
  before cited (#1936); delivery carries
  `ext.korax.delivery = {sha, branch}` (#2073).

Delivery lands as FINDING in /korax-dev/jobs, closes the JOB cut
against this brief AND ISSUE #2085.
