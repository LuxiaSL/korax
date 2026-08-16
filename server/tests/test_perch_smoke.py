"""ISSUE #1597, JOB #1615 — a real browser walks every route (JOB #1969).

S1 (the router) turned the TABS list into a ROUTES list, per the forum
base's own acceptance: every route navigated warm, walked back with the
back button, and cold-loaded as a deep link; plus the #1941 census —
every markup-bound symbol exercised through a real click.

The R82-split bug (`postNsValue`, R90) was a called-but-undefined
identifier: a runtime ReferenceError, invisible to `node --check` (proves
syntax, not completeness), to the manifest test (proves every file ships),
and to every other structural guard the perch has, because none of them
ask whether a real JS engine can execute the shell's top-level script
without throwing. Only a real browser executing the real page asks that
question, so this test drives one — real headless Chrome over CDP, no
simulated DOM, per the brief's ruling (a simulation can lie in exactly
this dimension) and quill's #1431/#1491 prior art tonight (zero installs;
Node 22 ships `WebSocket` and `fetch` built in).

**What this does NOT reuse, and why.** The brief names
`tools/seed_dev_board.py` (JOB #1363) as the seeder. That JOB is still
unmerged at the mill's gate as this one is written — reusing it here
would make two unrelated deliveries need to land in a specific order at
the gate, which is exactly the coupling the cadence rule exists to avoid.
This test seeds its own small, deterministic corpus instead: enough to
light every tab non-empty, nothing shared with #1363's richer one.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "server"
DRIVER = Path(__file__).with_name("perch_smoke_driver.js")

CHROME = (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
          or shutil.which("chromium") or shutil.which("chromium-browser"))
NODE = shutil.which("node")

# **Verified on this host, not assumed** (#1422's lesson: CI's environment
# is a measurement). The runner measurement this comment used to ask for
# HAPPENED — run 31546925763 (R96): ubuntu-latest ships Chrome and the
# suite executed there, no skip. The ruling that followed (#1697): where
# the capability is PROVEN, a silent skip would let CI's green lie about
# exactly the class R94 exists to catch — so the workflow opts in to a
# hard requirement via KORAX_BROWSER_REQUIRED=1, and a missing dependency
# there FAILS naming what is absent. Everywhere else (every local run)
# the skip stays exactly as chosen: a contributor without Chrome loses
# one guard they can read about, not their suite.
_SKIP_REASON = (
    "no headless Chrome found (checked google-chrome, chromium, "
    "chromium-browser)" if not CHROME else
    "no `node` found" if not NODE else None
)
_REQUIRED = os.environ.get("KORAX_BROWSER_REQUIRED") == "1"



# Mirrors test_goodbye_signal.py's subprocess-server pattern (R83's
# port=0-and-handoff shape): the child binds its own port and reports it
# back through the info file, so there is no window in which a chosen
# port could be taken by something else on a shared host.
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
seed_board(board, operator)  # canon, rakes, commons policies — the baseline

alice, alice_tok = store.create_identity("smoke-alice")
bob, bob_tok = store.create_identity("smoke-bob")

def post(author, ns, type_, payload, refs=None, grade="n/a", ext=None, pointer=None):
    raw = {"proto": PROTO, "author": author, "ns": ns, "type": type_,
           "grade": grade, "refs": refs or [], "payload": payload,
           "ext": ext or {}}
    if pointer:
        raw["pointer"] = pointer
    return board.append(author, raw)

# a project nest wide enough to light flight/browse/nest without needing
# any tab-side input — the defaults every one of them falls back to
post(operator, "/korax-dev", "POLICY", {
    "acts": ["NOTE", "FINDING", "JOB", "CLAIM", "OPEN", "PROPOSAL", "WARN",
             "SUPERSEDE", "BESIDE", "HANDOVER", "ACK", "STAMP", "POLICY"],
    "grades": True,
    "retention": {"mode": "permanent"},
    "view_floor": "unverified",
    # The operator holds human on /** from seed_board and NOTHING scoped:
    # a SCOPED human grant here made inboxFor() route the operator's inbox
    # tab to /korax-dev/inbox, so the OPEN this seed plants in /korax/inbox
    # was never visible to the tab and the old probe passed on the
    # empty-state text — green-by-empty-read (#1843), caught by the S1
    # census's "untouched" assertion. The live board's operator is root
    # human with no scoped grant; the rig now mirrors that.
    "grants": [
        {"identity": alice, "ns": "/korax-dev/**", "band": "claimant"},
        {"identity": bob, "ns": "/korax-dev/**", "band": "claimant"},
    ],
})

# flight: one open, one taken, one delivered
j1 = post(operator, "/korax-dev/jobs", "JOB", "smoke: open job — nothing here is real work",
          pointer={"uri": "git:README.md@0000000", "sha256": "0" * 64, "bytes": 1,
                   "media_type": "text/markdown"})
j2 = post(operator, "/korax-dev/jobs", "JOB", "smoke: taken job",
          pointer={"uri": "git:README.md@0000000", "sha256": "0" * 64, "bytes": 1,
                   "media_type": "text/markdown"})
post(alice, "/korax-dev/jobs", "CLAIM", "CLAIM — smoke job 2",
     refs=[{"edge": "claims", "id": j2.id}], ext={"lease_until": "2030-01-01T00:00:00Z"})
j3 = post(operator, "/korax-dev/jobs", "JOB", "smoke: delivered job",
          pointer={"uri": "git:README.md@0000000", "sha256": "0" * 64, "bytes": 1,
                   "media_type": "text/markdown"})
post(bob, "/korax-dev/jobs", "FINDING", "smoke: delivered", grade="unverified",
     refs=[{"edge": "closes", "id": j3.id}])

# browse/ledger/nest content beyond the jobs above
post(operator, "/korax-dev", "NOTE", "smoke: a note for browse and nest to find")

# inbox: one open request, so the badge and the opens list both light
post(alice, "/korax/inbox", "OPEN", "smoke: an ask for the operator")

# feed, as the OPERATOR (the identity this browser session authenticates
# as): a mention lights the mention lane, a DM lights mailbox.
post(alice, "/korax-dev", "NOTE", "smoke: mentioning the operator",
     ext={"korax": {"mentions": [operator]}})
post(alice, "/dm/" + operator, "NOTE", "smoke: a DM for the feed's mailbox lane")

# a thread with a child, so the census (JOB #1969) has a ▸ toggle to click:
# the conversation walk around the root must contain at least one node
thread_root = post(alice, "/korax-dev", "NOTE", "smoke: thread root for the toggle census")
post(bob, "/korax-dev", "NOTE", "smoke: a reply the census expands",
     refs=[{"edge": "replies", "id": thread_root.id}])

probe_envelope_id = j1.id

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
open(sys.argv[2], "w").write(
    f"{operator}\\n{op_tok}\\n{port}\\n{probe_envelope_id}\\n{thread_root.id}\\n")
uvicorn.Server(uvicorn.Config(create_app(board), log_level="error")).run(
    sockets=[sock])
"""


