"""JOB #2199 (S2) — the thread page, driven end to end in a real browser.

The brief's acceptance leg. Everything here is a CLICK with an effect
asserted, because the alternative — reading the rendered HTML and
believing it — is how a page passes a test while showing the wrong
thing to a person (#1843's denominator rule, and my own #2045 §1: a
probe that passes by reading an empty region proves nothing).

THE FIXTURE IS THE ARGUMENT. Two components, seeded to make the two
claims falsifiable:

  A — five envelopes citing each other, where the one we DEEP-LINK TO
      is deliberately the MIDDLE of its conversation. `root at top`
      means the component's oldest id leads; `highlight` means the
      envelope you followed is marked wherever it falls. A fixture
      whose focus was also its oldest would satisfy both assertions
      while testing neither.

  B — a hub cited by seventy envelopes, which is PAST the walk's
      MAX_NODES budget of 60 on purpose. The truncation notice is
      asserted here, where it must fire, and its absence is asserted
      on A, where it must not. A bound tested only on a small
      component is a bound never tested at all.

The reply box is exercised in both directions (#112): `/commons/rakes`
permits FINDING and does NOT permit NOTE, so the same box posts once
and is refused once, and the refusal has to be legible rather than a
button that quietly did nothing.
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
DRIVER = Path(__file__).with_name("perch_thread_driver.js")

CHROME = (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
          or shutil.which("chromium") or shutil.which("chromium-browser"))
NODE = shutil.which("node")
_SKIP_REASON = (
    "no headless Chrome found" if not CHROME else
    "no `node` found" if not NODE else None
)

#: The walk's own budget (search.py MAX_NODES). The fixture must exceed it
#: or the truncation half of this test is vacuous.
NODE_BUDGET = 60

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

# `/commons/rakes` permits WARN and FINDING and refuses NOTE (seed.py's
# policy), which is what lets the reply box be canaried both ways.
def warn(text, refs=()):
    # board.append returns an Envelope MODEL, not a dict — `e.id`, never
    # `e["id"]`. The in-process append and the HTTP path differ here.
    return board.append(operator, {
        "proto": PROTO, "author": operator, "ns": "/commons/rakes",
        "type": "WARN", "grade": "unverified",
        "refs": [{"edge": e, "id": i} for e, i in refs],
        "payload": text, "ext": {}})

# -- component A: a conversation whose middle is the deep link ----------
a1 = warn("A1 — the first word in this conversation")
a2 = warn("A2 — answering the first word", [("replies", a1.id)])
a3 = warn("A3 — the envelope the URL names; it cites two earlier ones",
          [("replies", a2.id), ("derives-from", a1.id)])
a4 = warn("A4 — answering A3", [("replies", a3.id)])
a5 = warn("A5 — citing the first word from further away",
          [("derives-from", a1.id)])

# -- component B: seeded PAST the node budget on purpose ----------------
hub = warn("HUB — a much-cited envelope; its component does not fit")
for n in range(70):
    warn(f"spoke {n} — one of many citing the hub", [("derives-from", hub.id)])

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
open(sys.argv[2], "w").write(
    f"{operator}\\n{op_tok}\\n{port}\\n"
    f"{a3.id}\\n{a1.id}\\n{a2.id}\\n{a4.id}\\n{hub.id}\\n")
uvicorn.Server(uvicorn.Config(create_app(board), log_level="error")).run(
    sockets=[sock])
"""


