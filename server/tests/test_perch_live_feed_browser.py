"""The live feed's two claims, in a real browser (JOB #1659).

`test_perch_live_feed.py` executes the RULES behind DOM stubs — jitter,
backoff, the cursor hold. This file executes the FEATURE, because both of the
job's actual claims are about ORDERING that no stub reproduces:

1. **an envelope from another band renders without a reload**, and
2. **a restart shows "restarting" BEFORE "reconnecting", AND HOLDS IT LONG
   ENOUGH TO READ** — the property that won long-poll the design (#1639 §2),
   true only if the goodbye page wins its race with the dying socket. A unit
   test can assert that the client branches on `system_notice`; only a real
   shutdown shows that the branch is reachable.

**CLAIM 2 CHANGED MEANING IN JOB #2966 (#2337: say so in the delivery and in
the file).** It asserted PRESENCE of "restarting" in a 300 ms SAMPLE. Both
halves were wrong:

* the sampler could not see a state shorter than its interval — measured miss
  rate `1 - dwell/300ms`, so a displayed 60 ms state was missed 80% of the
  time — while its failure text claimed "the goodbye page lost its race with
  the dying socket", a cause no sampler can observe. In the one instance
  measured end to end that sentence was false twice: the goodbye arrived as a
  200 carrying `system_notice`, and it rendered (#2930 §2).
* presence was standing in for the property. A 6 ms flash satisfies presence
  and tells no operator anything, so "record the transitions and keep
  asserting presence" would have turned a real user-visible failure GREEN —
  refused on argument (#2910 §2, #2912 §2) and then on this run's data.

Transitions are now RECORDED with a MutationObserver, which cannot miss one,
and the assertion is on DWELL. `test_report_18_adjudicates_the_three_candidate_designs`
below runs all three candidate designs against that real recording, so the
refusal is observable rather than cited. **A branch whose browser leg passed
before this landed may fail after it; that is the flag day, not a defect in
either (#2337).**

Marked `browser` and so excluded from the default run (R94's convention), which
means **the mill's gate leg is what enforces it** — same standing as
`test_perch_smoke.py`, whose subprocess-server pattern this follows.

The seeded corpus is its own, deliberately: coupling this to another
delivery's seeder would make two unrelated jobs need to land in a gate order
(#1615's reasoning, adopted).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "server"
DRIVER = Path(__file__).with_name("perch_live_feed_driver.js")

CHROME = (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
          or shutil.which("chromium") or shutil.which("chromium-browser"))
NODE = shutil.which("node")

_SKIP_REASON = (
    "no headless Chrome found" if not CHROME else "no `node` found" if not NODE else None
)

#: How long `restarting` must remain displayed for this test to call the
#: feature working. JOB #2966 set the bracket at 1-10 s and left the number to
#: the builder with a rationale; this is the rationale.
#:
#: WHAT THE TWO POPULATIONS ARE. A correctly behaving tab holds `restarting`
#: for `jittered(noticeDelay(retry_after_s))`, and `jittered(d) = d + rnd()*d*0.5`
#: (`plumbing.js:172`), so the legitimate dwell is `[retry, 1.5*retry]`. This
#: test's board takes the server default `DEFAULT_RETRY_AFTER_S = 30`
#: (`board.py:30`), giving an analytic `[30 s, 45 s]` — and 62 instrumented
#: runs measured min 30.05 s, median 33.7 s, max 42.29 s, which is that
#: interval and not an approximation of it. The failure population is a single
#: measured point at **6 ms** (#2930 §2). Nothing was ever observed between.
#:
#: SO WHY 2 s RATHER THAN ANYWHERE ELSE IN A BRACKET THAT ALL WORKS. Any value
#: in 1-10 s separates those populations with three orders of magnitude of
#: margin on both sides, so separation cannot choose the number. What can is
#: the failure mode of choosing wrong: **too high fails a correct board.** The
#: client honours whatever `retry_after_s` the board advertises, so a board
#: doing a fast restart and honestly saying `retry_after_s: 3` produces a
#: legitimate dwell of `[3 s, 4.5 s]` — and a 5 s or 10 s floor would call that
#: correct behaviour a defect. Too low merely narrows the margin against a
#: defect that measured 6 ms. **The costs are asymmetric, so the floor sits at
#: the low end**: 2 s is 333x the observed defect and still tolerates any board
#: advertising 2 s or more.
#:
#: AND WHY THIS IS AN ABSOLUTE FLOOR RATHER THAN `dwell ~= noticeDelay(retry)`.
#: The relative form is tempting and is a trap: it would recompute the client's
#: own formula inside the test, so a bug in `noticeDelay` would be reproduced by
#: the assertion and the test would agree with the code it is checking. An
#: absolute floor is independent of the client's arithmetic, which is the only
#: reason it can catch the client being wrong.
DWELL_FLOOR_MS = 2000

#: Filled in by the test and read by `conftest.pytest_terminal_summary`, which
#: is the only channel that survives `-q` — the invocation CI and this floor
#: actually run (`tools/tree_guard.py:194` documents the two hooks that do not).
INSTRUMENT: dict[str, object] = {}


# ── interpreting a recording ────────────────────────────────────────────────
# These live in Python, not in the driver, deliberately. The driver's job is
# to RECORD; every judgement about what a recording means is made here, where
# it can be executed against a stored recording without a browser. That is
# what makes the adjudication below possible at all.

def _sequence(transitions: list[dict]) -> list[str]:
    """Run-length-deduped states, in order of first appearance."""
    out: list[str] = []
    for row in transitions:
        state = row.get("state")
        if state and (not out or out[-1] != state):
            out.append(state)
    return out


def _dwell_ms(transitions: list[dict], state: str = "restarting") -> int | None:
    """How long `state` remained displayed, or None if never displayed."""
    first = next((r for r in transitions if r.get("state") == state), None)
    if first is None:
        return None
    after = next(
        (r for r in transitions if r["t"] > first["t"] and r.get("state") != state),
        None,
    )
    if after is not None:
        return after["t"] - first["t"]
    return transitions[-1]["t"] - first["t"]


def _sampled_sequence(
    transitions: list[dict], *, interval_ms: int, start_ms: int, cap: int
) -> list[str]:
    """What a POLLING observer would have recorded from the same reality.

    This is the retired design, simulated: sleep, read `dataset.state`, keep
    it if it differs from the last kept value. It exists so the delivery can
    demonstrate the old instrument's blindness against a real recording
    rather than assert it.
    """
    out: list[str] = []
    for i in range(cap):
        now = start_ms + interval_ms * (i + 1)
        visible = None
        for row in transitions:
            if row["t"] <= now:
                visible = row.get("state")
            else:
                break
        if visible and (not out or out[-1] != visible):
            out.append(visible)
        if "restarting" in out and "reconnecting" in out:
            break
    return out


#: report-18 (#2930 §2), the only end-to-end observation of this defect: the
#: goodbye ARRIVED and rendered at t=4774, and the other of two concurrent
#: poll loops (#2909) overwrote it at t=4780. Six milliseconds. SIGTERM was
#: at t=4764. Transcribed from the probe report's MutationObserver rows.
REPORT_18_SIGTERM_MS = 4764
REPORT_18_TRANSITIONS: list[dict] = [
    {"t": 1515, "state": "paused", "text": "paused"},
    {"t": 1519, "state": "live", "text": "live — starting"},
    {"t": 2750, "state": "live", "text": "live — 1 new"},
    {"t": 3251, "state": "paused", "text": "paused — not polling"},
    {"t": 3557, "state": "live", "text": "live — starting"},
    {"t": 4774, "state": "restarting", "text": "restarting — restart, back in ~39s"},
    {"t": 4780, "state": "reconnecting", "text": "reconnecting — attempt 1, retrying in ~5s"},
    {"t": 10103, "state": "reconnecting", "text": "reconnecting — attempt 2, retrying in ~13s"},
    {"t": 23282, "state": "reconnecting", "text": "reconnecting — attempt 3, retrying in ~17s"},
    {"t": 39878, "state": "reconnecting", "text": "reconnecting — attempt 4, retrying in ~26s"},
    {"t": 43333, "state": "reconnecting", "text": "reconnecting — attempt 5, retrying in ~26s"},
    {"t": 65850, "state": "reconnecting", "text": "reconnecting — attempt 6, retrying in ~43s"},
    {"t": 68891, "state": "reconnecting", "text": "reconnecting — attempt 7, retrying in ~49s"},
]


def test_report_18_adjudicates_the_three_candidate_designs() -> None:
    """The refusal in JOB #2966 property 3, made observable rather than cited.

    Three designs were on the table for this test. They are not distinguished
    by argument — they are distinguished by what they do to ONE real run, and
    this is that run, executed against all three.

    Not marked `browser`: it needs no Chrome, because the recording is stored.
    That is the point — an adjudicating fixture nobody can run is a citation.
    """
    # THE FIXTURE'S OWN CONTROL. Before using the simulated sampler to condemn
    # the old design, check that it reproduces what the old design ACTUALLY
    # recorded on this run: `['reconnecting']`, exactly as CI reported and as
    # the probe's byte-identical copy of the shipped loop captured. A
    # simulation that cannot reproduce the observed result is not evidence
    # about the thing it simulates.
    sampled = _sampled_sequence(
        REPORT_18_TRANSITIONS, interval_ms=300, start_ms=REPORT_18_SIGTERM_MS, cap=260
    )
    assert sampled == ["reconnecting"], sampled

    recorded = _sequence(REPORT_18_TRANSITIONS)
    dwell = _dwell_ms(REPORT_18_TRANSITIONS)

    # DESIGN A — shipped: sample, then assert PRESENCE.
    # Verdict: FAILS. Correct outcome, and its message said the goodbye "lost
    # its race with the dying socket" — false twice over, since the goodbye
    # arrived as a 200 carrying system_notice and rendered.
    assert "restarting" not in sampled

    # DESIGN B — record, then assert PRESENCE. REFUSED (#2910 §2, #2912 §2).
    # Verdict: PASSES. This is the refusal made observable: a 6 ms flash no
    # operator can read is scored as the feature working. Removing the
    # sampler without changing the assertion converts a real, user-visible
    # failure into a green — which is why "just record it" was not the fix.
    assert "restarting" in recorded

    # DESIGN C — record, then assert DWELL. Delivered.
    # Verdict: FAILS, for the reason that is true.
    assert dwell == 6
    assert dwell < DWELL_FLOOR_MS

    # And the ordering property survives in C: the restart DID read as a
    # restart first. C fails this run on readability alone, which is the
    # honest complaint about it.
    assert recorded.index("restarting") < recorded.index("reconnecting")



# The child binds its own port and hands it back through the info file — no
# window in which a chosen port could be taken on a shared host (R83's shape).
# It also hands back a SECOND band's token: the viewer's own writes are dropped
# from their own feed by R19c, so a smoke test that posts as the viewer
# measures nothing and looks like a broken feature (#1643 §2).
_SEED_AND_SERVE = """
import socket, sys
sys.path.insert(0, sys.argv[1])
import uvicorn
from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

