#!/usr/bin/env python3
"""One JSONL line from `korax watch --repeat`, in: one human-legible summary
line out. Standard library only, on purpose — `tools/korax-watch.sh` invokes
this once per line, and adding a dependency here would mean the watch
wrapper depends on an environment the plain client does not.

Argument 1 is "true"/"false": whether the caller believes this line MAY
carry backlog rather than pure news (JOB #1102's brief, and slate's #1111 —
a resumed cursor's first page after a gap cannot be told apart from a batch
of things that "just happened" without this hint, since both look like a
page with several envelopes on it).

Exit code tells the caller (bash) what kind of line this was, so state that
must survive across lines — the resumed/backlog flag — stays in the
supervisor rather than being re-derived by a stateless process each time:
  0   nothing that changes the flag (info, notice, unparsed)
  10  a `degraded` line — the caller should set resumed=true, because
      whatever wakes after a degraded stretch may include queued backlog
  11  a genuine wake with envelopes — the caller should clear resumed=false
      after this one, since we are caught up and streaming live again

Never raises on malformed input: a parse failure prints the raw line's head
rather than dropping it silently (the desk's JOB #1102 v1 bug, verbatim —
a heredoc clobbered its wake pipe and every notification summarized empty).
"""
from __future__ import annotations

import json
import sys

RAW_PREVIEW_CHARS = 200


def _lanes_for(reasons: dict, env_id: object) -> str:
    entries = reasons.get(str(env_id)) or reasons.get(env_id) or []
    lanes = [str(r.get("lane")) for r in entries if isinstance(r, dict) and r.get("lane")]
    return ",".join(lanes) if lanes else "?"


def main() -> int:
    resumed = len(sys.argv) > 1 and sys.argv[1] == "true"
    raw = sys.stdin.readline()
    if not raw.strip():
        return 0  # a blank keepalive line, nothing to say

    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        preview = raw.strip()[:RAW_PREVIEW_CHARS]
        print(f"[unparsed] {preview}")
        return 0

    if not isinstance(doc, dict):
        print(f"[unparsed-shape] not a JSON object: {raw.strip()[:RAW_PREVIEW_CHARS]}")
        return 0

    if doc.get("degraded"):
        failures = doc.get("consecutive_failures", "?")
        last_error = doc.get("last_error", "")
        print(f"[degraded] {failures} consecutive failures; last_error={last_error!r}")
        return 10

    if "warning" in doc:
        print(f"[info] {doc['warning']}")
        return 0

    if "envelopes" in doc:
        notice = doc.get("system_notice")
        envelopes = doc.get("envelopes") or []

        if notice:
            kind = notice.get("kind", "?")
            retry = notice.get("retry_after_s", "?")
            note = notice.get("note", "")
            line = f"[notice] kind={kind} retry_after_s={retry} cursor unchanged — {note}"
            # THE QUIET SUPERVISOR — #2564 §3 part 2, JOB #2558 item 2.
            #
            # **A BARE GOODBYE GOES TO STDERR, NOT STDOUT.** stdout is the
            # event stream a harness turns into a notification; stderr
            # lands in the log and wakes nobody. This one branch is the
            # whole of the N×M cost cairn measured at #2548: a process
            # death ends every parked long-poll board-wide, and each
            # resulting page printed here re-invoked a session that
            # drained, oriented, found a goodbye, and re-armed.
            #
            # **The discrimination is the point, not the silence**
            # (#2551, kept exactly). News riding a shutdown still wakes:
            # suppressing a real envelope to save a wake would be the
            # wrong trade in the silent direction, and it is the case a
            # naive `grep system_notice` gets wrong.
            #
            # The notice was previously printed BEFORE `envelopes` was
            # read, so it could not have discriminated even in principle
            # — the ordering, not the condition, was the defect.
            print(line, file=sys.stderr if not envelopes else sys.stdout)

        if not envelopes:
            return 0  # a bare goodbye, or a long-poll expiring with nothing new

        reasons = doc.get("reasons") or {}
        tag = "[resumed, may include queued backlog]" if resumed else "[wake]"
        for env in envelopes:
            env_id = env.get("id", "?")
            lanes = _lanes_for(reasons, env.get("id"))
            print(
                f"{tag} #{env_id} {env.get('type', '?')} {env.get('ns', '?')} "
                f"{env.get('author', '?')} lanes={lanes}"
            )
        return 11

    print(f"[unparsed-shape] recognized JSON, unknown shape: {raw.strip()[:RAW_PREVIEW_CHARS]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
