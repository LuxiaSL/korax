"""JOB #1842 — the grant console's acceptance, driven end to end.

The brief's browser leg: request posted → review clicked → diff shown →
POLICY landed → grant queryable → OPEN closed. The driver proves the
browser half (including the two refusal directions the happy path cannot
reach: a broken policy read renders as a loud refusal, and a diff with
removals withholds the post button); this file then asserts the
server-side half by reading the board over the API — the same reads any
client would do — not by trusting the driver's report:

  - the successor root POLICY landed, human-band, superseding the prior
    one, with EVERY prior grant carried forward (removed: none is
    re-verified here against the log, independently of the UI's claim);
  - the requested grant is queryable — the requester's band actually
    changed;
  - the OPEN reads closed in the inbox state reduction.

The false-all-clear class (#1843) is why the carried-forward assertion
computes over both grant lists with the denominator checked non-empty:
the test must not itself be green-by-empty-read.
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "server"
DRIVER = Path(__file__).with_name("perch_grant_console_driver.js")

CHROME = (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
          or shutil.which("chromium") or shutil.which("chromium-browser"))
NODE = shutil.which("node")
_SKIP_REASON = (
    "no headless Chrome found" if not CHROME else
    "no `node` found" if not NODE else None
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


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

# the requester: a fresh band on the visitor floor, asking for claimant
requester, req_tok = store.create_identity("console-fixture-requester")
request = board.append(requester, {
    "proto": PROTO, "author": requester, "ns": "/korax/inbox",
    "type": "OPEN", "grade": "n/a", "refs": [],
    "payload": "grant request: claimant on /korax-dev/**",
    "ext": {"korax": {"grant_request": {
        "identity": requester, "display": "console-fixture-requester",
        "grants": [{"ns": "/korax-dev/**", "band": "claimant"}]}}}})

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
open(sys.argv[2], "w").write(
    f"{operator}\\n{op_tok}\\n{requester}\\n{port}\\n{request.id}\\n")
uvicorn.Server(uvicorn.Config(create_app(board), log_level="error")).run(
    sockets=[sock])
"""


@pytest.mark.browser
@pytest.mark.skipif(bool(_SKIP_REASON), reason=str(_SKIP_REASON))
def test_approve_shows_the_diff_posts_the_policy_and_closes(tmp_path) -> None:
    script = tmp_path / "serve.py"
    script.write_text(_SEED_AND_SERVE, encoding="utf-8")
    info = tmp_path / "info.txt"
    server = subprocess.Popen([sys.executable, str(script), str(SERVER_DIR), str(info)])
    chrome = None
    cdp_port = _free_port()
    try:
        for _ in range(80):
            if info.exists():
                break
            time.sleep(0.25)
        else:
            pytest.skip("server did not start; not a statement about the console")
        time.sleep(1.0)
        operator, token, requester, port, open_id = info.read_text().splitlines()
        origin = f"http://127.0.0.1:{port}"

        def api(path: str):
            req = urllib.request.Request(
                origin + path, headers={"Authorization": "Bearer " + token})
            return json.load(urllib.request.urlopen(req))

        # the denominator BEFORE the driver runs — the non-empty proof this
        # test's own carried-forward assertion rests on (#1843's rule,
        # applied to the test as much as to the UI)
        before = api("/policy?ns=%2F")
        grants_before = before["payload"]["grants"]
        assert len(grants_before) > 0, "seed policy served no grants — the rig is broken"
        key = lambda g: (g["identity"], g["ns"], g["band"])  # noqa: E731

        chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={tmp_path / 'chrome-profile'}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # The else-clause is the fix for CI run 31557685663 (#2009/#2017):
        # this loop used to exhaust SILENTLY, launching the driver against a
        # dead CDP port — whose first fetch then died as "TypeError: fetch
        # failed" with an empty report, reading as "the driver lost the
        # server" when Chrome had simply not answered in time on a loaded
        # runner. The budget is 60s because this job runs four browser
        # tests, each with its own Chrome, on two cores.
        for _ in range(240):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list")
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.fail(
                "headless Chrome did not answer its CDP port within the "
                "budget — the driver was NOT launched (a silent fall-through "
                "here is how a slow runner read as a mid-test server loss)"
            )

        run = subprocess.run(
            [NODE, str(DRIVER), str(cdp_port), origin, token, open_id],
            capture_output=True, text=True, timeout=120)
        report = json.loads(run.stdout or "{}")
        assert run.returncode == 0, f"driver reported failure: {report}"

        # -- the POLICY landed, wholesale-safe ----------------------------
        after = api("/policy?ns=%2F")
        assert after["policy"] != before["policy"], "no successor POLICY landed"
        grants_after = after["payload"]["grants"]
        carried = {key(g) for g in grants_after}
        lost = [g for g in grants_before if key(g) not in carried]
        assert lost == [], f"the approval REMOVED grants: {lost} (#1198)"
        assert (requester, "/korax-dev/**", "claimant") in carried, \
            "the requested grant did not land"

        # -- the grant is queryable: the requester's band actually changed
        idents = api("/identities")["identities"]
        mine = next(i for i in idents if i["id"] == requester)
        assert any(g["ns"] == "/korax-dev/**" and g["band"] == "claimant"
                   for g in mine.get("grants", [])), \
            "the registry does not show the new grant"

        # -- the OPEN reads closed in the state reduction ------------------
        state = api("/view/state?ns=/korax/inbox")["output"]
        assert int(open_id) not in state.get("opens", []), \
            "the OPEN is still pending after approval"
    finally:
        if chrome is not None and chrome.poll() is None:
            chrome.kill()
        server.kill()
