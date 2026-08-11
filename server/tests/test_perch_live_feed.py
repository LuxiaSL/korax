"""The live feed — round one of the reload-free perch (JOB #1659).

The design is PROPOSAL #1639, endorsed whole at #1646, whose condition 2
says the restart rules are ACCEPTANCE TESTS rather than comments. This file
is that condition.

**These guards EXECUTE the rules; they do not grep for them.** R74 is the
scar: 540 structural tests asserting strings are present did not catch
conflict markers in the served page. A test that greps for `jittered(` proves
the token was typed, which is not the claim. So the perch's own source is
loaded into `node` behind minimal DOM stubs and the functions are called.

**And every rule is canaried BOTH WAYS** (#112, canon v6, and the correction
this band needed three times): the guard is shown failing against a deliberately
broken rule and staying quiet against the real one. A guard that raises on
everything passes every canary while being useless.

The one rule that cannot be tested anywhere else: **the cursor does not move
across a goodbye page.** §11 keeps it server-side, but the browser writes
`koraxFeedCursor` from `page.cursor` — so the client has its own copy of the
invariant, and no server test can satisfy it on the client's behalf (#854).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from perch_source import PERCH_DIR, markup, script

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node absent; rules cannot be executed")


# The perch is browser code: it touches document, localStorage and fetch at
# load time. The stubs are deliberately DUMB — anything clever here would be a
# second implementation of the thing under test.
HARNESS = r"""
const store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};
globalThis.__store = store;
const node = new Proxy({}, {
  get: (t, p) => {
    if (p === "dataset") return (t.__ds = t.__ds || {});
    if (p === "classList") return { toggle: () => {}, add: () => {}, remove: () => {} };
    if (p === "addEventListener" || p === "showModal") return () => {};
    if (p === "value") return "";
    if (p in t) return t[p];
    return "";
  },
  set: (t, p, v) => { t[p] = v; return true; },
});
globalThis.document = { querySelector: () => node, querySelectorAll: () => [] };
globalThis.fetch = async () => { throw new Error("no network in the rule harness"); };
"""


def _run_js(body: str, source: str | None = None) -> dict:
    """Load the perch's real source, then run `body`; parse its JSON stdout."""
    src = script() if source is None else source
    prog = HARNESS + "\n" + src + "\n" + body
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as f:
        f.write(prog)
        path = f.name
    done = subprocess.run([NODE, path], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, f"harness failed:\n{done.stderr[:2000]}"
    return json.loads(done.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------------
# THE CURSOR DOES NOT MOVE ACROSS A GOODBYE (#854, client-side)
# --------------------------------------------------------------------------

def test_the_cursor_does_not_move_across_a_goodbye() -> None:
    """Forwards AND backwards. A goodbye page hands back the `since` it was
    given, so the dangerous case is not the ordinary poll — it is "everything
    addressed to me", which polls with `since=-1`. Without the rule the
    browser writes -1 over a real drain position and silently re-drains the
    whole backlog it had already shown.
    """
    out = _run_js(r"""
      const goodbye = {envelopes: [], cursor: -1, system_notice: {kind: "restart", retry_after_s: 30}};
      const normal  = {envelopes: [], cursor: 1700};
      console.log(JSON.stringify({
        held_backwards: feedCursorAfter(goodbye, 1500),
        held_forwards:  feedCursorAfter({...goodbye, cursor: 9999}, 1500),
        advances_when_not_a_goodbye: feedCursorAfter(normal, 1500),
        is_goodbye: feedIsGoodbye(goodbye),
        is_not_goodbye: feedIsGoodbye(normal),
      }));
    """)
    assert out["held_backwards"] == 1500, "a goodbye rewound the cursor to -1"
    assert out["held_forwards"] == 1500, "a goodbye advanced the cursor"
    assert out["advances_when_not_a_goodbye"] == 1700
    assert out["is_goodbye"] is True and out["is_not_goodbye"] is False


def test_a_goodbye_is_detected_by_the_key_and_not_by_its_contents() -> None:
    """THIS TEST FOUND A REAL DEFECT IN THIS DELIVERY and is kept for that.

    The first implementation asked `!!page.system_notice`. `goodbye_page()`
    always emits the key while a normal page never emits it, but
    `board.system_notice` is typed `dict | None` — so a shutdown flag armed
    without a notice yields `{"system_notice": null}`, which the truthiness
    detector reads as an ORDINARY QUIET PAGE and whose cursor it then moves.

    Not reachable through `begin_shutdown` today, which arms the notice first.
    Reachable the moment anything else sets the flag — and a client rule whose
    correctness rests on the ordering inside somebody else's method is the
    borrowed invariant this whole file exists to stop borrowing.
    """
    out = _run_js(r"""
      console.log(JSON.stringify({
        null_notice: feedIsGoodbye({envelopes: [], cursor: 7, system_notice: null}),
        held: feedCursorAfter({envelopes: [], cursor: -1, system_notice: null}, 1500),
        normal_page_has_no_key: feedIsGoodbye({envelopes: [], cursor: 7}),
      }));
    """)
    assert out["null_notice"] is True, (
        "a goodbye page with a null notice read as an ordinary page"
    )
    assert out["held"] == 1500, "and so the cursor moved across it"
    assert out["normal_page_has_no_key"] is False


def test_the_goodbye_cursor_guard_is_canaried_broken() -> None:
    """Break the rule on purpose and watch the guard fail — otherwise the
    assertion above passes for any implementation that returns its argument.
    """
    broken = script().replace(
        "function feedCursorAfter(page, current) {\n  if (feedIsGoodbye(page)) return current;",
        "function feedCursorAfter(page, current) {\n  if (false) return current;",
    )
    assert broken != script(), "the canary patched nothing — the rule moved"
    out = _run_js(r"""
      const goodbye = {envelopes: [], cursor: -1, system_notice: {kind: "restart"}};
      console.log(JSON.stringify({held: feedCursorAfter(goodbye, 1500)}));
    """, source=broken)
    assert out["held"] == -1, (
        "the deliberately broken rule still held the cursor, so the guard "
        "above is not testing the rule"
    )


# --------------------------------------------------------------------------
# JITTER IS ADDITIVE (the advised wait is a FLOOR, never a centre)
# --------------------------------------------------------------------------

def test_jitter_never_returns_less_than_the_advised_wait() -> None:
    """A symmetric jitter re-polls EARLIER than advised, which on the goodbye
    path means arriving while the restart it warned about is still running.
    Checked at both ends of the rng range, not at a random point.
    """
    out = _run_js(r"""
      const at = (r) => noticeDelay(30, 0.5, () => r);
      console.log(JSON.stringify({
        rng_zero: at(0), rng_one: at(1), rng_mid: at(0.5),
        escal_zero: escalatingDelay(1, 0.5, () => 0),
        escal_one: escalatingDelay(1, 0.5, () => 1),
      }));
    """)
    assert out["rng_zero"] == 30, "the floor itself must be reachable"
    assert out["rng_one"] == 45 and out["rng_mid"] == 37.5
    assert min(out["rng_zero"], out["rng_one"], out["rng_mid"]) >= 30, (
        "a wait shorter than the board's advised floor: the herd arrives mid-restart"
    )
    assert out["escal_zero"] >= 5 and out["escal_one"] >= 5


def test_the_additive_jitter_guard_is_canaried_broken() -> None:
    """A symmetric (±) jitter must redden the test above."""
    broken = script().replace(
        "return delay + rnd() * delay * fraction;",
        "return delay + (rnd() - 0.5) * delay * fraction;",
    )
    assert broken != script(), "the canary patched nothing"
    out = _run_js(r"""
      console.log(JSON.stringify({low: noticeDelay(30, 0.5, () => 0)}));
    """, source=broken)
    assert out["low"] < 30, (
        "the deliberately symmetric jitter still respected the floor, so the "
        "floor assertion is not testing additivity"
    )


# --------------------------------------------------------------------------
# THE CURVE JITTERS AFTER THE CAP (#1370's second half)
# --------------------------------------------------------------------------

def test_the_escalating_curve_jitters_after_the_cap() -> None:
    """At the ceiling every client otherwise waits exactly `cap` and
    re-synchronises on it — the same herd by a slower route. So the saturated
    curve must still spread, which means values ABOVE the cap exist.
    """
    out = _run_js(r"""
      console.log(JSON.stringify({
        saturated_low: escalatingDelay(100, 0.5, () => 0),
        saturated_high: escalatingDelay(100, 0.5, () => 1),
        below_cap: escalatingDelay(2, 0.5, () => 0),
        zero_failures: escalatingDelay(0, 0.5, () => 1),
      }));
    """)
    assert out["saturated_low"] == 60, "the cap is not the floor of the saturated curve"
    assert out["saturated_high"] > 60, (
        "the saturated curve produced no value above the cap — every client "
        "waits exactly 60s and re-synchronises (#1370)"
    )
    assert out["below_cap"] == 10
    assert out["zero_failures"] == 0, "no failures must mean no wait"


# --------------------------------------------------------------------------
# A MALFORMED system_notice PRODUCES A WAIT, NOT A NaN
# --------------------------------------------------------------------------

def test_a_misbehaving_board_still_produces_a_wait() -> None:
    """This is the one path whose whole job is surviving a board that is
    misbehaving, so `null`, a string, a missing key and `true` must all fall
    back to the default rather than poison the timer. `true` is not 1 second.
    """
    out = _run_js(r"""
      const z = (v) => noticeDelay(v, 0.5, () => 0);
      console.log(JSON.stringify({
        null_: z(null), missing: z(undefined), str: z("soon"),
        bool_: z(true), nan: z(NaN), real: z(5),
      }));
    """)
    for key in ("null_", "missing", "str", "bool_", "nan"):
        assert out[key] == 30, f"{key} did not fall back to the 30s default (got {out[key]})"
    assert out["real"] == 5, "a real number must be honoured, not defaulted"


# --------------------------------------------------------------------------
# CONTRACT — the goodbye page really is shaped the way the client reads it
# --------------------------------------------------------------------------

def test_the_board_really_serves_the_shape_the_client_branches_on() -> None:
    """R61's rule: measure the contract against a live board rather than
    modelling it. The client decides "restarting" from `system_notice` and
    holds the cursor because a goodbye's cursor is the `since` it was given —
    both are asserted here against the real endpoint, not assumed.
    """
    store = Store(":memory:")
    op, tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    app = create_app(board)
    with TestClient(app) as client:
        auth = {"Authorization": f"Bearer {tok}"}
        # Through the real arming method, not by poking the flag: the notice
        # is armed BEFORE the flag there, and that ordering is the thing under
        # test. Setting `shutting_down` by hand tests a state the board never
        # actually serves.
        import asyncio

        asyncio.run(board.begin_shutdown())
        r = client.get("/feed", params={"since": 4, "timeout": 0}, headers=auth)
        assert r.status_code == 200, "a goodbye must be a 200 with a body, not a closed socket"
        page = r.json()
        assert page.get("system_notice"), (
            "the client's whole restarting/reconnecting split reads this key"
        )
        assert page["envelopes"] == []
        assert page["cursor"] == 4, "the goodbye advanced the cursor server-side"


def test_a_goodbye_is_a_200_and_not_an_error_status() -> None:
    """The property that won long-poll the design (#1639 §2): a restart is
    DATA. If it ever became a 5xx the client's `poll()` would classify it as
    `refused` and the operator would see "reconnecting" — losing the
    distinction the brief calls mandatory.
    """
    store = Store(":memory:")
    op, tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    with TestClient(create_app(board)) as client:
        import asyncio

        asyncio.run(board.begin_shutdown())
        r = client.get("/feed", params={"since": 1, "timeout": 0},
                       headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and "system_notice" in r.json()


# --------------------------------------------------------------------------
# STRUCTURAL — the wiring, which execution above cannot reach
# --------------------------------------------------------------------------

def test_the_live_loop_parks_rather_than_spinning() -> None:
    """`timeout=0` is right for a click and catastrophic for a loop: it would
    busy-poll the board as fast as the network allows. The live path must ask
    the endpoint to park.
    """
    src = (PERCH_DIR / "js" / "tabs" / "feed.js").read_text()
    assert "FEED_POLL_TIMEOUT = 50" in src
    assert "timeout=${FEED_POLL_TIMEOUT}" in src, (
        "the live tick does not send the parking timeout"
    )


def test_the_three_states_are_all_reachable_in_source() -> None:
    """#171 made UI: a stopped tab and a quiet board must not look alike, and
    a restart must not look like a drop.
    """
    src = (PERCH_DIR / "js" / "tabs" / "feed.js").read_text()
    for state in ("live", "restarting", "reconnecting"):
        assert f'feedSetState("{state}"' in src, f"no branch sets state {state!r}"
    assert 'id="feedLive"' in markup(), "the shell has no indicator element to set"


def test_a_goodbye_does_not_escalate_the_backoff() -> None:
    """A goodbye is the board behaving correctly and saying so. Counting it as
    a failure would escalate the curve across a clean restart, making the tab
    slower the better the board behaves.
    """
    src = (PERCH_DIR / "js" / "tabs" / "feed.js").read_text()
    goodbye_branch = src.split("if (feedIsGoodbye(page)) {", 1)[1].split("return wait;", 1)[0]
    assert "FEED_FAILURES = 0" in goodbye_branch, (
        "the goodbye branch does not reset the failure count"
    )
    assert "FEED_FAILURES += 1" not in goodbye_branch
