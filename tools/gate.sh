#!/usr/bin/env bash
#
# tools/gate.sh — the gate ritual as code. JOB #2504, closes ISSUE #2085.
#
# WHAT THIS IS. The mill's battery grew from six legs to ten across loop
# ten, and every one of them lived in `/tmp/claude-output/gate-*.sh`,
# which dies with the session. #2492 named that as the first thing the
# seat would fix and could not fix it itself: the mill is recused from
# building what it gates (#2239/#2249, ruled onto this JOB at #2503).
# The normative spec is #2492's ritual-changes section, as corrected by
# the gavel at #2514 and the mill at #2518.
#
# THE THREE PROPERTIES THAT DECIDED THE SHAPE
#
# 1. EVERY EXIT CODE IS CAPTURED INTO A VARIABLE, NEVER READ THROUGH A
#    PIPE. That is ISSUE #2085, which this closes, and it is not a style
#    preference: `cmd | tee log && next` reports tee's success as cmd's,
#    so every `&&` after a pipe is a lie about what succeeded. Here each
#    leg redirects to a file and `$?` is read on the next line.
#
# 2. THE DENOMINATOR COMES FROM THE DECLARATION, NOT FROM THE LOOP.
#    `LEG_NAMES` is written down before anything runs, and M is its
#    length. A report that counts what it happened to run cannot tell a
#    shrunken battery from a whole one — ten legs and six legs both
#    print `fail=0`. That is #2485's rule, and it is the same defect
#    reproduced in `tools/r85_compare.py` at #2482, where removing a
#    probe silently shrank the table and still rendered a clean pass.
#    A gate is exactly where that must not happen, so the count is
#    declared and every leg is accounted for as ran / skipped / failed.
#
# 3. A LEG THAT CANNOT FAIL IS NOT A CHECK, SO THE CONTROLS ARE INSIDE
#    THE INSTRUMENT. The shallow leg carries its own control (see
#    `run_shallow_leg`) rather than relying on somebody having run a
#    canary once, in a session that is now gone. #2518's own framing: a
#    canary that can only fire in the red direction cannot distinguish a
#    working check from a vacuous one.
#
# A SKIP IS NOT A PASS, AND AN UNOWED RUN IS NOT AN OWED ONE. Legs
# report in three states — `RAN (owed)`, `RAN (not owed)`, `SKIPPED` —
# so a deliberate over-measurement (the mill's R137/R138 gate ran the
# browser leg although no perch file was in the diff) stays
# distinguishable from a required run and from a skip (#2518 §1).
#
# WHAT THIS IS NOT. Not a replacement for the mill's judgment. The
# script runs the battery and reports; the gate FINDING stays a seat's
# authored act, and diff-reading — the `_annotate` control in #2478,
# the UNKNOWN semantics in #2481 — stays human work no script does.
#
# ELEVEN LEGS, TEN COMMANDS. #2478's table counts ruff and mypy
# separately and the gavel settled M = 10 at #2514. Since R135/#2379,
# `uv run tools/type_lane.py` IS the lane and the bare commands are not
# citable as delivery evidence — so ONE invocation reports TWO legs,
# attributed from the wrapper's own `lane FAILED: <names>` line. If that
# line cannot be parsed the failure is attributed to BOTH, because
# guessing which checker passed is the one direction that fails green.
#
# LEG 11 IS THE LEDGER-DISPOSITION GUARD (#2680 → #2682). A delivery
# that owes a ledger entry and brings none passed all nine tests in
# `test_revisions_ledger.py` — every one of them is a property of a
# heading that IS present, and none can observe an entry that was never
# written (`214a776`, #2671/#2673). M moves 10 → 11 for exactly that
# reason, and it is a deliberate act named at this leg's own delivery,
# not a side effect (#2680's own framing, applied to itself).
#
# USAGE
#   tools/gate.sh <merge-target-sha> [--base <ref>] [--keep] [--branch]
#
#   --base <ref>  Compute the diff against <ref> to decide whether the
#                 browser leg is owed (#2422). WITHOUT IT THE BROWSER
#                 LEG RUNS and is reported `RAN (not owed)`: this fails
#                 toward measuring, because a leg skipped for an unknown
#                 reason is indistinguishable from one that was not owed.
#   --keep        Leave the worktree and logs in place for inspection.
#   --branch      Pre-delivery self-check on a BRANCH: unset
#                 KORAX_MERGE_TARGET, because an unrenamed `## R-NEXT`
#                 heading is correct there. Two ledger guards then
#                 SKIP, and the report says so rather than implying
#                 the strict battery ran.

set -uo pipefail
# NOTE: deliberately NOT `set -e`. Legs are EXPECTED to fail — that is
# the output — and `set -e` inside a compound invocation does not abort
# reliably anyway (#2492 §2, the incident that put seven commits on the
# tree six bands share). Position is asserted; failure is not inferred
# from propagation.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
readonly SELF_DIR REPO_ROOT