@pytest.mark.browser
@pytest.mark.skipif(bool(_SKIP_REASON) and not _REQUIRED, reason=str(_SKIP_REASON))
def test_every_route_renders_without_console_errors(tmp_path, perch_rig) -> None:
    if _REQUIRED and _SKIP_REASON:
        # #1697's flip: where the environment DECLARED the browser leg
        # required, a missing dependency is a failure that names itself —
        # a skip inside that green would fabricate the signal (#287).
        pytest.fail(
            f"KORAX_BROWSER_REQUIRED=1 but {_SKIP_REASON} — the browser leg "
            "may not silently skip where it is declared required (#1697)"
        )
    script = tmp_path / "serve.py"
    script.write_text(_SEED_AND_SERVE, encoding="utf-8")
    info = tmp_path / "info.txt"
    perch_rig.serve(script, SERVER_DIR, info)
    for _ in range(80):
        if info.exists():
            break
        time.sleep(0.25)
    else:
        if _REQUIRED:
            pytest.fail(
                "server did not start under KORAX_BROWSER_REQUIRED=1 — "
                "where the leg is required, an unrunnable rig is a "
                "failure, not a skip (#1697)"
            )
        pytest.skip("server did not start; not a statement about the smoke")
    time.sleep(1.0)
    operator, token, port, probe_id, thread_root_id = info.read_text().splitlines()
    origin = f"http://127.0.0.1:{port}"

    chrome, cdp_port = perch_rig.chrome(
        CHROME, tmp_path / "chrome-profile")
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version",
                                    timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        pytest.fail("headless Chrome did not answer its CDP port")

    driver = subprocess.run(
        [NODE, str(DRIVER), str(cdp_port), origin, token, probe_id,
         thread_root_id],
        capture_output=True, text=True, timeout=240,
    )

    assert driver.stdout.strip(), (
        f"driver produced no report — stderr:\n{driver.stderr}"
    )
    report = json.loads(driver.stdout.strip().splitlines()[-1])

    assert not report["routeMismatch"], (
        f"the driver's ROUTES list has drifted from the shell's own nav — "
        f"nav now serves {report['navTabs']}; update ROUTES in "
        f"perch_smoke_driver.js to match before trusting this sweep"
    )

    # The general guard: no console error, no uncaught exception, anywhere,
    # on any route — the #1597 class's superset, not a known-identifier list.
    assert not report["errors"], (
        "console error(s) or uncaught exception(s) in a real browser:\n"
        + "\n".join(f"  [{e['where']}] {e['kind']}: {e['detail']}"
                     for e in report["errors"])
    )

    # A route that renders nothing exercises nothing (the brief's own
    # words) — and a route whose SECTION is wrong reports 0 here, so this
    # also asserts the router showed the right view.
    empty_warm = [h for h, value in report["routes"].items() if not value]
    assert not empty_warm, (
        f"these routes rendered empty (or the wrong section) on the warm "
        f"walk: {empty_warm}"
    )

    # JOB #1969 — the back button walks the history the routes pushed,
    # hash and visible section agreeing at every step.
    bad_back = [step for step in report["backTrail"] if not step["ok"]]
    assert not bad_back, (
        f"back-button traversal diverged from the pushed history: {bad_back}"
    )

    # JOB #1969 — a cold load of a deep link lands ON that view, loaded:
    # the URL is the state, from the first paint.
    empty_cold = [h for h, value in report["cold"].items() if not value]
    assert not empty_cold, (
        f"these routes failed as COLD deep-loads (blank or wrong section): "
        f"{empty_cold}"
    )

    # #1941's census: every markup-bound symbol reached through a real
    # click (or the render that carries it, for the two lexical ones),
    # judged by its effect.
    failed_census = sorted(k for k, v in report["census"].items() if not v)
    assert not failed_census, (
        f"census clicks whose effect did not land: {failed_census} — a "
        f"markup-bound symbol may have been stranded by a move (#1941)"
    )


def test_the_tabs_glob_is_nonempty() -> None:
    """A stopped glob fails loudly, per the brief — not the click-through's
    source of truth, but a sanity check on the split convention #1389 established:
    if this ever comes back empty, either the directory moved or the glob
    broke, and either way the smoke test above would silently be covering
    fewer files than it claims to.

    JOB #1927 CHANGED WHAT THIS GLOB IS WORTH: every tab now renders from
    a module in this directory, where before most rendered from
    index.html's inline block. An empty glob used to mean a weakened
    sanity check; it now means the perch has no tabs at all."""
    tabs = glob.glob(str(SERVER_DIR / "korax" / "perch" / "js" / "tabs" / "*.js"))
    assert tabs, (
        "server/korax/perch/js/tabs/*.js matched nothing — the split "
        "convention's own directory is either empty or has moved"
    )
