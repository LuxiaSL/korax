"""`/conformance.boot_id` — the board's restart witness (#2387, ruled #2393).

**What was missing.** The board could report what CODE it was running and
could not report *whether this is the same process that answered a minute
ago*. Nothing build-derived can close that: a restart on the SAME sha
leaves every such fact unchanged, and that restart is precisely the
cleanest R85 equivalence window there is — so a rule like "the build
identifier must differ" would reject exactly the measurement most worth
having.

**What it already cost.** `tools/r85_compare.py` needs "did the process
restart and rebuild state from sqlite" as its central precondition. The
mill found the gap by RUNNING the tool against production (#2360): head
had advanced, the liveness check passed, nine digests came back
identical, and nothing had been measured — the incremental join compared
against itself. Until this field exists the witness is hand-carried
(`--service-active-since`, an operator reading systemd).

**The acceptance is the same-sha case, and it is easy to fake passing.**
A test that restarts onto a *different* build would see the id change and
prove nothing, because a build-derived value would also change. So the
canary boots one unchanged tree twice. And a value that changed on every
REQUEST would satisfy differs-on-restart too, which is why the stability
control sits beside it rather than being assumed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from korax.api import BOOT_ID, create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

SERVER_DIR = Path(__file__).resolve().parents[1]


def _world() -> Board:
    store = Store(":memory:")
    operator, _token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    return board


def _conformance(board: Board) -> dict:
    return TestClient(create_app(board)).get("/conformance").json()


# ── the field, where it was ruled to be ───────────────────────────────

def test_conformance_serves_a_boot_id_at_the_top_level() -> None:
    body = _conformance(_world())
    assert "boot_id" in body, "the board must be able to say which process it is"
    assert isinstance(body["boot_id"], str) and body["boot_id"]


def test_the_boot_id_is_not_nested_under_serving() -> None:
    """**Placement is load-bearing, and the first ruling got it wrong.**

    `serving` is written unconditionally by the MCP client onto the board's
    own response body (`server.py:2402`, filed #2392). A nonce placed there
    would be silently replaced by a fact about the CALLER's process — a
    tool asking "did the board restart" would be told whether its own MCP
    client restarted, and could not tell the difference. #2388 ruled it
    there on a false premise of mine; #2391 corrected it and #2393
    superseded the placement. This pins the corrected one.
    """
    body = _conformance(_world())
    assert "serving" not in body, (
        "the server must not serve a `serving` key — that name belongs to "
        "the MCP client's self-report and would be clobbered (#2392)"
    )


def test_the_boot_id_is_not_a_timestamp() -> None:
    """Random, per the ruling: a timestamp invites arithmetic nobody should
    do with it, and the only contract is differs-on-restart."""
    boot = _conformance(_world())["boot_id"]
    assert not boot.replace("-", "").replace(":", "").replace("T", "").isdigit()
    assert len(boot) >= 16, "long enough not to collide by accident"


# ── the control: stable within one process ────────────────────────────

def test_it_is_stable_across_requests_in_one_process() -> None:
    """**The control that makes the canary below mean something.** A value
    regenerated per request would also "differ across a restart" and would
    be useless — every comparison would report a restart that never
    happened, which is the failure this field exists to prevent, inverted.
    """
    board = _world()
    client = TestClient(create_app(board))
    first = client.get("/conformance").json()["boot_id"]
    second = client.get("/conformance").json()["boot_id"]
    assert first == second


def test_two_apps_in_one_process_report_the_same_boot() -> None:
    """It identifies the PROCESS, not the app. Two `create_app` calls in one
    interpreter are one boot; a per-app value would read as a restart to
    anything comparing across them, and the suite itself builds dozens."""
    assert _conformance(_world())["boot_id"] == _conformance(_world())["boot_id"]
    assert _conformance(_world())["boot_id"] == BOOT_ID


# ── the canary: a SAME-SHA restart changes it ─────────────────────────

_PRINT_BOOT = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from korax.api import BOOT_ID; print(BOOT_ID)"
)


def _boot_in_subprocess() -> str:
    run = subprocess.run(
        [sys.executable, "-c", _PRINT_BOOT, str(SERVER_DIR)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert run.returncode == 0, run.stderr
    return run.stdout.strip()


def test_a_same_sha_restart_changes_the_boot_id() -> None:
    """**THE ACCEPTANCE, and the reason it uses subprocesses.**

    Two boots of the SAME unchanged tree — no merge, no rebuild, not one
    byte different. That is the case `built_from` and every other
    build-derived fact structurally cannot see, and it is the case that
    matters: an ordinary service restart. A canary that restarted onto a
    different build would pass while proving nothing, because a
    build-derived value would change too.
    """
    first = _boot_in_subprocess()
    second = _boot_in_subprocess()
    assert first and second
    assert first != second, (
        "two boots of an unchanged tree reported the same boot_id — the "
        "field cannot witness a same-sha restart, which is the only case "
        "it exists for"
    )


def test_the_canary_direction_holds_within_a_boot() -> None:
    """The canary above must be able to fail for the right reason: within a
    single interpreter the value does not move, so a difference across two
    of them is the restart and not noise."""
    assert BOOT_ID == BOOT_ID
    assert _conformance(_world())["boot_id"] == BOOT_ID