# ── the battery, DECLARED ─────────────────────────────────────────────
# M lives here. Adding a leg means adding a name here AND a case below;
# a name here that nothing runs is reported `MISSING — NOT REACHED`
# rather than silently dropped from the count, and `run_leg` refuses a
# leg that is not declared.
readonly LEG_NAMES=(
  suite-server
  suite-cli
  suite-mcp
  browser
  ci-server
  ci-cli
  ci-mcp
  ruff
  mypy
  shallow
  ledger-disposition
)
readonly LEG_COUNT=${#LEG_NAMES[@]}

#: Where the perch actually lives. BOTH roots are load-bearing: the
#: browser tests execute driver `.js` files that sit in `server/tests/`
#: (`test_perch_smoke.py:43` -> `perch_smoke_driver.js`), so a
#: driver-only change alters what the browser leg RUNS while touching
#: nothing under `server/korax/perch/`. A predicate naming only the app
#: directory reports `SKIPPED (no perch files)` truthfully, about the
#: wrong question (#2518 §2, whose own path set had this gap; verified
#: at #2520). `clients/perch/**` is deliberately absent — no such
#: directory exists, and a pathspec nobody can trip is indistinguishable
#: from one that is watching.
readonly PERCH_PATHS=(
  'server/korax/perch/**'
  'server/tests/*perch*'
)

# ── state ─────────────────────────────────────────────────────────────
declare -A LEG_STATUS=()   # name -> PASS | FAIL | SKIP
declare -A LEG_DETAIL=()   # name -> one-line summary or reason
declare -A LEG_OWED=()     # name -> owed | unowed  (only when it RAN)
#: Process GROUPS this script created, one per leg. Teardown reaps these
#: and nothing else — the same rule `server/tests/perch_rig.py` follows,
#: and for the same reason: an early probe for that work identified a
#: tree by SESSION and killed the shell running it (#2633). `killpg` is
#: safe here only because these groups are ours by construction.
LEG_PGIDS=()
LEDGER_LINES=()

TARGET_SHA=""
BASE_REF=""
KEEP=0
WT=""
LOGDIR=""
SCRATCH=""

die() {
  printf 'gate.sh: %s\n' "$*" >&2
  exit 2
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --base)
        [ $# -ge 2 ] || die "--base needs a ref"
        BASE_REF="$2"; shift 2 ;;
      --keep) KEEP=1; shift ;;
      --branch) MERGE_TARGET=0; shift ;;
      -h|--help) sed -n '1,60p' "${BASH_SOURCE[0]}"; exit 0 ;;
      -*) die "unknown option: $1" ;;
      *)
        [ -z "$TARGET_SHA" ] || die "more than one sha given: $TARGET_SHA and $1"
        TARGET_SHA="$1"; shift ;;
    esac
  done
  [ -n "$TARGET_SHA" ] || die "usage: tools/gate.sh <merge-target-sha> [--base <ref>] [--keep] [--branch]"
}

# ── precondition: the worktree, with POSITION ASSERTED ────────────────
# A precondition, not a leg: if it does not hold, nothing runs and there
# is no battery to report on, so it refuses (exit 2) rather than
# counting. #2492 §2 is the reason — `git worktree add` failed on a
# stale path, the `cd` failed, and `set -euo pipefail` did not abort
# because the failure sat inside a compound `bash -c`. Assert position;
# never trust propagation.
setup_worktree() {
  local full_sha rc
  full_sha="$(git -C "$REPO_ROOT" rev-parse --verify "${TARGET_SHA}^{commit}" 2>/dev/null)"
  rc=$?
  [ $rc -eq 0 ] && [ -n "$full_sha" ] || die "not a commit in this repo: $TARGET_SHA"
  TARGET_SHA="$full_sha"

  SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/korax-gate-XXXXXX")"
  WT="$SCRATCH/wt"
  LOGDIR="$SCRATCH/logs"
  mkdir -p "$LOGDIR" || die "could not create log dir $LOGDIR"

  git -C "$REPO_ROOT" worktree prune
  git -C "$REPO_ROOT" worktree add --detach "$WT" "$TARGET_SHA" \
      > "$LOGDIR/worktree-add.log" 2>&1
  rc=$?
  [ $rc -eq 0 ] || die "worktree add failed (rc=$rc); see $LOGDIR/worktree-add.log"

  # `--show-toplevel` also catches the right directory of the WRONG
  # repository, which a plain `[ "$PWD" = "$WT" ]` does not (#2492 §2's
  # stronger form).
  local top want got head
  top="$(cd "$WT" && git rev-parse --show-toplevel 2>/dev/null)"
  [ -n "$top" ] || die "could not read toplevel inside $WT"
  want="$(cd "$WT" && pwd -P)"
  got="$(cd "$top" && pwd -P)"
  [ "$want" = "$got" ] || die "position assertion FAILED: expected $want, git says $got"

  head="$(cd "$WT" && git rev-parse HEAD 2>/dev/null)"
  [ "$head" = "$TARGET_SHA" ] || die "worktree HEAD is $head, expected $TARGET_SHA"
}

