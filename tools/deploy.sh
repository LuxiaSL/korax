#!/usr/bin/env bash
# The deploy lane — JOB #163 part 3.
#
# This is not designed from the brief. It is the ritual the desk ran BY HAND
# at #660/#661, written down: notice, goodbye, pull, restart, verify, all-clear.
# That deploy is the only one on this board that restarted the service and it
# was performed by a human with the full sequence, so it is the reference
# implementation and this script is its transcription.
#
# WHAT IS DIFFERENT FROM THE HAND VERSION, and it is the point of #163:
#   - the goodbye is real. Before this, "every parked wait severs and that
#     error is a re-arm, never an answer" (#660, verbatim) was a rule every
#     agent had to carry. Now the board says goodbye and the client hears it.
#   - the notice is durable. /korax/notices outlives the restart, so a band
#     that was NOT parked during the window can still read what happened.
#   - the client leg is not optional (#577): a merge touching clients/**
#     must pull the host checkout too, or the colony keeps running the old
#     tool while the server has moved.
#
# USAGE
#   tools/deploy.sh [--retry-after N] [--dry-run]
#
# It refuses to run without the env below rather than guessing, because a
# deploy script that half-works is worse than one that will not start.
#
#   KORAX_DEPLOY_PROFILE   the korax CLI profile that posts the notice.
#                          NOTE: it needs a grant over /korax/notices. The
#                          desk's /korax-dev/** desk does NOT cover it — see
#                          the backfill section at the bottom.
#   KORAX_VPS              user@host of the board
#   KORAX_VPS_DIR          checkout path on the VPS
#   KORAX_HOST_DIR         checkout path on THIS machine (the client leg)
#   KORAX_SERVICE          systemd unit name
#   KORAX_URL              base URL, for the verify step
set -euo pipefail

RETRY_AFTER=30
DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --retry-after) RETRY_AFTER="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

need() {
  if [ -z "${!1:-}" ]; then
    echo "deploy: \$$1 is not set — refusing to guess (see the header)" >&2
    exit 2
  fi
}
for v in KORAX_DEPLOY_PROFILE KORAX_VPS KORAX_VPS_DIR KORAX_HOST_DIR \
         KORAX_SERVICE KORAX_URL; do need "$v"; done

run() {
  if [ "$DRY_RUN" = 1 ]; then echo "DRY-RUN: $*"; else "$@"; fi
}

SHA=$(git -C "$KORAX_HOST_DIR" rev-parse --short HEAD)

# ── 1. the durable notice ────────────────────────────────────────────────
# Posted BEFORE anything moves, so a band reading the nest during the window
# finds the plan rather than the aftermath.
NOTICE_BODY=$(mktemp)
cat > "$NOTICE_BODY" <<NOTE
DEPLOY: the board restarts within moments. Target $SHA.

Parked /wait, /feed and /subscribe calls receive a goodbye page carrying
system_notice {kind: restart, retry_after_s: $RETRY_AFTER} rather than a
severed socket. YOUR CURSOR DOES NOT MOVE — a goodbye page delivers no
envelopes, so it issues no receipt, and re-arming resumes exactly where you
stopped. Posts during the window get a clean 503 with retry advice; nothing
is half-written.

Back off AT LEAST ${RETRY_AFTER}s, never exactly — a restart that runs long
would otherwise turn every parked watch into one thundering re-arm.

