"""ISSUE #2995, product half — the handlers tolerate a failed boot.

#2997 §2 is the binding acceptance: *the handlers tolerate a failed boot
observably; removing the fetch flake without that is symptom-removal and
does not close this ISSUE.* So the fetch flake is deliberately NOT fixed
here and stays #2897-family — this file asserts only that a page whose
boot failed dies politely instead of throwing.

TWO INSTRUMENTS, BECAUSE THEY GUARD DIFFERENT THINGS.

`test_no_post_body_names_ME_identity` is a SEAM test over the source: it
guards the FORM, and it is the one that catches the tenth site. Nine
hand-applied guards would be the same rule enforced by remembering, which
is exactly the shape that produced this defect — three of ten handlers
already guarded, in the right form, and nobody could see that the other
seven did not.

**It checks an ABSENCE, not a guard's presence, and that is deliberate.**
I first wrote the presence version as a regex classifier and it was wrong
in the flattering direction: it counted `ME &&` inside a `.filter()` as a
guard and mis-attributed two event-listener callbacks to the named
functions above them, reporting seven unguarded sites where there were
nine. Static scope analysis of JS in a regex is a thing that looks like it
works. `author: ME.identity` appearing nowhere is decidable by reading
bytes, cannot be fooled by scope, and has exactly one correct spelling.

The browser test guards the BEHAVIOUR, which no source read can: that the
handler returns and toasts rather than throwing. `perch_null_boot_driver.js`
carries the argument for why nothing in it may catch.
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
PERCH = SERVER_DIR / "korax" / "perch"
DRIVER = Path(__file__).with_name("perch_null_boot_driver.js")

CHROME = (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
          or shutil.which("chromium") or shutil.which("chromium-browser"))
NODE = shutil.which("node")
_SKIP_REASON = (
    "no headless Chrome found" if not CHROME else
    "no `node` found" if not NODE else None
)

# The banned spelling. A post body naming `ME.identity` as its author is
# the defect; `requireMe(...)` then `me.identity` is the repair.
_BANNED = "author: ME.identity"


def _perch_sources() -> list[Path]:
    return sorted([*PERCH.rglob("*.js"), *PERCH.rglob("*.html")])


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Lines that are not whole-line comments.

    A test that greps for a string matches the prose describing it — this
    file's own module docstring and `plumbing.js`'s comment block both
    name the banned spelling in order to explain it. Whole-line comments
    are skipped so documenting the rule does not break it. A trailing
    comment carrying the pattern would still trip: stated as a known
    limit, and cheaper than parsing JS to be sure.
    """
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("<!--"):
            continue
        out.append((n, line))
    return out


def test_no_post_body_names_ME_identity() -> None:
    """The seam: the tenth handler fails here rather than in production."""
    offenders = [
        f"{p.relative_to(PERCH)}:{n}"
        for p in _perch_sources()
        for n, line in _code_lines(p)
        if _BANNED in line
    ]
    assert not offenders, (
        "a post body composed `author: ME.identity`, which throws an uncaught "
        "TypeError on any page whose boot failed (ISSUE #2995). Use "
        "`const me = requireMe(\"<what>\"); if (!me) return;` and then "
        f"`author: me.identity`. Sites: {offenders}"
    )


def test_the_seam_test_can_actually_fail() -> None:
    """The canary's own red-check — a guard that cannot fail is not one.

    #3182/#3247: this board struck two acceptance items this loop for
    passing on the broken code. This asserts the detector fires on the
    exact string it exists to catch, so a future refactor that quietly
    breaks `_code_lines` cannot leave `test_no_post_body_names_ME_identity`
    green over a reintroduced defect.
    """
    planted = [(1, f'    proto: "korax/0.1", {_BANNED}, ns,')]
    assert any(_BANNED in line for _, line in planted)
    # and the comment-skipping does not swallow a real line
    assert [n for n, line in planted if _BANNED in line] == [1]


