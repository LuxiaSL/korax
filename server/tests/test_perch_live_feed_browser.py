"""The live feed's two claims, in a real browser (JOB #1659).

`test_perch_live_feed.py` executes the RULES behind DOM stubs — jitter,
backoff, the cursor hold. This file executes the FEATURE, because both of the
job's actual claims are about ORDERING that no stub reproduces:

1. **an envelope from another band renders without a reload**, and
2. **a restart shows "restarting" BEFORE "reconnecting"** — the property that
   won long-poll the design (#1639 §2), true only if the goodbye page wins its
   race with the dying socket. A unit test can assert that the client branches
   on `system_notice`; only a real shutdown shows that the branch is reachable.

Marked `browser` and so excluded from the default run (R94's convention), which
means **the mill's gate leg is what enforces it** — same standing as
`test_perch_smoke.py`, whose subprocess-server pattern this follows.

The seeded corpus is its own, deliberately: coupling this to another
delivery's seeder would make two unrelated jobs need to land in a gate order
(#1615's reasoning, adopted).
"""

from __future__ import annotations

import json
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

    # CLAIM 2 — the restart is DATA, and it arrives before the socket dies.
    assert "restarting" in report["stateSequence"], (
        f"no 'restarting' state was ever shown — the goodbye page lost its "
        f"race with the dying socket, and the design's whole advantage over "
        f"SSE/WS is theoretical. Sequence seen: {report['stateSequence']}"
    )
    assert report["stateSequence"].index("restarting") == 0, (
        f"'reconnecting' preceded 'restarting': {report['stateSequence']}"
    )
    assert "reconnecting" in report["stateSequence"], (
        f"the tab never noticed the board had actually gone: "
        f"{report['stateSequence']}"
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
