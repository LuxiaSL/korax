"""JOB #2243 (S3) — the board and user pages, driven end to end.

Everything here is a CLICK with an effect asserted (#1843's denominator
rule; #2045 §1: a probe that passes by reading an empty region proves
nothing) — the same discipline S2's own browser leg used, since S3 is
that base's next stage.

THE FIXTURE IS THE ARGUMENT, same as S2's:

  - A small conversation gives the interlink checks something concrete
    to walk: a thread card's author chip -> user page, its ns chip ->
    board page, a board-page row -> thread page, a user-page post row
    -> both.

  - A PROLIFIC author is seeded with more envelopes than the profile's
    own page budget (100), on purpose — this is the #2302 regression
    test. The prior code showed a band's OLDEST 100 envelopes wearing a
    newest-first face; the fixture makes that distinguishable from the
    fix by construction: the LAST envelope posted (the true newest) is
    asserted present, and the bound notice is asserted where it must
    fire. A fixture with <=100 envelopes would pass either
    implementation and prove nothing (#2045 §1's own trap).
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
DRIVER = Path(__file__).with_name("perch_forum_s3_driver.js")

CHROME = (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
          or shutil.which("chromium") or shutil.which("chromium-browser"))
NODE = shutil.which("node")
_SKIP_REASON = (
    "no headless Chrome found" if not CHROME else
    "no `node` found" if not NODE else None
)

#: The profile page's own page budget (bands.js PROFILE_BUDGET). The
#: prolific fixture must exceed it or the bound half of this test is
#: vacuous, same reasoning as S2's NODE_BUDGET.
PROFILE_BUDGET = 100

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

NS = "/commons/rakes"  # permits WARN and FINDING, refuses NOTE (seed.py)

def post_as(author_id, ns, type_, text, refs=()):
    # board.append returns an Envelope MODEL, not a dict (#2232's own
    # session-3 lesson) -- `.id`, never `["id"]`.
    return board.append(author_id, {
        "proto": PROTO, "author": author_id, "ns": ns,
        "type": type_, "grade": "unverified",
        "refs": [{"edge": e, "id": i} for e, i in refs],
        "payload": text, "ext": {}})

def post(type_, text, refs=()):
    return post_as(operator, NS, type_, text, refs)

# -- a small conversation for the interlink checks -----------------------
# Deliberately its OWN small nest, seeded before the flood below: if the
# prolific posts shared this ns, `/view/browse`'s own limit=100 would cap
# the board page's listing before the flood could ever be the reason,
# and a click at a fixture id that fell outside that cap would be a flake
# wearing a test's clothes rather than a real assertion.
convo_root = post("WARN", "S3 driver — the conversation the interlink test follows")
convo_reply = post("FINDING", "S3 driver — answering the root",
                    [("replies", convo_root.id)])

# -- the in-budget canary band, granted BEFORE the flood below --------
# The grant POLICY is itself authored by `operator` (author == requester,
# §1.1.3), so it would otherwise land INSIDE operator's own most-recent
# window and its ns ("/", not LOAD_NS) would silently become "the
# newest post" the profile test picks — a fixture-ordering trap, not an
# application bug, found by this test's own driver reading a real
# rendered ns chip instead of assuming the fixture's shape.
quiet, quiet_tok = store.create_identity("quiet")
LOAD_NS = "/s3-driver/prolific"  # governed by inheriting the root policy
                                  # (WARN/FINDING admitted, grades:True) --
                                  # no POLICY of its own needed for ACTS.
board.append(operator, {
    "proto": PROTO, "author": operator, "ns": "/", "type": "POLICY",
    "grade": "n/a", "refs": [], "ext": {}, "payload": {"grants": [
        # a POLICY at / replaces its grants WHOLESALE (JOB #1693's own
        # lesson) -- the operator's own seat has to be restated, not
        # merely added to.
        {"identity": operator, "ns": "/**", "band": "human"},
        {"identity": quiet, "ns": LOAD_NS, "band": "poster"},
    ]}})
quiet_post = post_as(quiet, LOAD_NS, "FINDING", "S3 driver — the quiet band's only post")

# -- the profile budget/bound fixture: strictly MORE than PROFILE_BUDGET --
# Its OWN nest too (LOAD_NS), separate from NS above for the same reason:
# `recentByAuthor`'s walk is author-scoped and does not care, but keeping
# the flood out of the board page's own nest keeps that page's fixture
# honest and small. Posted LAST so every one of operator's most-recent
# envelopes — the profile page's top-100 window — is genuinely a
# prolific WARN in LOAD_NS, not the grant POLICY above.
PROFILE_BUDGET = %(budget)d
first_prolific = last_prolific = None
for n in range(PROFILE_BUDGET + 10):
    e = post_as(operator, LOAD_NS, "WARN", f"S3 driver — prolific post {n}")
    if first_prolific is None:
        first_prolific = e
    last_prolific = e

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
open(sys.argv[2], "w").write(
    f"{operator}\\n{op_tok}\\n{port}\\n{NS}\\n{LOAD_NS}\\n"
    f"{convo_root.id}\\n{convo_reply.id}\\n"
    f"{first_prolific.id}\\n{last_prolific.id}\\n{quiet}\\n")
uvicorn.Server(uvicorn.Config(create_app(board), log_level="error")).run(
    sockets=[sock])
""" % {"budget": PROFILE_BUDGET}