def test_requireMe_exists_and_is_the_single_guard() -> None:
    """One helper, defined once, in the file that owns the client half."""
    plumbing = (PERCH / "js" / "plumbing.js").read_text(encoding="utf-8")
    assert "function requireMe(" in plumbing, (
        "the guard lives in plumbing.js — the header says the protocol's "
        "client half lives there and nowhere else"
    )
    defs = [
        f"{p.relative_to(PERCH)}"
        for p in _perch_sources()
        if "function requireMe(" in p.read_text(encoding="utf-8")
    ]
    assert defs == ["js/plumbing.js"], (
        f"requireMe must be defined exactly once; found in {defs}"
    )


def test_every_post_composing_file_guards_before_it_composes() -> None:
    """Every file composing `author: me.identity` also calls requireMe.

    Weaker than scope analysis on purpose — see the module docstring for
    why the scope-analysing version was wrong. This catches the file-level
    mistake (a site converted to `me.identity` with no guard added), which
    is the one a hand edit actually makes; the browser test catches the
    rest.
    """
    for p in _perch_sources():
        text = p.read_text(encoding="utf-8")
        if "author: me.identity" in text:
            assert "requireMe(" in text, (
                f"{p.relative_to(PERCH)} composes a post from `me.identity` "
                "but never calls requireMe — `me` is unbound or unguarded"
            )


_SEED_AND_SERVE = """
import socket, sys
sys.path.insert(0, sys.argv[1])
import uvicorn
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

store = Store(":memory:")
operator, op_tok = store.create_identity("operator")
store.set_meta("genesis_identity", operator)
board = Board(store)
seed_board(board, operator)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
open(sys.argv[2], "w").write(f"{operator}\\n{op_tok}\\n{port}\\n")
uvicorn.Server(uvicorn.Config(create_app(board), log_level="error")).run(
    sockets=[sock])
"""


@pytest.mark.browser
@pytest.mark.skipif(bool(_SKIP_REASON), reason=str(_SKIP_REASON))
def test_a_failed_boot_leaves_every_handler_polite(tmp_path, perch_rig) -> None:
    """#2997 §2's acceptance, driven in a real browser.

    The boot failure is FORCED, not raced: #2995 observed it at 2-of-5
    under 2-CPU pinning, and a test that waited for that would be the
    flake it documents. Overriding fetch for /whoami reproduces the state
    the race produces.
    """
    script = tmp_path / "serve.py"
    script.write_text(_SEED_AND_SERVE, encoding="utf-8")
    info = tmp_path / "info.txt"
    perch_rig.serve(script, SERVER_DIR, info)
    for _ in range(80):
        if info.exists():
            break
        time.sleep(0.25)
    else:
        pytest.skip("server did not start; not a statement about the guard")
    time.sleep(1.0)
    _operator, token, port = info.read_text().splitlines()
    origin = f"http://127.0.0.1:{port}"

    _chrome, cdp_port = perch_rig.chrome(CHROME, tmp_path / "chrome-profile")
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list")
            break
        except Exception:
            time.sleep(0.25)

    run = subprocess.run(
        [NODE, str(DRIVER), str(cdp_port), origin, token],
        capture_output=True, text=True, timeout=180)
    report = json.loads(run.stdout or "{}")

    steps = report.get("steps", {})
    probes = report.get("probes", {})
    assert steps.get("booted_normally") is True, f"rig did not boot: {report}"
    assert steps.get("me_is_null") is True, (
        f"the forced boot failure did not leave ME null — the probe measured "
        f"nothing: {report}")
    assert steps.get("who_says_boot_failed") is True, f"{report}"

    # The half deliberately left open (#2997 §2). Its PRESENCE is asserted so
    # that a future fetch fix cannot silently turn this test into a claim
    # about a defect it never covered.
    assert steps.get("boot_console_error_present") is True, (
        "boot's own console.error is the fetch flake and stays open — if it "
        f"is gone, this test's premise changed: {report}")

    threw = {n: p for n, p in probes.items() if p.get("threw")}
    assert not threw, (
        "handlers threw an uncaught exception after a failed boot — this is "
        f"#2995's null-deref: {threw}")

    silent = {n: p for n, p in probes.items()
              if not (p.get("toast_shown") and p.get("toast_names_identity"))}
    assert not silent, (
        "handlers returned without telling the operator why — #2997 §2 "
        f"requires the tolerance be OBSERVABLE, not silent: {silent}")

    assert run.returncode == 0, f"driver reported failure: {report}"
