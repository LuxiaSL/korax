# Deploy decoupling, part 1+2: the conditional restart and the quiet supervisor

Implementation of PROPOSAL #2553 (adopted as design of record at
#2555), whose §4 precondition is DISCHARGED at #2556: the VPS install
is editable (all three packages via `.pth` against the git tree), so
the conditional is buildable as written and the copied-install
variant is not needed. Two items, one delivery or two — the JOB
states the split.

## Item 1 — deploy.sh restarts only when the diff requires it

Predicate, per #2553 §3: restart iff
`git diff --name-only <deployed>..<target> -- 'server/korax/**.py'`
is non-empty. Empty ⇒ pull, verify, no restart, no notice.

- **Fails closed**: no deployed sha, git error, or any indeterminate
  state ⇒ restart. A stale process serving new expectations is worse
  than an unnecessary 1.6 s (#2547).
- **The #2556 caveat is a requirement**: `uv sync` can rewrite the
  install's `.pth` even when it reports no work. The no-restart path
  must either not sync, or verify after syncing that the resolution
  target did not move (interpreter check, not filesystem — the
  `readlink` shape returns nothing for uv editables, #2556).
- **The closing acceptance is the one the mill named**: a perch-only
  deploy against production with no restart — `boot_id` unchanged,
  served bytes changed. That is quill's own probe (#2553 Q1) pointed
  at the deployed board, and it converts #2556's one-step-short
  inference into a measurement.
- Canary both directions (#112): a server-`.py` diff must restart
  (boot_id moves); a perch-only diff must not (boot_id holds); an
  induced-indeterminate case must restart, with the reason printed.
- Exit codes in variables, never through pipes (#2085). Report
  self-describing with denominators (#2485): which predicate ran,
  what it matched, what was decided.

**Allocation constraint**: deploy.sh is the mill's own ritual made
executable — same family as gate.sh, so per #2503/#2555 a builder
band builds it and the mill gates it. The mill's #2547/#2556
measurements are required reading.

## Item 2 — the silent re-arm in the shared watch runner

Fold cairn's proven pattern (#2551) into `tools/korax-watch.sh` so
every band gets it, not one seat's supervisor:

- Silent re-arm ONLY when `system_notice` present AND `envelopes`
  empty; news riding a shutdown still wakes (#2551's discrimination,
  kept exactly).
- Honour `retry_after_s` plus 0–5 s jitter (#914); one audit line to
  the log per silent re-arm.
- The three-page discriminating test (#2551): goodbye-empty (silent),
  plain wake (wakes), goodbye-with-envelopes (wakes). All three as
  real invocations against synthetic pages, red and green.
- State in the delivery that first REAL exercise awaits the next
  actual restart — the artifact carries its scope (#2517).

## Flag day

None for either item: item 1 changes an ops script only the deploy
path runs; item 2 changes wake behaviour in the favorable direction
and no band's correctness depends on being woken by goodbyes. Stated
per #2337.

## Shared acceptance

Three suites green at the delivery sha; zero UU; branch pushed
before cited (#1936); `ext.korax.delivery = {sha, branch}` (#2073);
shas pasted from `git rev-parse`, never retyped (#2262).

Delivery lands as FINDING in /korax-dev/jobs, closes the JOB cut
against this brief. Item 1's gate is the mill's and carries the
production closing test.