@pytest.mark.browser
@pytest.mark.skipif(bool(_SKIP_REASON), reason=str(_SKIP_REASON))
def test_the_thread_page_reads_as_a_conversation(tmp_path) -> None:
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
            pytest.skip("server did not start; not a statement about the thread page")
        time.sleep(1.0)
        operator, token, port, focus, lead, quoted, neighbour, hub = \
            info.read_text().splitlines()
        origin = f"http://127.0.0.1:{port}"

        chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={tmp_path / 'chrome-profile'}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # R123's lesson, applied rather than cited: a CDP wait that falls
        # through SILENTLY launches the driver against a dead port, and its
        # first fetch dies as `TypeError: fetch failed` with an empty report
        # — which reads as "the driver lost the server" when Chrome simply
        # never answered. 60s because these run several browsers on few
        # cores; the else-clause is the part that matters.
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
                "here is how a slow runner reads as a mid-test server loss)"
            )

        run = subprocess.run(
            [NODE, str(DRIVER), str(cdp_port), origin, token,
             focus, lead, quoted, neighbour, hub],
            capture_output=True, text=True, timeout=300)
        report = json.loads(run.stdout or "{}")
        assert run.returncode == 0, (
            f"driver reported failure: {report}\nstderr: {run.stderr}")
        assert report["errors"] == [], report["errors"]

        focus_id, lead_id = int(focus), int(lead)

        # -- the page loaded from a cold deep link -----------------------
        assert report["cold"]["tab"] == "tab-thread", (
            "#/e/<id> must land on the THREAD, not the single-envelope tab — "
            "that redirection is the whole of S2")
        assert report["cold"]["cards"] == 5, (
            f"the component is five envelopes; the page rendered "
            f"{report['cold']['cards']}")

        # -- root at top and highlight are DIFFERENT properties ----------
        assert report["order"]["firstCard"] == lead_id, (
            "the oldest id must lead — 'root at top' is the component's "
            "oldest, not the envelope the URL named")
        assert report["order"]["ascending"] is True, "the page must be id-ordered"
        assert report["order"]["focusIsHighlighted"] is True, (
            "the envelope you followed must be marked")
        assert report["order"]["focusIndex"] > 0, (
            "THE FIXTURE HAS GONE VACUOUS: the focus is also the first card, "
            "so 'oldest leads' and 'focus highlighted' cannot be told apart")

        # -- quotelinks out, backlinks in --------------------------------
        assert report["links"]["quotelinksOnFocus"] == 2, (
            "the focus cites two envelopes; both must render as quotelinks")
        assert report["links"]["quoteCarriesEdge"] is True, (
            "a quotelink must name its edge — 'why does this cite that' "
            "belongs on the chip")
        assert report["links"]["backlinksOnLead"] == 3, (
            "three envelopes cite the lead; backlinks are refs INVERTED "
            "across the component, and this is the assertion that the "
            "inversion ran at all")
        assert report["links"]["jumpFlashed"] is True, (
            "following a quotelink must say where it put you — a silent "
            "scroll on a page of similar cards reads as nothing happening")

        # -- collapse is also the payload loader -------------------------
        assert report["collapse"]["bodyHiddenBefore"] is True
        assert report["collapse"]["textBefore"] == 0, (
            "the walk's summaries carry no payload, so a non-focus card "
            "must start with no prose — otherwise 60 payloads were fetched "
            "eagerly, which is the storm the brief forbids")
        assert report["collapse"]["bodyHiddenAfter"] is False
        assert report["collapse"]["textAfter"] > 0, (
            "expanding must FETCH; a class flip with no text is the control "
            "working and the loader not")
        assert report["collapse"]["ariaAfter"] == "true"
        assert report["collapse"]["reclosed"] is True, (
            "a toggle that only opens is half a control")

        # -- the #id modal, ruled decision 3 -----------------------------
        assert report["modal"]["open"] is True, (
            "the #id chip must open the modal — it used to navigate, and "
            "taking the whole screen for one citation was the wrong default")
        assert report["modal"]["urlUnchanged"] is True, (
            "'without breaking the current screen or URL' — the chip must "
            "not move the hash")
        assert report["modal"]["titleNames"] is True
        assert report["modal"]["metaRendered"] is True
        assert report["modal"]["peekFilled"] is True, "read-it-here must fetch"
        assert report["modal"]["peekCollapsed"] is True, (
            "expand-COLLAPSE — the second half of the gesture")
        assert report["modal"]["wentToThread"] is True, (
            "go-to-thread must move the URL, the section AND the highlight")
        assert report["modal"]["closedAfterGo"] is True
        assert report["modal"]["replyFocused"] is True, (
            "reply-to-it must land with the cursor in the box; a reply "
            "action that leaves you hunting for the box is a link")
        assert report["modal"]["replyAimed"] is True

        # -- the reply box posts, and its refs were prefilled ------------
        assert report["reply"]["landed"] is True, (
            f"the reply did not reach the board: "
            f"{report['reply']['cardsBefore']} -> {report['reply']['cardsAfter']}")
        assert report["reply"]["backlinkOnFocus"] >= 1, (
            "the posted reply must cite the card it was aimed at — it "
            "appears as a BACKLINK on the focus, which only happens if the "
            "prefilled ref actually pointed there")
        assert report["reply"]["replyBoxCleared"] is True

        # ...and is refused legibly in the other direction
        assert report["reply"]["refusedCards"] == report["reply"]["cardsAfter"], (
            "NOTE is not permitted in /commons/rakes; the refused post must "
            "not have landed")
        assert report["reply"]["refusalToasted"] is True, (
            "a refused post must SAY so — a box that silently does nothing "
            "is the failure mode this canary exists for")

        # -- the bound, asserted where it fires --------------------------
        assert report["bound"]["truncatedShown"] is True, (
            "the over-budget component must declare its truncation")
        assert report["bound"]["saysBounded"] is True
        assert report["bound"]["namesTheBudget"] is True, (
            "a bound the reader cannot inspect is a bound they will read "
            "as an absence (§10.10, R67)")
        assert report["bound"]["saysLowerBound"] is True, (
            "when the walk truncated, backlinks are a LOWER BOUND — an "
            "envelope outside the budget citing one of these is real and "
            "absent, and the page must not imply otherwise")
        assert report["bound"]["completeAbsent"] is True

        # the canary direction: no seal on a component that closed, and a
        # positive statement that it closed, so "no seal" is never
        # ambiguous between complete and unchecked
        assert report["bound"]["inBudgetNoSeal"] is True, (
            "the in-budget component must NOT claim a bound — otherwise the "
            "notice above proves nothing")
        assert report["bound"]["inBudgetSaysComplete"] is True

        # -- the server-side half: the reply is a real envelope ----------
        def api(path: str):
            req = urllib.request.Request(
                origin + path, headers={"Authorization": "Bearer " + token})
            return json.load(urllib.request.urlopen(req))

        posted = [e for e in api("/read?ns=/commons/rakes&limit=200")["envelopes"]
                  if e["type"] == "FINDING"
                  and "posted from the thread page" in (e.get("payload") or "")]
        assert len(posted) == 1, "exactly one reply should have landed"
        edges = {(r["edge"], r["id"]) for r in posted[0].get("refs", [])}
        assert ("replies", focus_id) in edges, (
            "the reply box's prefilled ref must reach the board as a real "
            "edge, not merely render as one")
        # §6.1 — the box sends no grade and the board resolves it. A client
        # that guessed would be refused in exactly the nests it guessed wrong.
        assert posted[0]["grade"] == "unverified", (
            "an omitted grade must resolve per §6.1 (unverified for a "
            "content act in a graded nest)")
    finally:
        if chrome is not None and chrome.poll() is None:
            chrome.kill()
        server.kill()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
