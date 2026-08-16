#!/usr/bin/env bash
# The conditional-restart predicate, standalone (#2553 §3, JOB #2558 item 1).
#
# Separated from deploy.sh so it is testable against a local git fixture
# without SSH or a live board — server/tests/test_deploy_predicate.py
# exercises it directly.
#
# USAGE
#   deploy_predicate.sh <repo_dir> <deployed_sha> <target_sha>
#
# Prints exactly one line to stdout, always starting with the decision
# word, self-describing with a denominator per #2485:
#   restart <N> file(s) under server/korax/**.py: <names>
#   restart indeterminate: <reason>
#   no-restart matched 0 files under server/korax/**.py between <a> and <b>
#
# Exit code is always 0 — the decision is the OUTPUT, not the exit status,
# so a caller captures it with $(...) rather than branching on $?. This
# script never mutates anything; it only reads with `git diff`/`cat-file`.
#
# FAILS CLOSED (#2547): a missing argument, an unresolvable sha, or a git
# error all print `restart indeterminate: ...` — a stale process serving
# new expectations is worse than an unnecessary ~1.6s restart.
set -uo pipefail  # deliberately no -e: every branch below must still print

REPO_DIR="${1:-}"
DEPLOYED_SHA="${2:-}"
TARGET_SHA="${3:-}"

if [ -z "$REPO_DIR" ] || [ -z "$DEPLOYED_SHA" ] || [ -z "$TARGET_SHA" ]; then
  echo "restart indeterminate: missing argument(s) (repo_dir=${REPO_DIR:-<empty>} deployed_sha=${DEPLOYED_SHA:-<empty>} target_sha=${TARGET_SHA:-<empty>})"
  exit 0
fi

if [ ! -d "$REPO_DIR" ]; then
  echo "restart indeterminate: repo_dir $REPO_DIR does not exist"
  exit 0
fi

if ! git -C "$REPO_DIR" cat-file -e "${DEPLOYED_SHA}^{commit}" 2>/dev/null; then
  echo "restart indeterminate: deployed sha $DEPLOYED_SHA is not a resolvable commit in $REPO_DIR"
  exit 0
fi

if ! git -C "$REPO_DIR" cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null; then
  echo "restart indeterminate: target sha $TARGET_SHA is not a resolvable commit in $REPO_DIR"
  exit 0
fi

CHANGED=$(git -C "$REPO_DIR" diff --name-only "$DEPLOYED_SHA" "$TARGET_SHA" -- 'server/korax/**.py' 2>/dev/null)
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
  echo "restart indeterminate: git diff failed (exit $STATUS) between $DEPLOYED_SHA and $TARGET_SHA"
  exit 0
fi

if [ -n "$CHANGED" ]; then
  N=$(printf '%s\n' "$CHANGED" | grep -c .)
  NAMES=$(printf '%s' "$CHANGED" | tr '\n' ' ')
  echo "restart $N file(s) under server/korax/**.py: $NAMES"
else
  echo "no-restart matched 0 files under server/korax/**.py between $DEPLOYED_SHA and $TARGET_SHA"
fi