# ── one leg ───────────────────────────────────────────────────────────
# Output goes to a FILE by redirection, never through a pipe, which is
# what keeps `$?` the command's own (#2085).
#: CI sets this on main (`ci.yml`: `github.ref == 'refs/heads/main'`),
#: and TWO guards in `test_revisions_ledger.py` skip without it: the
#: zero-`R-NEXT`-headings check and the inline-tag check. A merge gate
#: that does not set it cannot reproduce the one condition it exists to
#: reproduce, and renders those two as ordinary skips — environment
#: noise rather than checks that never ran. That omission bounced this
#: tool's own first delivery (#2634): the blind spot concealed an
#: unsubstituted tag in the ledger entry shipping the tool.
#:
#: ON BY DEFAULT, because this tool's argument is a MERGE-TARGET sha and
#: at a merge target the allocation step has already renamed the
#: heading. `--branch` turns it off for a claimant's pre-delivery
#: self-check, where an unrenamed `## R-NEXT` heading is CORRECT and the
#: strict guard would fire on the one thing the branch is supposed to
#: carry. **The mode is REPORTED either way** — a battery that ran the
#: weaker environment must not be indistinguishable from one that ran
#: the strict one, which is this tool's own denominator rule applied to
#: its environment rather than to its legs.
MERGE_TARGET=1

run_leg() {
  local name="$1" owed="$2"; shift 2
  _assert_declared "$name"
  printf '  %-12s ... ' "$name" >&2
  local env_args=()
  [ "$MERGE_TARGET" -eq 1 ] && env_args=(KORAX_MERGE_TARGET=1)
  # `set -m` puts the background job in its OWN process group whose pgid
  # equals its pid, which is what makes `kill -- -$pid` reach the whole
  # leg — pytest, the server it spawns, and Chrome's ~14 descendants.
  # Without it an interrupted gate leaves the tree running AND deletes
  # its scratch dir out from under it (#2611).
  set -m
  ( cd "$WT" && env "${env_args[@]}" "$@" ) > "$LOGDIR/$name.log" 2>&1 &
  local leg_pid=$!
  LEG_PGIDS+=("$leg_pid")
  wait "$leg_pid"
  local rc=$?
  set +m
  forget_leg "$leg_pid"
  LEG_OWED[$name]="$owed"
  if [ $rc -eq 0 ]; then
    LEG_STATUS[$name]=PASS
    LEG_DETAIL[$name]="$(summarise "$LOGDIR/$name.log")"
    printf 'PASS\n' >&2
  else
    LEG_STATUS[$name]=FAIL
    LEG_DETAIL[$name]="rc=$rc — $(summarise "$LOGDIR/$name.log")"
    printf 'FAIL (rc=%d)\n' "$rc" >&2
  fi
}

skip_leg() {
  local name="$1" reason="$2"
  _assert_declared "$name"
  LEG_STATUS[$name]=SKIP
  LEG_DETAIL[$name]="$reason"
  printf '  %-12s ... SKIP (%s)\n' "$name" "$reason" >&2
}

_assert_declared() {
  local name="$1" n
  for n in "${LEG_NAMES[@]}"; do [ "$n" = "$name" ] && return 0; done
  die "internal: leg '$name' is not in LEG_NAMES — the declaration is the denominator"
}

# Read the tally out of a log FILE. Nothing here can eat an exit code:
# the leg's rc was captured before this is ever called.
summarise() {
  local log="$1" line
  line="$(grep -aE '[0-9]+ (passed|failed|error)' "$log" 2>/dev/null | tail -n 1)"
  [ -n "$line" ] || line="$(grep -av '^[[:space:]]*$' "$log" 2>/dev/null | tail -n 1)"
  printf '%s' "${line:-(no output)}"
}

# ── is the browser leg owed? (#2422) ──────────────────────────────────
browser_is_owed() {
  [ -n "$BASE_REF" ] || return 1          # no base -> not *owed*; runs anyway
  local base_sha changed
  base_sha="$(git -C "$REPO_ROOT" rev-parse --verify "${BASE_REF}^{commit}" 2>/dev/null)"
  [ -n "$base_sha" ] || return 1
  changed="$(git -C "$REPO_ROOT" diff --name-only "$base_sha" "$TARGET_SHA" \
             -- "${PERCH_PATHS[@]}" 2>/dev/null)"
  [ -n "$changed" ]
}

# ── the ledger-disposition primitives (#2680 → #2682) ─────────────────
# Each takes REPO/BASE/TARGET as explicit arguments, unlike
# browser_is_owed above — this leg's own decision logic (four cases over
# two signals, one of them a contradiction) is complex enough that a
# test reimplementing it in Python risks silently agreeing with a bug in
# the real one (#2668's canary rule). Parameterized, the acceptance
# suite calls THESE functions directly, against planted fixture repos,
# instead of restating their logic.
ledger_disposition_is_owed() {
  local repo="$1" base_sha="$2" target_sha="$3" changed
  changed="$(git -C "$repo" diff --name-only "$base_sha" "$target_sha" 2>/dev/null)"
  [ -n "$changed" ] || return 1
  printf '%s\n' "$changed" | grep -qvE '^docs/'
}

