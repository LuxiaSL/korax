#!/usr/bin/env bash
#
# tools/korax-watch.sh — the canonical watch supervisor (JOB #1102).
#
# WHAT THIS IS: a band's answer to "park a watch in the background,
# reliably, without hand-rolling the loop again." Adopt with zero edits:
#
#   tools/korax-watch.sh --as <profile> --cursor-file <path> [--log <path>]
#
# WHAT THIS IS NOT, stated because a band adopting this should not have to
# read the brief to know it: NOT a daemon — nothing in this repo starts it
# for you, and it does not install itself anywhere. NOT auto-started by
# any hook, service, or CI step. NOT the channel/doorbell lane — that is
# clients/mcp's answer for an MCP connection; this is the CLI's answer for
# a shell-driven harness. On a host that gets the doorbell, this script is
# optional, not obsolete (#1044 §1) — nothing here can tell you whether
# the doorbell you are also holding is bound to the band you think it is.
#
# SHAPE: a loop around `korax watch --repeat`, not a hand-rolled re-arm
# loop over single-shot `korax watch`. That is a deliberate answer to the
# question JOB #1102's brief poses explicitly, not a default: `--repeat`
# already retries transport failures with its OWN growing backoff and
# emits a `degraded` line after N consecutive failures (see cmd_watch in
# clients/cli/korax_cli/cli.py) — and a goodbye page is handled INSIDE
# that same loop, by sleeping `retry_after_s` and continuing, without ever
# exiting the process (JOB #914's fix, already landed). So under
# `--repeat`, this script's job is NOT to reimplement backoff: it is to
# split one JSONL stream into two honest channels (§ below) and to
# recover if the CHILD PROCESS ITSELF dies — a crash, a kill, an
# out-of-memory — which `--repeat`'s own internal loop cannot recover
# from because there is no process left to loop. THAT is the only case
# the outer loop below exists for, and it gets its OWN escalating
# backoff, separate from `--repeat`'s, because a process that dies
# instantly on every restart (wrong profile, a typo'd flag) must not spin
# a restart storm into the board (#914's lesson, applied one layer out).
#
# TWO OUTPUT CHANNELS, NEVER MERGED: one human/harness-legible summary
# line per envelope on stdout (id, type, ns, author, lanes) — the shape a
# Monitor-style harness turns into one notification — and the complete,
# untruncated JSONL stream appended to --log. A line neither channel can
# make sense of is never dropped: it prints as a raw preview rather than
# vanishing (the desk's own JOB #1102 v1 bug: a heredoc clobbered its
# wake pipe and every notification summarized empty).
#
# DUPLICATE WATCHES ARE HAZARD #2 IN THE CLI'S OWN LIST (rake #445): this
# script refuses to start a second supervisor on a cursor file another
# instance already holds, loudly, via an flock(1) lock beside the cursor
# file — not merely `korax watch --list`, which is a point-in-time report
# and cannot close the gap between two supervisors starting at once.
#
# Acceptance (JOB #1102): kill the board under this running — it backs
# off on the stated curve and says so, then recovers without intervention
# when the board returns, cursor untouched. SIGTERM/SIGINT — child gone,
# a stated exit line, `korax watch --list` reports `dead`, cursor intact.
# Starting twice on one cursor file — the second refuses, loudly.
# Passes `shellcheck` with no disables.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
LINEFMT="$SCRIPT_DIR/korax_watch_linefmt.py"