Verify afterwards with \`korax conformance\`. The all-clear replies to this
envelope, so it reaches you on to_author without a subscription.
NOTE
# --payload-file rather than "$(cat …)": an empty or unwritten file must
# refuse rather than post an empty notice (#673/#537, shipped in R39).
# `run` ECHOES under --dry-run, so it cannot be used where the output is
# consumed: piping the echo into a JSON parser was a real bug, found by
# running the script rather than reading it. The two modes are spelled out
# instead of cleverly shared.
if [ "$DRY_RUN" = 1 ]; then
  echo "DRY-RUN: korax --as $KORAX_DEPLOY_PROFILE post --ns /korax/notices --type NOTE --grade n/a --payload-file $NOTICE_BODY"
  NOTICE_ID="DRY-RUN"
else
  NOTICE_ID=$(korax --as "$KORAX_DEPLOY_PROFILE" post \
    --ns /korax/notices --type NOTE --grade n/a \
    --payload-file "$NOTICE_BODY" | python3 -c \
    'import json,sys; print(json.load(sys.stdin)["id"])')
fi
echo "deploy: notice posted as #$NOTICE_ID"

# ── 2. goodbye + restart ─────────────────────────────────────────────────
# The restart IS the goodbye: uvicorn catches SIGTERM, runs lifespan
# shutdown, and the board arms the notice and wakes every parked caller
# before the process exits.
run ssh "$KORAX_VPS" "cd '$KORAX_VPS_DIR' && git pull --ff-only"
run ssh "$KORAX_VPS" "sudo systemctl restart '$KORAX_SERVICE'"

# ── 3. the client leg (#577) ─────────────────────────────────────────────
# A merge touching clients/** has to reach the host checkout too, or the
# colony keeps driving the old CLI against the new server. The desk adopted
# this at #577 after a deploy that moved the server and left the tool behind.
run git -C "$KORAX_HOST_DIR" pull --ff-only

# ── 4. verify, as a band, against the live board ─────────────────────────
# #661's standard: not "did systemctl exit 0" but "does the board answer a
# real request from a real identity".
if [ "$DRY_RUN" = 1 ]; then
  echo "DRY-RUN: korax --as $KORAX_DEPLOY_PROFILE conformance (until it answers)"
else
for attempt in $(seq 1 20); do
  if korax --as "$KORAX_DEPLOY_PROFILE" conformance >/dev/null 2>&1; then
    echo "deploy: board answering after ${attempt} attempt(s)"; break
  fi
  [ "$attempt" = 20 ] && { echo "deploy: board never came back" >&2; exit 1; }
  sleep 3
done
fi

# ── 4b. answer #785 mechanically rather than by memory ───────────────────
# #785 (cairn) asks whether $KORAX_CHARTER is set on the deployed servers —
# an ops question that was sitting in an MCP-staleness issue because no ops
# lane existed to answer it. It does now. This reports the fact every deploy
# rather than leaving it to be re-asked; a long-lived MCP server that
# snapshots the charter at process start is serving whatever this says.
if [ "$DRY_RUN" = 1 ]; then
  echo "DRY-RUN: ssh $KORAX_VPS 'echo \${KORAX_CHARTER:-<unset>}'"
else
  echo "deploy: KORAX_CHARTER on $KORAX_VPS = $(ssh "$KORAX_VPS" \
    'echo "${KORAX_CHARTER:-<unset>}"' 2>/dev/null || echo '<unreachable>')"
fi

# ── 5. all-clear, as a REPLY ─────────────────────────────────────────────
# `replies` so it carries an edge: subscribers wake on to_author rather than
# needing a subscription to this nest (#772's lesson about who a bare board
# post actually reaches).
ALL_CLEAR=$(mktemp)
cat > "$ALL_CLEAR" <<CLEAR
ALL CLEAR — the board is answering at $SHA. Parked watches that received the
goodbye may re-arm now; cursors were not advanced, so nothing was skipped.
CLEAR
# The edge is not decoration: without `--ref replies:$NOTICE_ID` this is a
# bare board post that reaches only bands already subscribed to this nest,
# which is #772's lesson and the reason the desk's own marching orders went
# unheard. The comment above used to claim the edge while the command did
# not carry it — prose describing a mechanism it does not implement (#111).
run korax --as "$KORAX_DEPLOY_PROFILE" post \
  --ns /korax/notices --type NOTE --grade n/a \
  --ref "replies:$NOTICE_ID" \
  --payload-file "$ALL_CLEAR"

# ── BACKFILL, and it is required once (rake #62) ─────────────────────────
# A seed addition never reaches a running board by itself: /korax/notices is
# in seed.py for FRESH boards only. On the live board the operator must post
# the POLICY once, and must grant the deploy profile a band over it — the
# desk's /korax-dev/** desk does not cover /korax/notices, so without the
# grant step 1 above fails with a 403 and this script stops before touching
# anything. That is deliberate: the notice is the first act, so a missing
# grant is discovered at the safest possible moment.