# ── entry_added / trailer_present ask about TARGET'S OWN FIRST-PARENT
# DIFF, never the caller-supplied --base (#2777's WARN; quill found a
# hole in the first fix at #2782, ruled at #2783; #2786/#2790 confirm
# independently). A base gated more than one revision back sweeps
# UNRELATED intervening revisions into base..target — a delivery
# bringing no entry of its own could then read "entry added" (or
# "trailer present") by inheriting somebody else's, which is the exact
# vacuity leg 11 exists to prevent, one layer up from #2688's inherited-
# heading property. For a real two-parent merge, target^1 IS the
# accurate pre-merge mainline regardless of how many commits the
# feature branch carried — a TREE diff, unlike a commit-by-commit walk,
# cannot miss intermediate commits. For a non-merge target (a direct or
# `--branch`-mode commit), target^1 is its own true predecessor, which
# is the right question there too (#2783 ruling 2) — no special case
# needed. owed() below deliberately does NOT move: over-triggering
# `owed` from a too-far-back base is the same safe direction
# browser_is_owed already accepts (asks for more than strictly needed,
# never less); only entry/trailer have a defect-HIDING failure mode, so
# only they need base-independence.
#
# AT MOST TWO PARENTS, ASSERTED NOT ASSUMED (#2783 ruling 2): the desk
# merges one branch at a time, so an octopus target is a precondition
# violation this leg refuses rather than interprets. A root commit (no
# parent) is likewise refused rather than diffed against nothing — not
# a shape this repo's real history produces, and guessing at empty-tree
# semantics for a case that cannot occur here is not worth the surface.
ledger_disposition_parent_count() {
  local repo="$1" target_sha="$2"
  git -C "$repo" show -s --format=%P "$target_sha" 2>/dev/null | wc -w
}

# THE ENTRY MUST ARRIVE, NOT BE INHERITED (#2688's sharpening on the
# brief): grepping the diff's ADDED lines — never the file's resting
# content at target — is what keeps a heading that was already present
# at target^1 from reading as this delivery's own.
ledger_disposition_entry_added() {
  local repo="$1" target_sha="$2"
  # BOTH SPELLINGS OF "AN ENTRY ARRIVED" (#2777's WARN, ruled #2779).
  # On a branch the added heading is `## R-NEXT`; on a merge target it
  # is already `## R<N>`, because the desk's number substitution IS
  # the merge. Safe under first-parent for the identical reason it was
  # safe under base-relative (#2786/#2790's unreachability argument):
  # main can never carry an unrenamed `## R-NEXT`
  # (`test_no_r_next_on_the_merge_target`, enforced via
  # `KORAX_MERGE_TARGET` on `refs/heads/main` in CI), so there is never
  # an INHERITED `## R-NEXT` for a rename to produce — a rename can only
  # ever apply to a heading the branch itself brought.
  git -C "$repo" diff "${target_sha}^1" "$target_sha" -- docs/korax-revisions.md 2>/dev/null \
    | grep -qE '^\+##[[:space:]]+R(-NEXT|[0-9]+)\b'
}

# THE ESCAPE IS A COMMIT TRAILER, NEVER SILENCE (#2682 ruling 2): a
# delivery legitimately owing no entry (a tightening repair, #2550's
# criterion) states so IN THE ARTIFACT. The exact spelling is this
# leg's to fix (ruled) — `Ledger: none` as a trailer-shaped line,
# anywhere in the commits THIS delivery brought, is read as present
# regardless of which one carries it. `target^1..target_sha` walks
# exactly those commits for a real merge (everything reachable from the
# merge but not from its mainline parent) and exactly one commit for a
# direct delivery — never an unrelated earlier delivery's trailer,
# which a stale caller-supplied base could otherwise sweep in.
ledger_disposition_trailer_present() {
  local repo="$1" target_sha="$2"
  git -C "$repo" log --format=%B "${target_sha}^1..${target_sha}" 2>/dev/null \
    | grep -qE '^Ledger:[[:space:]]*none\b'
}

# ── the type lane: ONE command, TWO legs ──────────────────────────────
run_lane_legs() {
  printf '  %-12s ... ' "ruff+mypy" >&2
  set -m
  ( cd "$WT" && uv run tools/type_lane.py ) > "$LOGDIR/type-lane.log" 2>&1 &
  local lane_pid=$!
  LEG_PGIDS+=("$lane_pid")
  wait "$lane_pid"
  local rc=$?
  set +m
  forget_leg "$lane_pid"
  LEG_OWED[ruff]=owed
  LEG_OWED[mypy]=owed

  if [ $rc -eq 0 ]; then
    LEG_STATUS[ruff]=PASS;  LEG_DETAIL[ruff]="clean (via tools/type_lane.py)"
    LEG_STATUS[mypy]=PASS;  LEG_DETAIL[mypy]="clean (via tools/type_lane.py)"
    printf 'PASS (both)\n' >&2
    return
  fi

  local failed_line
  failed_line="$(grep -a 'lane FAILED:' "$LOGDIR/type-lane.log" 2>/dev/null | tail -n 1)"
  if [ -z "$failed_line" ]; then
    # FAIL CLOSED. The wrapper went red without naming a checker, so
    # attributing the pass to either one would be a guess in the only
    # direction that fails green.
    LEG_STATUS[ruff]=FAIL
    LEG_STATUS[mypy]=FAIL
    LEG_DETAIL[ruff]="lane rc=$rc, no 'lane FAILED:' line to attribute — failing closed"
    LEG_DETAIL[mypy]="lane rc=$rc, no 'lane FAILED:' line to attribute — failing closed"
    printf 'FAIL (rc=%d, unattributed -> both)\n' "$rc" >&2
    return
  fi

  local name
  for name in ruff mypy; do
    case "$failed_line" in
      *"$name"*)
        LEG_STATUS[$name]=FAIL
        LEG_DETAIL[$name]="named in: ${failed_line#*lane FAILED: }" ;;
      *)
        LEG_STATUS[$name]=PASS
        LEG_DETAIL[$name]="not named in the lane's failure line" ;;
    esac
  done
  printf 'FAIL (%s)\n' "${failed_line#*lane FAILED: }" >&2
}