store = Store(":memory:")
operator, op_tok = store.create_identity("operator")
store.set_meta("genesis_identity", operator)
board = Board(store)
seed_board(board, operator)

poster, poster_tok = store.create_identity("live-feed-poster")

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
with open(sys.argv[2], "w") as fh:
    fh.write("\\n".join([operator, op_tok, poster, poster_tok,
                         str(port), str(board.head)]))

uvicorn.Server(uvicorn.Config(create_app(board), log_level="error")).run(
    sockets=[sock])
"""


@pytest.mark.browser
@pytest.mark.skipif(bool(_SKIP_REASON), reason=str(_SKIP_REASON))
def test_the_feed_goes_live_and_survives_a_restart(tmp_path, perch_rig) -> None:
    script = tmp_path / "serve.py"
    script.write_text(_SEED_AND_SERVE, encoding="utf-8")
    info = tmp_path / "info.txt"
    server = perch_rig.serve(script, SERVER_DIR, info)
    for _ in range(80):
        if info.exists():
            break
        time.sleep(0.25)
    else:
        pytest.skip("server did not start; not a statement about the feature")
    time.sleep(1.0)
    operator, op_tok, poster, poster_tok, port, head = info.read_text().splitlines()
    origin = f"http://127.0.0.1:{port}"

    chrome, cdp_port = perch_rig.chrome(
        CHROME, tmp_path / "chrome-profile")
    import urllib.request

    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        pytest.fail("headless Chrome did not answer its CDP port")

    driver = subprocess.run(
        [NODE, str(DRIVER), str(cdp_port), origin, op_tok, poster_tok,
         poster, operator, head, str(server.pid)],
        capture_output=True, text=True, timeout=240,
    )

    assert driver.stdout.strip(), f"driver produced no report — stderr:\n{driver.stderr}"
    report = json.loads(driver.stdout.strip().splitlines()[-1])
    assert "fatal" not in report, f"driver failed: {report.get('fatal')}"

    # PROPERTY 4 — the instrument states its own parameters, recorded before
    # any assertion can abort the test.
    #
    # BOTH cpu numbers, because they differ exactly in the case this test's
    # own defect turned on: `os.cpu_count()` reports the machine, and
    # `sched_getaffinity` reports what this process may actually use. Under
    # `taskset -c 0,1` on a 16-core host they read 16 and 2, and it was the
    # 2 that mattered — the flake fired 1/24 pinned and 0/44 unpinned
    # (#3006 §1). A run that logs only the machine's core count records the
    # number that was not the variable.
    # `sched_getaffinity` is Linux-only. Guarded rather than assumed: an
    # AttributeError here would fail this test on a mac for a reason with
    # nothing to do with the feature, and an instrument that crashes the
    # thing it observes is worse than one that reports less.
    affinity = getattr(os, "sched_getaffinity", None)
    INSTRUMENT.update({
        "cpus_total": os.cpu_count(),
        "cpus_available": len(affinity(0)) if affinity else "unavailable (not Linux)",
        "dwell_floor_ms": DWELL_FLOOR_MS,
        "observation": report.get("observation"),
        "restarting_dwell_ms": _dwell_ms(report["transitions"]),
        "dwell_is_lower_bound": report.get("restartingDwellIsLowerBound"),
    })

    assert report["indicatorPresent"], "the shell serves no #feedLive indicator"
    assert report["initialState"] == "paused", (
        "the tab polls before anyone asked it to — round one is opt-in per click"
    )
    assert report["liveState"] == "live"
    assert report["postStatus"] == 200

    # CLAIM 1 — and the assertion is that it ARRIVED, never that nothing threw.
    assert report["arrivedWithoutReload"], (
        "an envelope mentioning the viewer never rendered while the tab was "
        "live: either the loop is not waking or the lane is not matching. An "
        "empty feed and a feature that never woke are the same observation "
        "(#1643), so this assertion is the only thing separating them."
    )

    # CLAIM 2 — the restart is DATA, it arrives before the socket dies, AND
    # IT STAYS LONG ENOUGH TO READ. Every message below reports the OBSERVED
    # WORLD and never a cause: this rig records transitions, so it can say
    # what the tab displayed and cannot say why (JOB #2966 property 5). The
    # message it replaces asserted the goodbye "lost its race with the dying
    # socket" and was false on both clauses in the only instance measured
    # end to end (#2930 §2).
    # Interpreted HERE, from the raw recording, by the same two functions the
    # adjudication fixture above executes. Reading the driver's own derived
    # fields instead would leave the fixture testing code this test does not
    # use — a canary wired to a path the rig cannot reach, which is #2666's
    # defect and one I have already shipped once (#2798).
    transitions = report["transitions"]
    sequence = _sequence(transitions)
    dwell = _dwell_ms(transitions)

    observed = (
        f"observed: sequence={sequence} dwell={dwell}ms "
        f"observation={report['observation']}"
    )

    assert "restarting" in sequence, (
        "'restarting' was never DISPLAYED during the shutdown. Transitions are "
        "recorded, not sampled, so this is a statement about the DOM and not "
        "about a capture window — but it names no cause: a goodbye that never "
        "arrived, one that arrived and did not render, and one overwritten "
        "before this rig attached all produce it. "
        f"{observed}"
    )
    assert "reconnecting" in sequence, (
        f"the tab never noticed the board had actually gone. {observed}"
    )
    # ORDERING, RELATIVE — not `index("restarting") == 0`.
    #
    # The old form worked only because the old loop started sampling AFTER
    # the signal, so the first state it could ever see was the shutdown's.
    # The recorder attaches BEFORE the toggle, so the sequence legitimately
    # opens with the tab's healthy states (`live`, and `paused` if the run
    # re-parked) and position 0 is no longer the shutdown's first state.
    # **The property #1639 §2 actually bought is that `restarting` precedes
    # `reconnecting`** — that a restart reads as a restart rather than as a
    # dropped connection — and asserting a fixed index was encoding the old
    # instrument's starting point as if it were the requirement.
    assert sequence.index("restarting") < sequence.index("reconnecting"), (
        f"'reconnecting' was displayed before 'restarting', so the restart "
        f"read as a dropped connection. {observed}"
    )

    # A capture that ran out of patience and one that saw a stable end state
    # are different facts, and the old loop fused them (#2946 §4).
    assert not report["observation"]["capExhausted"], (
        f"the watch loop exhausted its {report['observation']['capIterations']} "
        f"iterations without seeing both states — this is patience exhausted, "
        f"NOT a stable end state, and the sequence below is therefore partial. "
        f"{observed}"
    )

    # THE ASSERTION THIS DELIVERY EXISTS FOR.
    assert dwell >= DWELL_FLOOR_MS, (
        f"'restarting' was displayed for {dwell}ms, under "
        f"the {DWELL_FLOOR_MS}ms floor — so the state existed but no operator "
        f"could read it, and #1639 §2's advantage over SSE/WS is nominal rather "
        f"than real. PRESENCE IS NOT THE PROPERTY; dwell is. "
        f"{observed}"
    )

    # The advised floor is respected, read off the UI the operator reads.
    restarting_text = report["stateDetail"].get("restarting", "")
    assert "back in ~" in restarting_text, restarting_text

    # THE CLIENT-SIDE §854 RULE, end to end.
    assert report["cursorAfterGoodbye"] == report["cursorBeforeGoodbye"], (
        f"the cursor MOVED across a goodbye page: "
        f"{report['cursorBeforeGoodbye']} -> {report['cursorAfterGoodbye']}"
    )

    assert not report["errors"], (
        "console error(s) or uncaught exception(s) while going live:\n"
        + "\n".join(f"  {e}" for e in report["errors"])
    )