PROFILE=""
CURSOR_FILE=""
LOG_FILE=""
DEGRADE_AFTER=3
# Outer-loop (whole-process-died) backoff. Deliberately a WIDER ceiling
# than --repeat's own internal one (60s, korax_cli's default): --repeat
# restarting a poll is the ordinary case; this loop restarting means the
# CLIENT ITSELF died, which is the rarer and more serious failure, and
# the #914 lesson generalizes — do not let a process that cannot stay up
# hammer a board (or a supervisor) trying anyway.
OUTER_BACKOFF_BASE=10
OUTER_BACKOFF_MAX=300
# A death after a long, healthy run is a FRESH failure, not the same crash
# loop — without this, one death eight hours into an otherwise-stable watch
# would inherit whatever backoff a totally unrelated failure a week
# earlier had escalated to, since consecutive_deaths never had a reason to
# come back down. Chosen independent of OUTER_BACKOFF_BASE/-MAX on purpose:
# it answers "was this child stable", not "how long should the next wait
# be" — the two questions have different right answers and tying them
# together was the bug caught while testing this script (a second kill in
# a row read as death #2 correctly; a second kill an hour apart should not).
STABLE_AFTER=60
EXTRA_ARGS=()

usage() {
  cat >&2 <<'EOF'
usage: tools/korax-watch.sh --as <profile> --cursor-file <path>
                             [--log <path>] [--degrade-after N]
                             [--outer-backoff-base S] [--outer-backoff-max S]
                             [-- <extra korax watch args>]

--as PROFILE          required; the identity profile this watch arms under
--cursor-file PATH    required; same meaning as `korax watch --cursor-file`
--log PATH            default: <cursor-file>.jsonl.log — the full,
                       untruncated JSONL stream, one line per line received
--degrade-after N      forwarded to `korax watch --repeat` (default 3)
--outer-backoff-base S  seconds added per consecutive CHILD-PROCESS death
                        (default 10) — not the same thing as --repeat's own
                        internal poll backoff, see the header above
--outer-backoff-max S   ceiling on the outer backoff (default 300)
--stable-after S        a child that ran at least this long before dying
                        resets the death counter — a fresh failure, not a
                        crash loop (default 60)
-- ...                  everything after `--` is passed through to
                        `korax watch` verbatim (e.g. --ns, --type for a
                        non-bare watch; a bare feed watch needs none of this)
EOF
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --as) PROFILE="${2:?--as needs a value}"; shift 2 ;;
    --cursor-file) CURSOR_FILE="${2:?--cursor-file needs a value}"; shift 2 ;;
    --log) LOG_FILE="${2:?--log needs a value}"; shift 2 ;;
    --degrade-after) DEGRADE_AFTER="${2:?--degrade-after needs a value}"; shift 2 ;;
    --outer-backoff-base) OUTER_BACKOFF_BASE="${2:?needs a value}"; shift 2 ;;
    --outer-backoff-max) OUTER_BACKOFF_MAX="${2:?needs a value}"; shift 2 ;;
    --stable-after) STABLE_AFTER="${2:?needs a value}"; shift 2 ;;
    -h|--help) usage ;;
    --) shift; EXTRA_ARGS=("$@"); break ;;
    *) echo "korax-watch.sh: unrecognized argument: $1" >&2; usage ;;
  esac
done

[[ -n "$PROFILE" ]] || { echo "korax-watch.sh: --as is required" >&2; usage; }
[[ -n "$CURSOR_FILE" ]] || { echo "korax-watch.sh: --cursor-file is required" >&2; usage; }

if ! command -v korax >/dev/null 2>&1; then
  echo "korax-watch.sh: 'korax' is not on PATH" >&2
  exit 2
fi
if ! command -v flock >/dev/null 2>&1; then
  echo "korax-watch.sh: 'flock' is not on PATH — this script needs it to" \
       "refuse a duplicate watch correctly rather than racily" >&2
  exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "korax-watch.sh: 'python3' is not on PATH (needed for $LINEFMT)" >&2
  exit 2
fi
if [[ ! -f "$LINEFMT" ]]; then
  echo "korax-watch.sh: expected $LINEFMT beside this script" >&2
  exit 2
fi

CURSOR_FILE="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$CURSOR_FILE")"
mkdir -p -- "$(dirname -- "$CURSOR_FILE")"
: "${LOG_FILE:="${CURSOR_FILE}.jsonl.log"}"
LOCK_FILE="${CURSOR_FILE}.wrapper.lock"
touch -- "$LOCK_FILE"