# ── the shallow leg, WITH ITS OWN CONTROL ─────────────────────────────
# `file://` IS LOAD-BEARING. A plain local `git clone --depth 1 <path>`
# silently hardlinks the whole object store and reports a false
# all-clear; git warns on STDERR (`--depth is ignored in local clones`)
# and a script capturing stdout drops it. That is #2409: a fixture using
# two real shas passed every local run and reddened CI, whose
# `actions/checkout@v4` clones at depth 1.
#
# THE CONTROL IS INSIDE THE LEG, not in a canary somebody ran once. The
# bare-path form is cloned too, and its commit count is REPORTED beside
# the file:// form. If the two are equal, `--depth` is being honoured
# locally on this git, the file:// form is not doing the work we think,
# and the leg says so instead of quietly passing (#2518 §4).
run_shallow_leg() {
  local shallow="$SCRATCH/shallow" control="$SCRATCH/shallow-control"
  LEG_OWED[shallow]=owed
  printf '  %-12s ... ' "shallow" >&2

  git clone --depth 1 "file://$WT" "$shallow" > "$LOGDIR/shallow-clone.log" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then
    LEG_STATUS[shallow]=FAIL
    LEG_DETAIL[shallow]="file:// clone failed (rc=$rc); see $LOGDIR/shallow-clone.log"
    printf 'FAIL (clone rc=%d)\n' "$rc" >&2
    return
  fi

  git clone --depth 1 "$WT" "$control" > "$LOGDIR/shallow-control-clone.log" 2>&1
  local n_shallow n_control n_source
  n_shallow="$(cd "$shallow" && git rev-list --count HEAD 2>/dev/null)"
  n_control="$(cd "$control" && git rev-list --count HEAD 2>/dev/null)"
  n_source="$(cd "$WT" && git rev-list --count HEAD 2>/dev/null)"

  if [ "$n_shallow" != "1" ]; then
    LEG_STATUS[shallow]=FAIL
    LEG_DETAIL[shallow]="file:// clone is NOT shallow (${n_shallow:-?} commits, want 1) — the leg would prove nothing"
    printf 'FAIL (not shallow: %s)\n' "${n_shallow:-?}" >&2
    return
  fi

  if [ "$n_control" = "$n_shallow" ]; then
    LEG_STATUS[shallow]=FAIL
    LEG_DETAIL[shallow]="CONTROL FAILED: bare-path clone is also ${n_control} commit(s), so file:// is not what makes this shallow — leg is vacuous"
    printf 'FAIL (control: bare path also %s)\n' "$n_control" >&2
    return
  fi

  set -m
  ( cd "$shallow" && uv run --project . pytest -q clients/cli/tests ) \
      > "$LOGDIR/shallow.log" 2>&1 &
  local shallow_pid=$!
  LEG_PGIDS+=("$shallow_pid")
  wait "$shallow_pid"
  rc=$?
  set +m
  forget_leg "$shallow_pid"
  local ctl="control: bare path ${n_control:-?} of ${n_source:-?} commits (--depth ignored locally, as it must be)"
  if [ $rc -eq 0 ]; then
    LEG_STATUS[shallow]=PASS
    LEG_DETAIL[shallow]="1-commit file:// clone; $(summarise "$LOGDIR/shallow.log") — $ctl"
    printf 'PASS\n' >&2
  else
    LEG_STATUS[shallow]=FAIL
    LEG_DETAIL[shallow]="rc=$rc in 1-commit clone — $(summarise "$LOGDIR/shallow.log") — $ctl"
    printf 'FAIL (rc=%d)\n' "$rc" >&2
  fi
}

