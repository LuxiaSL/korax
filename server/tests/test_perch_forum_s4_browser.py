"""JOB #2505 (S4) — home, profile, and the gate, driven end to end.

Every gesture is a CLICK with an effect asserted (#1843's denominator
rule; #2045 §1: a probe that passes by reading an empty region proves
nothing).

THE FIXTURE IS THE ARGUMENT. A board with real data is seeded FIRST, so
the cold-unbound assertion is the vacuous-absence trap's own remedy
(#2045 §1, restated in the brief's own acceptance line): asserting "no
data rendered" against an empty board proves nothing, since an empty
board would render nothing either way. The DM below is what a bound
visit must show and an unbound one must not.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "server"
DRIVER = Path(__file__).with_name("perch_forum_s4_driver.js")

CHROME = (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
          or shutil.which("chromium") or shutil.which("chromium-browser"))
NODE = shutil.which("node")
_SKIP_REASON = (
    "no headless Chrome found" if not CHROME else
    "no `node` found" if not NODE else None
)

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

# A DM lands in the operator's own mailbox lane — the /feed union's
# simplest guaranteed member, so a bound visit's first-ever feed load
# (loadFeed's cursor=-1 backlog pull) has something real to show, and
# the marker string is what the cold-unbound assertion checks is ABSENT
# from the served bytes.
MARKER = "S4 driver -- the DM only a bound visit may see"
dm = board.append(operator, {
    "proto": PROTO, "author": operator, "ns": "/dm/" + operator,
    "type": "NOTE", "grade": "n/a", "refs": [], "payload": MARKER, "ext": {}})

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
open(sys.argv[2], "w").write(
    f"{operator}\\n{op_tok}\\n{port}\\n{dm.id}\\n")
uvicorn.Server(uvicorn.Config(create_app(board), log_level="error")).run(
    sockets=[sock])
"""

MARKER = "S4 driver -- the DM only a bound visit may see"


@pytest.mark.browser
@pytest.mark.skipif(bool(_SKIP_REASON), reason=str(_SKIP_REASON))
def test_home_profile_and_the_gate(tmp_path, perch_rig) -> None:
    script = tmp_path / "serve.py"
    script.write_text(_SEED_AND_SERVE, encoding="utf-8")
    info = tmp_path / "info.txt"
    perch_rig.serve(script, SERVER_DIR, info)
    for _ in range(80):
        if info.exists():
            break
        time.sleep(0.25)
    else:
        pytest.skip("server did not start; not a statement about S4")
    time.sleep(1.0)
    operator, token, port, dm_id = info.read_text().splitlines()
    origin = f"http://127.0.0.1:{port}"

    chrome, cdp_port = perch_rig.chrome(
        CHROME, tmp_path / "chrome-profile")
    for _ in range(240):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list")
            break
        except Exception:
            time.sleep(0.25)
    else:
        pytest.fail(
            "headless Chrome did not answer its CDP port within the "
            "budget — the driver was NOT launched"
        )

    run = subprocess.run(
        [NODE, str(DRIVER), str(cdp_port), origin, token, operator],
        capture_output=True, text=True, timeout=300)
    report = json.loads(run.stdout or "{}")
    assert run.returncode == 0, (
        f"driver reported failure: {report}\nstderr: {run.stderr}")
    assert report["errors"] == [], report["errors"]

    # ── cold, unbound: the gate, and NOTHING else ───────────────────
    assert report["cold"]["gateVisible"] is True, (
        "an unbound cold load must show the gate")
    assert report["cold"]["navHidden"] is True
    assert report["cold"]["mainHidden"] is True
    # the vacuous-absence trap's own remedy (#2045 §1): the board
    # HAS the marker DM, so its absence from the unbound page proves
    # the gate rather than an empty fixture proving nothing
    assert report["cold"]["markerAbsent"] is True, (
        "the seeded DM must not appear anywhere in the unbound page's "
        "bytes — the gate must narrow what renders, not just what a "
        "loader is told to fetch")

    # ── token entry -> home is the feed, live ───────────────────────
    assert report["afterLogin"]["gateHidden"] is True
    assert report["afterLogin"]["navVisible"] is True
    assert report["afterLogin"]["landedTab"] == "tab-feed", (
        "home for a bound identity is the feed (S4's own line), not "
        f"the prior default; got {report['afterLogin']['landedTab']}")
    assert report["afterLogin"]["markerPresent"] is True, (
        "the bound visitor's own feed must show the seeded DM")

    # ── the profile hub: the four links, walked and back ────────────
    assert report["you"]["tab"] == "tab-you"
    assert report["you"]["selfIdentityShown"] is True
    assert report["you"]["toInbox"] is True
    assert report["you"]["toShelf"] is True
    assert report["you"]["toPosts"] is True, (
        "the Posts link must land on the viewer's OWN profile page "
        "(#/band/<own id>) — the S3 user page, self-directed")
    assert report["you"]["toBands"] is True

    # ── a fresh cold load, bound: home is still the feed ────────────
    assert report["coldBound"]["landedTab"] == "tab-feed"


