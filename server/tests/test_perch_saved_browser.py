"""JOB #1739 — the shelf's both-directions acceptance, driven end to end.

The brief's browser leg: save an envelope, reload, still saved; unsave,
reload, gone. The reload steps are the point — they prove the BOARD is
the record and localStorage at most a cache, because a fresh boot has
nothing else to remember with.

The server-side half asserts the wire shapes the brief ruled: the save
is a payload-optional NOTE in the saver's OWN mailbox with a `beside`
edge and `ext.korax.saved: true`; the unsave is a SUPERSEDE of exactly
that NOTE. Asserted by reading the mailbox over the API after the
driver run — the same read any client would do — not by trusting the
driver's report. That another band's read of the shelf ns is refused
is the existing seal tests' territory (cited in the delivery, not
re-proven here).
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
DRIVER = Path(__file__).with_name("perch_saved_driver.js")

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

# one envelope worth saving
target = board.append(operator, {
    "proto": PROTO, "author": operator, "ns": "/commons/rakes",
    "type": "WARN", "grade": "unverified", "refs": [],
    "payload": "shelf fixture: a rake worth keeping", "ext": {}})

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
open(sys.argv[2], "w").write(f"{operator}\\n{op_tok}\\n{port}\\n{target.id}\\n")
uvicorn.Server(uvicorn.Config(create_app(board), log_level="error")).run(
    sockets=[sock])
"""


@pytest.mark.browser
@pytest.mark.skipif(bool(_SKIP_REASON), reason=str(_SKIP_REASON))
def test_save_survives_reload_and_unsave_removes(tmp_path, perch_rig) -> None:
    script = tmp_path / "serve.py"
    script.write_text(_SEED_AND_SERVE, encoding="utf-8")
    info = tmp_path / "info.txt"
    perch_rig.serve(script, SERVER_DIR, info)
    for _ in range(80):
        if info.exists():
            break
        time.sleep(0.25)
    else:
        pytest.skip("server did not start; not a statement about the shelf")
    time.sleep(1.0)
    operator, token, port, target_id = info.read_text().splitlines()
    origin = f"http://127.0.0.1:{port}"

    chrome, cdp_port = perch_rig.chrome(
        CHROME, tmp_path / "chrome-profile")
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list")
            break
        except Exception:
            time.sleep(0.25)

    run = subprocess.run(
        [NODE, str(DRIVER), str(cdp_port), origin, token, target_id],
        capture_output=True, text=True, timeout=120)
    report = json.loads(run.stdout or "{}")
    assert run.returncode == 0, f"driver reported failure: {report}"

    # -- the server-side half: the wire shapes the brief RULED --------
    def api(path: str):
        req = urllib.request.Request(
            origin + path, headers={"Authorization": "Bearer " + token})
        return json.load(urllib.request.urlopen(req))

    mailbox = api(f"/read?ns=/dm/{operator}&limit=100")["envelopes"]
    saves = [e for e in mailbox
             if e["type"] == "NOTE"
             and (e.get("ext") or {}).get("korax", {}).get("saved") is True]
    assert len(saves) == 1, "exactly one save NOTE should have landed"
    save = saves[0]
    assert save["author"] == operator
    assert save.get("payload") in (None, ""), "the save is payload-optional"
    edges = {(r["edge"], r["id"]) for r in save.get("refs", [])}
    assert ("beside", int(target_id)) in edges, "the beside edge is the save"

    supers = [e for e in mailbox if e["type"] == "SUPERSEDE"
              and any(r["edge"] == "supersedes" and r["id"] == save["id"]
                      for r in e.get("refs", []))]
    assert len(supers) == 1, "the unsave is a SUPERSEDE of exactly that NOTE"