# ── the ledger-disposition leg: LEG 11, a GUARD not an echo ───────────
# Cut from the mill's own routing (#2680), ruled at #2682. The four
# LEDGER_LINES `run_ledger_checks` prints below are unchanged display
# echoes of the suite's own guards (#2635); this is the exit-code-
# bearing check that makes an OWED-BUT-SILENT delivery a red gate
# instead of a near-miss two seats happened to catch by hand in the
# same ten minutes (`214a776`, #2671/#2673).
#
# DISPOSITION MUST BE EXACTLY ONE (#2682 ruling 3). Owed means the
# base..target diff touches any path outside docs/. When owed, exactly
# one of {an added `## R-NEXT` heading in the ledger diff, a
# `Ledger: none` trailer in base..target} must be present — zero of
# either is the `214a776` shape; BOTH at once is also red, because an
# entry that also claims to be none is a contradiction, not a stronger
# green.
#
# NO FALLBACK WITHOUT --base, UNLIKE THE BROWSER LEG. browser_is_owed
# can run its whole suite without a base (worst case: an unowed run);
# this leg's OWN CHECK, not just its owed-ness, is a question about a
# RANGE — with no base there is nothing to scan, so it skips rather
# than guessing at ownership.
run_ledger_disposition_leg() {
  if [ -z "$BASE_REF" ]; then
    skip_leg ledger-disposition "no --base given — this leg's own check needs the range, not just its owed-ness"
    return
  fi

  local base_sha
  base_sha="$(git -C "$REPO_ROOT" rev-parse --verify "${BASE_REF}^{commit}" 2>/dev/null)"
  if [ -z "$base_sha" ]; then
    skip_leg ledger-disposition "--base ${BASE_REF} does not resolve to a commit in this repo"
    return
  fi

  if ! ledger_disposition_is_owed "$REPO_ROOT" "$base_sha" "$TARGET_SHA"; then
    skip_leg ledger-disposition "diff against ${BASE_REF} touches only docs/ (or nothing) — not owed"
    return
  fi

  # AT MOST TWO PARENTS (#2783 ruling 2) — checked before entry/trailer,
  # which need target^1 to mean something. A precondition violation,
  # not a case to interpret: the desk merges one branch at a time.
  local n_parents
  n_parents="$(ledger_disposition_parent_count "$REPO_ROOT" "$TARGET_SHA")"
  if [ "$n_parents" -gt 2 ]; then
    LEG_OWED[ledger-disposition]=owed
    LEG_STATUS[ledger-disposition]=FAIL
    LEG_DETAIL[ledger-disposition]="target ${TARGET_SHA:0:12} has $n_parents parents (an octopus merge) — ledger-disposition only understands a direct commit or a two-parent merge; the desk merges one branch at a time, so this is a precondition violation, not a case to interpret"
    printf '  %-12s ... FAIL (%d parents)\n' "ledger-disposition" "$n_parents" >&2
    return
  fi
  if [ "$n_parents" -eq 0 ]; then
    LEG_OWED[ledger-disposition]=owed
    LEG_STATUS[ledger-disposition]=FAIL
    LEG_DETAIL[ledger-disposition]="target ${TARGET_SHA:0:12} has no parent (a root commit) — nothing to diff against; not a shape this repo's real history produces"
    printf '  %-12s ... FAIL (root commit)\n' "ledger-disposition" >&2
    return
  fi

  printf '  %-12s ... ' "ledger-disposition" >&2
  local entry_added=0 trailer_present=0
  ledger_disposition_entry_added "$REPO_ROOT" "$TARGET_SHA" && entry_added=1
  ledger_disposition_trailer_present "$REPO_ROOT" "$TARGET_SHA" && trailer_present=1

  LEG_OWED[ledger-disposition]=owed
  case $((entry_added + trailer_present)) in
    1)
      LEG_STATUS[ledger-disposition]=PASS
      if [ $entry_added -eq 1 ]; then
        LEG_DETAIL[ledger-disposition]="disposition: a ledger entry (## R-NEXT or ## R<N>) was added in ${TARGET_SHA:0:12}^1..${TARGET_SHA:0:12}"
      else
        LEG_DETAIL[ledger-disposition]="disposition: Ledger: none trailer present in ${TARGET_SHA:0:12}^1..${TARGET_SHA:0:12}"
      fi
      printf 'PASS\n' >&2 ;;
    0)
      LEG_STATUS[ledger-disposition]=FAIL
      LEG_DETAIL[ledger-disposition]="owed (diff touches paths outside docs/) but neither an added ledger entry nor a Ledger: none trailer is present"
      printf 'FAIL (no entry, no trailer)\n' >&2 ;;
    2)
      LEG_STATUS[ledger-disposition]=FAIL
      LEG_DETAIL[ledger-disposition]="both an added ledger entry AND a Ledger: none trailer are present — contradiction, a stated none alongside a real entry"
      printf 'FAIL (both entry and trailer)\n' >&2 ;;
  esac
}

# ── the battery ───────────────────────────────────────────────────────
run_battery() {
  printf 'running %d legs against %s\n' "$LEG_COUNT" "${TARGET_SHA:0:12}" >&2

  run_leg suite-server owed uv run --project . pytest -q server/tests
  run_leg suite-cli    owed uv run --project . pytest -q clients/cli/tests
  run_leg suite-mcp    owed uv run --project . pytest -q clients/mcp/tests

  # `KORAX_BROWSER_REQUIRED=1` IS CI'S SETTING AND THE HAND-RUN BATTERY
  # DID NOT HAVE IT. Without it a missing Chrome or node SKIPS
  # (`server/tests/test_perch_smoke.py:64`) and the leg exits 0 having
  # run nothing — a green leg that measured zero tests, which is this
  # file's own defect class. With it, a missing dependency fails naming
  # itself, exactly as on CI.
  if browser_is_owed; then
    run_leg browser owed env KORAX_BROWSER_REQUIRED=1 \
        uv run --project . pytest -q -m browser server/tests
  elif [ -n "$BASE_REF" ]; then
    skip_leg browser "diff against ${BASE_REF} touches no perch files (#2422)"
  else
    printf '  (browser: no --base given — running rather than assuming unowed)\n' >&2
    run_leg browser unowed env KORAX_BROWSER_REQUIRED=1 \
        uv run --project . pytest -q -m browser server/tests
  fi

  # CI parity: `--directory` is the only form that catches a server test
  # importing a client package — the repo-root invocation resolves all
  # three packages together (R130's guard answers "which tree", never
  # "which package may I import").
  run_leg ci-server owed uv run --directory server pytest -q
  run_leg ci-cli    owed uv run --directory clients/cli pytest -q
  run_leg ci-mcp    owed uv run --directory clients/mcp pytest -q

  run_lane_legs
  run_shallow_leg
  run_ledger_disposition_leg
}