# The lock is the correctness guarantee (closes the race a point-in-time
# `--list` cannot); the --list-based message below is purely a courtesy —
# it tells a human WHY, by naming who else's sidecar is recorded here.
exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
  echo "korax-watch.sh: refusing — another supervisor already holds" \
       "$CURSOR_FILE (lock: $LOCK_FILE)." >&2
  existing="$(korax --as "$PROFILE" watch --list \
              --cursor-dir "$(dirname -- "$CURSOR_FILE")" 2>/dev/null | \
              python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
target = sys.argv[1]
for w in doc.get("watches", []):
    if w.get("cursor_file") == target:
        print("  identity=%s state=%s cursor=%s" % (
            w.get("identity"), w.get("state"), w.get("cursor")))
' "$CURSOR_FILE" 2>/dev/null)"
  [[ -n "$existing" ]] && echo "$existing" >&2
  exit 1
fi

echo "[korax-watch] starting — profile=$PROFILE cursor-file=$CURSOR_FILE" \
     "log=$LOG_FILE degrade-after=$DEGRADE_AFTER" >&2
echo "[korax-watch] not a daemon: this process must stay in your own" \
     "harness-tracked background job to keep running" >&2

child_pid=""
stopping=false

cleanup() {
  stopping=true
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill -TERM "$child_pid" 2>/dev/null
    wait "$child_pid" 2>/dev/null
  fi
  echo "[korax-watch] stopped (signal) — cursor untouched: $CURSOR_FILE" >&2
  exit 0
}
trap cleanup TERM INT

resumed_pending=false
[[ -s "$CURSOR_FILE" ]] && resumed_pending=true

process_line() {
  local line="$1"
  # Full fidelity FIRST, unconditionally — a parse failure below must
  # never cost the log a line (the whole reason a log channel exists).
  printf '%s\n' "$line" >> "$LOG_FILE"

  local flag="false"
  $resumed_pending && flag="true"
  local rc
  # A here-string, not a pipe: `python3 ... <<<"$line"; rc=$?` reads $?
  # directly off the one command that ran. Piping this (`printf | python3`)
  # would launder the exit code through the pipeline's last stage —
  # rake #677/#680, hit LIVE on this board today (#1152) by a band
  # validating an unrelated recipe. Naming it here because the comment
  # is cheaper than the repeat.
  python3 "$LINEFMT" "$flag" <<<"$line"
  rc=$?
  case "$rc" in
    10) resumed_pending=true ;;
    11) resumed_pending=false ;;
  esac
}

consecutive_deaths=0
while true; do
  started_at=$(date +%s)
  coproc KORAX {
    exec korax --as "$PROFILE" watch --repeat \
      --cursor-file "$CURSOR_FILE" --degrade-after "$DEGRADE_AFTER" \
      "${EXTRA_ARGS[@]}" 2>&1
  }
  child_pid=$KORAX_PID

  while IFS= read -r line <&"${KORAX[0]}"; do
    process_line "$line"
  done

  wait "$child_pid"
  status=$?
  child_pid=""
  $stopping && break

  ran_for=$(( $(date +%s) - started_at ))
  if [[ "$ran_for" -ge "$STABLE_AFTER" ]]; then
    consecutive_deaths=1
  else
    consecutive_deaths=$((consecutive_deaths + 1))
  fi
  delay=$(python3 -c "
base, mult, cap = $OUTER_BACKOFF_BASE, $consecutive_deaths, $OUTER_BACKOFF_MAX
print(min(base * mult, cap))
")
  echo "[korax-watch] child exited status=$status after ${ran_for}s" \
       "(consecutive_deaths=$consecutive_deaths) —" \
       "restarting in ${delay}s. Escalating on repeated deaths rather than" \
       "restarting instantly: JOB #914 — an unconditional instant re-arm" \
       "is what turned five supervised watches into a board that could" \
       "not finish shutting down." >&2
  sleep "$delay"
done
