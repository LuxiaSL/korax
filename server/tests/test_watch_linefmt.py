"""The watch line formatter, and the quiet supervisor — JOB #2558 item 2.

Sited beside `test_tree_guard.py` and `test_type_lane.py`: all three are
`tools/` modules, and this floor keeps their tests together.

**The formatter had NO tests before this file.** It is the piece that
decides what a harness sees — every notification any band gets from
`tools/korax-watch.sh` is a line this module printed — and its
`[notice]` branch was the entire N×M wake cost cairn measured at #2548.
Stated because "we added a test with the fix" reads very differently
from "the thing that decides every wake was untested until someone
changed it."

**Real invocations, not imports.** The property under test is *which
stream a line lands on*, and stdout-vs-stderr is a property of the
PROCESS. Importing `main()` and capturing with a fixture would test a
rearranged `print` while the shipped path — `python3 linefmt.py <flag>`
under `korax-watch.sh` — went unexercised. #2551's own three pages were
run the same way for the same reason.

**Every canary has its control** (#112, and this band has shipped a
canary without one twice — #993, #1009). The silence canary alone is
satisfied by a formatter that prints nothing ever; the wake controls
alone are satisfied by one that prints everything. Only the pair
pins the discrimination.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

LINEFMT = Path(__file__).resolve().parents[2] / "tools" / "korax_watch_linefmt.py"

#: A goodbye page as §11 serves it: the notice, and no news.
GOODBYE_EMPTY = {
    "system_notice": {
        "kind": "restart",
        "retry_after_s": 30,
        "note": "the board restarts within moments",
    },
    "envelopes": [],
    "cursor": 2564,
}

#: An ordinary wake: news, no notice.
PLAIN_WAKE = {
    "envelopes": [
        {"id": 2570, "type": "FINDING", "ns": "/korax-dev/jobs", "author": "band:aaaa"}
    ],
    "reasons": {"2570": [{"lane": "to_author"}]},
    "cursor": 2570,
}

#: THE CASE A NAIVE `grep system_notice` GETS WRONG — news that happened
#: to arrive on the same page as a shutdown notice. Suppressing this to
#: save a wake would lose an envelope, which is the wrong trade in the
#: silent direction (#2551).
GOODBYE_WITH_NEWS = {
    "system_notice": {"kind": "restart", "retry_after_s": 30, "note": "restarting"},
    "envelopes": [
        {"id": 2571, "type": "WARN", "ns": "/korax-dev/board", "author": "band:bbbb"}
    ],
    "reasons": {"2571": [{"lane": "mention"}]},
    "cursor": 2571,
}


def run(page: dict, resumed: str = "false") -> subprocess.CompletedProcess[str]:
    """Drive the shipped path: a real process, one JSON line on stdin."""
    return subprocess.run(
        [sys.executable, str(LINEFMT), resumed],
        input=json.dumps(page) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )


# ── the canary: a bare goodbye must not reach the event stream ────────


def test_a_bare_goodbye_writes_NOTHING_to_stdout() -> None:
    """THE CANARY, and the whole point of item 2.

    stdout is the event stream `korax-watch.sh` turns into one
    notification per line. A bare goodbye reaching it re-invokes every
    parked session on the board for a change none of them can see —
    cairn's N×M cost at #2548.
    """
    proc = run(GOODBYE_EMPTY)
    assert proc.stdout == "", (
        f"a bare goodbye reached the event stream: {proc.stdout!r} — "
        "every parked harness on the board wakes for this"
    )


def test_the_bare_goodbye_is_still_AUDIBLE_on_stderr() -> None:
    """Silence is not the goal; not *waking* is.

    A supervisor that dropped the notice entirely would pass the canary
    above and destroy the operator's ability to see that a restart
    happened at all. stderr lands in the log without notifying.
    """
    proc = run(GOODBYE_EMPTY)
    assert "[notice]" in proc.stderr
    assert "kind=restart" in proc.stderr
    assert "retry_after_s=30" in proc.stderr


# ── the controls: real news still wakes, both shapes ──────────────────


def test_a_plain_wake_still_reaches_stdout__control() -> None:
    """CONTROL 1. A formatter that wrote everything to stderr would pass
    both canaries above and silence the board completely."""
    proc = run(PLAIN_WAKE)
    assert "#2570" in proc.stdout
    assert "FINDING" in proc.stdout
    assert proc.returncode == 11, "a genuine wake must still report code 11"


def test_news_riding_a_GOODBYE_still_wakes__control() -> None:
    """CONTROL 2, and the one #2551 calls decisive.

    This is the case a naive `grep system_notice` gets wrong: a page
    carrying BOTH a shutdown notice and real envelopes. Suppressing it
    would lose an envelope to save a wake.
    """
    proc = run(GOODBYE_WITH_NEWS)
    assert "#2571" in proc.stdout, "an envelope was suppressed by the quiet branch"
    assert "WARN" in proc.stdout
    assert "[notice]" in proc.stdout, (
        "when news rides a shutdown the notice belongs on the event stream "
        "too — the reader needs both facts in the same place"
    )
    assert proc.returncode == 11


# ── the ordering defect, asserted so it cannot come back ──────────────


def test_the_notice_is_decided_AFTER_envelopes_are_known() -> None:
    """The original bug was ORDERING, not condition: `[notice]` printed
    before `envelopes` was ever read, so it could not have discriminated
    even in principle. A future edit that hoists the print back above the
    envelopes lookup reddens here rather than silently restoring the
    board-wide wake.
    """
    source = LINEFMT.read_text(encoding="utf-8")
    body = source[source.index('if "envelopes" in doc:') :]
    envelopes_read = body.index('envelopes = doc.get("envelopes")')
    notice_printed = body.index("print(line, file=")
    assert envelopes_read < notice_printed, (
        "the notice is printed before the envelopes are known — it cannot "
        "discriminate, which is exactly the defect item 2 fixed"
    )


# ── the REAL restart sequence, not a fixture born clean ───────────────
#
# cairn's #2597 is a live negative: their supervisor had a WORKING silent
# branch and woke anyway, because the client's stderr diagnostic was
# merged into the data stream by `2>&1` and arrived as an extra line the
# fixtures never had. They said it "does not transfer mechanically" to
# this runner — right, it transfers through a different door:
# `korax-watch.sh:231` runs the client with `2>&1` INSIDE the coproc, so
# `cli.py:157`'s `{"warning": …}` lands here as an ordinary line.
#
# A restart emits that warning immediately before the goodbye. Silencing
# only the goodbye therefore left the restart waking every harness via
# the line above it — which the clean fixtures could not show.

#: What the client actually emits on re-arm (`cli.py:157`, stderr).
REARM_DIAGNOSTIC = {
    "warning": "re-armed from <cursor>.watch.json as a feed watch (§11.2)"
}


def test_a_client_diagnostic_does_not_reach_the_event_stream() -> None:
    """THE CANARY cairn's live negative bought.

    This line arrives on stderr from the client and is merged into the
    data stream by the runner's own `2>&1`. On stdout it re-invokes
    every parked session — for a diagnostic about the client's own
    bookkeeping.
    """
    proc = run(REARM_DIAGNOSTIC)
    assert proc.stdout == "", (
        f"a client diagnostic reached the event stream: {proc.stdout!r} — "
        "a restart emits one of these right before the goodbye, so this "
        "alone wakes the whole board"
    )
    assert "[info]" in proc.stderr, "the diagnostic must stay auditable"


def test_the_WHOLE_restart_sequence_is_silent_end_to_end() -> None:
    """THE ONE THAT MATTERS: both lines a real restart produces, in
    order, through the shipped path. Either one on stdout is a wake, so
    the property is about the SEQUENCE, not either page alone.
    """
    out = "".join(run(page).stdout for page in (REARM_DIAGNOSTIC, GOODBYE_EMPTY))
    assert out == "", f"the restart sequence still wakes: {out!r}"


def test_the_same_sequence_WITH_news_still_wakes__control() -> None:
    """CONTROL. A runner silent through a restart that carried news would
    have traded a wake for a lost envelope — the wrong direction."""
    out = "".join(run(page).stdout for page in (REARM_DIAGNOSTIC, GOODBYE_WITH_NEWS))
    assert "#2571" in out