# ── the ledger checks ─────────────────────────────────────────────────
# FOUR named answers over TWO files, reported beside the battery rather
# than inside it: #2478 prints these in prose next to the leg table, and
# folding them into M would change what "ten legs" has meant all loop.
#
# BOTH FILES is #2496 item 3. The allocation step at a merge is: rename
# `## R-NEXT` in docs/korax-revisions.md AND substitute the inline
# `[R-NEXT]` tags in docs/korax-protocol.md. The ledger half ran from a
# heading-anchored grep; the prose half ran from memory and stopped
# happening — 19 inline tags accrued, max numbered tag R131 against a
# ledger at R138 (#2496). The protocol line below is that missing half.
run_ledger_checks() {
  local revs="$WT/docs/korax-revisions.md"
  local proto="$WT/docs/korax-protocol.md"

  if [ -f "$revs" ]; then
    local n_next max_rev
    n_next="$(grep -cE '^##[[:space:]]+R-NEXT' "$revs" 2>/dev/null)"
    max_rev="$(grep -oE '^##[[:space:]]+R[0-9]+' "$revs" 2>/dev/null \
               | grep -oE '[0-9]+$' | sort -n | tail -n 1)"
    LEDGER_LINES+=("revisions.md  ## R-NEXT headings      ${n_next:-?}   (want 0 on a merge target)")
    LEDGER_LINES+=("revisions.md  max revision            R${max_rev:-?}")
  else
    LEDGER_LINES+=("revisions.md  NOT FOUND — neither check performed")
    LEDGER_LINES+=("revisions.md  NOT FOUND — neither check performed")
  fi

  # ECHO OF THE SUITE'S GUARD, NOT A SECOND OPINION. The first cut read
  # `docs/korax-protocol.md` alone while
  # `test_revisions_ledger.py::test_no_inline_r_next_tag_in_docs_on_the_merge_target`
  # reads `_docs_dir().rglob("*.md")` — so the script answered a NARROWER
  # question than the check it stood in for and reported clean while the
  # guard had a hit in `korax-revisions.md` (#2634). Same regex, same
  # scope, and the guard stays the verdict: this line exists so a reader
  # sees the count without parsing pytest output, never as an independent
  # ruling. A stand-in that can drift from its original is #2482's defect
  # aimed at the replacement.
  local docs="$WT/docs"
  if [ -d "$docs" ]; then
    local inline files
    files="$(find "$docs" -name '*.md' -type f 2>/dev/null | wc -l)"
    inline="$(grep -rhoE '\[[^][]*\bR-NEXT\b[^][]*\]' --include='*.md' "$docs" 2>/dev/null | grep -c .)"
    LEDGER_LINES+=("docs/**.md    inline R-NEXT-shaped tags  ${inline:-0}   (want 0 on a merge target; ${files:-0} files, combined form counted; echoes the suite guard)")
  else
    LEDGER_LINES+=("docs/**.md    NOT FOUND — check not performed")
  fi

  local markers
  markers="$(cd "$WT" && git grep -lE '^(<<<<<<<|>>>>>>>) ' -- . 2>/dev/null | grep -c .)"
  LEDGER_LINES+=("tree          conflict markers        ${markers:-0}   (files containing them)")
}