@pytest.mark.browser
@pytest.mark.skipif(bool(_SKIP_REASON), reason=str(_SKIP_REASON))
def test_the_board_and_user_pages_are_walkable(tmp_path) -> None:
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
            pytest.skip("server did not start; not a statement about S3")
        time.sleep(1.0)
        (operator, token, port, ns, load_ns, convo_root, convo_reply,
         first_prolific, last_prolific, quiet) = info.read_text().splitlines()
        origin = f"http://127.0.0.1:{port}"

        chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={tmp_path / 'chrome-profile'}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # R123's lesson: a CDP wait that falls through silently launches the
        # driver against a dead port, and its first fetch dies as an opaque
        # error that reads as "the driver lost the server". The else-clause
        # is the part that matters.
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
            [NODE, str(DRIVER), str(cdp_port), origin, token, operator, ns,
             load_ns, convo_root, convo_reply, first_prolific, last_prolific, quiet],
            capture_output=True, text=True, timeout=300)
        report = json.loads(run.stdout or "{}")
        assert run.returncode == 0, (
            f"driver reported failure: {report}\nstderr: {run.stderr}")
        assert report["errors"] == [], report["errors"]

        # ── the interlink, all four directions (the brief's own list) ──
        assert report["thread"]["tab"] == "tab-thread"
        assert report["thread"]["cards"] == 2

        assert report["thread"]["authorWentToProfile"] is True, (
            "a thread card's author chip must open the user page — "
            "the shared who() chip is S3's whole mechanism for this")
        assert report["thread"]["nsWentToBoard"] is True, (
            "a thread card's ns chip must open the board page")
        assert report["thread"]["boardMastheadNamesNs"] is True, (
            "the board page's masthead must name the ns it landed on")

        assert report["board"]["rowWentToThread"] is True, (
            "a board-page row must open the thread page")

        assert report["profile"]["tab"] == "tab-bands"
        assert report["profile"]["rowWentToThread"] is True, (
            "a user-page post row must open the thread page")
        assert report["profile"]["rowWentToBoard"] is True, (
            "a user-page post row's ns chip must open the board page")

        # ── #2302: recent-first, not oldest-100-wearing-newest's-face ──
        assert report["profile"]["newestPresent"] is True, (
            "the TRUE newest envelope (the last one posted) must render "
            "on the profile page — the regression this whole amendment "
            "exists to fix showed the oldest 100 instead")
        assert report["profile"]["oldestOfTheOldHundredAbsent"] is True, (
            "if the very first prolific post is STILL on the page, the "
            "walk read forward from genesis rather than backward from "
            "head, and the fixture has failed to distinguish the fix "
            "from the bug")
        assert report["profile"]["rowCount"] == PROFILE_BUDGET, (
            f"the page budget is {PROFILE_BUDGET}; got "
            f"{report['profile']['rowCount']}")
        assert report["profile"]["boundShown"] is True, (
            "an over-budget profile must declare its bound (§10.10, R67)")
        assert report["profile"]["boundSaysLatest"] is True

        # the canary direction: an in-budget band (the operator itself,
        # via seed_board, holds well under 100 posts on a fresh board)
        # must NOT claim a bound — otherwise the notice above proves
        # nothing (#2045 §1, S2's own convention, applied here).
        assert report["profileSmall"]["boundAbsent"] is True, (
            "a band under the page budget must not claim to be bounded"
        )

        # ── compose, ns prefilled (ruled decision 5's second instalment) ──
        assert report["compose"]["nsPrefilled"] is True, (
            "the compose box must open with the page's own ns already "
            "in the field, not empty or a default")
        assert report["compose"]["landed"] is True, (
            f"the board-page post did not reach the board: "
            f"{report['compose']['cardsBefore']} -> "
            f"{report['compose']['cardsAfter']}")
        assert report["compose"]["boxCleared"] is True

        # -- server-side: the compose post is real, in the prefilled ns --
        def api(path: str):
            req = urllib.request.Request(
                origin + path, headers={"Authorization": "Bearer " + token})
            return json.load(urllib.request.urlopen(req))

        posted = [e for e in api(f"/read?ns={ns}&limit=500")["envelopes"]
                  if e["type"] == "FINDING"
                  and "posted from the board page" in (e.get("payload") or "")]
        assert len(posted) == 1, "exactly one compose post should have landed"
        assert posted[0]["ns"] == ns, (
            "the compose box's ns field must have been genuinely prefilled "
            "and genuinely used, not merely displayed")
    finally:
        if chrome is not None and chrome.poll() is None:
            chrome.kill()
        server.kill()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