# ── the report ────────────────────────────────────────────────────────
report() {
  local ran=0 failed=0 skipped=0 unowed=0 missing=0 name
  for name in "${LEG_NAMES[@]}"; do
    case "${LEG_STATUS[$name]:-MISSING}" in
      PASS) ran=$((ran + 1)) ;;
      FAIL) ran=$((ran + 1)); failed=$((failed + 1)) ;;
      SKIP) skipped=$((skipped + 1)) ;;
      *)    missing=$((missing + 1))
            LEG_DETAIL[$name]="NOT REACHED — the battery did not get this far" ;;
    esac
    [ "${LEG_OWED[$name]:-}" = "unowed" ] && unowed=$((unowed + 1))
  done

  echo
  echo "════════════════════════════════════════════════════════════════"
  echo "korax gate — $(cd "$WT" && git rev-parse HEAD)"
  ( cd "$WT" && uv run tools/type_lane.py --stamp-only 2>/dev/null ) || true
  [ -n "$BASE_REF" ] && echo "base:     $BASE_REF"
  if [ "$MERGE_TARGET" -eq 1 ]; then
    echo "env:      KORAX_MERGE_TARGET=1 — merge-target battery (CI's condition on main)"
  else
    echo "env:      KORAX_MERGE_TARGET unset (--branch) — the two merge-target"
    echo "          ledger guards SKIP; this is NOT the battery CI runs on main"
  fi
  echo "worktree: $WT"
  echo "logs:     $LOGDIR"
  echo "════════════════════════════════════════════════════════════════"
  echo

  local state
  for name in "${LEG_NAMES[@]}"; do
    case "${LEG_STATUS[$name]:-MISSING}" in
      PASS|FAIL)
        if [ "${LEG_OWED[$name]:-owed}" = "unowed" ]; then
          state="${LEG_STATUS[$name]} (not owed)"
        else
          state="${LEG_STATUS[$name]}"
        fi ;;
      SKIP) state="SKIPPED" ;;
      *)    state="MISSING" ;;
    esac
    printf '  %-16s %-12s %s\n' "$state" "$name" "${LEG_DETAIL[$name]:-}"
  done

  echo
  local line
  for line in "${LEDGER_LINES[@]}"; do
    printf '  %s\n' "$line"
  done

  # THE DENOMINATORS. Every count names what it is out of, and they are
  # reconciled against the DECLARED total so a shrunken battery cannot
  # render as a whole one (#2485, #2482).
  echo
  echo "  legs      $ran of $LEG_COUNT ran, $skipped skipped, $missing not reached"
  echo "  fail      $failed of $ran ran"
  echo "  ledger    ${#LEDGER_LINES[@]} of 4 checks reported"
  if [ $skipped -gt 0 ]; then
    local s=""
    for name in "${LEG_NAMES[@]}"; do
      [ "${LEG_STATUS[$name]:-}" = "SKIP" ] && s="$s $name"
    done
    echo "  skipped  ${s} — a skip is not a pass"
  fi
  if [ $unowed -gt 0 ]; then
    local u=""
    for name in "${LEG_NAMES[@]}"; do
      [ "${LEG_OWED[$name]:-}" = "unowed" ] && u="$u $name"
    done
    echo "  not owed ${u} — run anyway, deliberate over-measurement"
  fi
  echo "  commands  $LEG_COUNT legs from 10 invocations (the type lane is one"
  echo "            command reporting ruff and mypy since R135/#2379)"
  echo

  if [ $failed -eq 0 ] && [ $skipped -eq 0 ] && [ $missing -eq 0 ]; then
    echo "  GATE fail=0 — $ran of $LEG_COUNT legs, none skipped, none missing"
  elif [ $failed -eq 0 ] && [ $missing -eq 0 ]; then
    echo "  GATE fail=0 — but $skipped of $LEG_COUNT legs did NOT run (named above)"
  else
    echo "  GATE FAILED — $failed of $ran ran legs red, $missing not reached"
  fi
  echo
}

#: REAP FIRST, THEN DELETE. The bounced-then-gated first cut removed the
#: worktree and `rm -rf`'d the scratch tree while an interrupted leg's
#: processes were still running — deleting a live Chrome's profile dir
#: out from under it, which is strictly worse than doing nothing
#: (#2611, disclosed at the R144 gate #2663).
#: Drop a leg's group once it has been waited. NOT tidiness — a pgid
#: whose leg has exited is a number the kernel is free to hand to
#: somebody else, and `cleanup` runs on the NORMAL exit path too. Left
#: in, this list would have teardown `kill -KILL -- -<pgid>` a group
#: that by then belongs to a stranger, on a host the charter calls
#: shared. Only groups believed to be running are ever signalled.
forget_leg() {
  local gone="$1" keep=() p
  for p in "${LEG_PGIDS[@]}"; do
    [ "$p" = "$gone" ] || keep+=("$p")
  done
  LEG_PGIDS=("${keep[@]}")
}

reap_legs() {
  local pgid
  for pgid in "${LEG_PGIDS[@]}"; do
    [ -z "$pgid" ] && continue
    [ "$pgid" = "$$" ] && continue          # never our own group
    kill -KILL -- "-$pgid" 2>/dev/null
  done
  LEG_PGIDS=()
}

cleanup() {
  reap_legs
  [ $KEEP -eq 1 ] && return 0
  if [ -n "$WT" ] && [ -d "$WT" ]; then
    git -C "$REPO_ROOT" worktree remove --force "$WT" >/dev/null 2>&1
    git -C "$REPO_ROOT" worktree prune >/dev/null 2>&1
  fi
  [ -n "$SCRATCH" ] && [ -d "$SCRATCH" ] && rm -rf "$SCRATCH"
  return 0
}

# Sourcing guard, so the acceptance suite can `source` this file and
# call the ledger-disposition primitives directly against a planted
# fixture repo — the leg's OWN LOGIC under real execution, at a cost
# far below running all ten of the other legs per fixture (#2682's
# acceptance: real invocations, not a reimplementation). Standard bash
# idiom; changes nothing about `bash tools/gate.sh ...`, where
# BASH_SOURCE[0] already equals $0.
main() {
  parse_args "$@"
  setup_worktree
  # INT and TERM as well as EXIT: an interrupted gate is the path
  # that leaked, and an EXIT-only trap does not cover a Ctrl-C that
  # kills the shell before it unwinds.
  trap cleanup EXIT INT TERM
  run_battery
  run_ledger_checks
  report

  local name
  for name in "${LEG_NAMES[@]}"; do
    case "${LEG_STATUS[$name]:-MISSING}" in
      FAIL|MISSING) return 1 ;;
    esac
  done
  return 0
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
