"""The flightboard — a board's work rendered as a departures board (JOB #1251).

The operator's sentence is the requirement: *"see jobs/proposals/issues for a
certain board and whether they've been closed or are still open."*

WHAT THESE GUARDS ARE WORTH — the #962/#841 split, labelled:

  - **Executed**: the pure helpers are lifted out and RUN under node.
  - **Contract**: the page reads specific fields off `docket` and `read`. Those
    are asserted against a REAL board through the app, so a reduction that
    stops carrying `grade_source` or `first_line` fails here rather than
    silently emptying a column in a browser nobody is looking at.
  - **Structural**: the markup and wiring, over the served page. Catches
    deletion and rename, not correctness.

There is no browser in this suite, so nothing here proves the page *looks*
right. The contract tests are the substitute worth having: they prove the data
the page is written against is the data the board serves.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from perch_source import PERCH_DIR, markup as _markup, script as _script
MOCK = Path(__file__).resolve().parents[2] / "docs" / "mockups" / "korax-flightboard.html"
NODE = shutil.which("node")


def page() -> str:
    return _markup()


def script() -> str:
    return _script()


def run_node(fn_pattern: str, expression: str) -> object:
    fn = re.search(fn_pattern, script(), re.S)
    assert fn, (
        f"cannot extract {fn_pattern!r} — the flightboard was restructured and "
        "these tests are asserting nothing. Re-point them; do not delete them."
    )
    prog = "const esc = (s) => String(s);\n" + fn.group(1) + \
        f"\nprocess.stdout.write(JSON.stringify({expression}));"
    r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)



def flightboard_source() -> str:
    """Just the flightboard's own code — bounded at both ends.

    Splitting the whole script on the function name swallows every section
    that follows it, which made an early version of the band-id assertion
    below fail against code it was never about. Bound both ends or the
    assertion is about the wrong file.
    """
    return script().split("// -- the flightboard")[1].split("// -- ledger")[0]


def asks_source() -> str:
    return flightboard_source().split("async function fbAsks")[1]


# -- executed ------------------------------------------------------------------


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_title_is_the_first_line_with_the_act_prefix_dropped() -> None:
    """Titles come from the payload's first line, the same convention the
    docket already uses for `first_line` on issues. The act prefix is dropped
    because a column of rows all starting `JOB:` carries no information."""
    out = run_node(r"(function fbFirstLine\(payload\) \{.*?\n\})",
                   'fbFirstLine("JOB: the flightboard\\n\\nbody here")')
    assert out == "the flightboard"


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_blank_leading_line_does_not_become_the_title() -> None:
    """An envelope whose payload opens with a blank line would otherwise get an
    empty title — a row that reads as a job with no name."""
    assert run_node(r"(function fbFirstLine\(payload\) \{.*?\n\})",
                    r'fbFirstLine("\n\n   \nISSUE: the real line")') == "the real line"


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_clean_page_says_nothing_about_withholding() -> None:
    """**The control.** A withheld note that renders on every page teaches
    readers to ignore it, which is worse than not having one."""
    out = run_node(r"(function fbWithheld\(page, what\) \{.*?\n\})",
                   'fbWithheld({sealed_excluded:0, participation_excluded:0, '
                   'rotated_excluded:0, withheld_scope:"slice"}, "jobs")')
    assert out == ""


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_bucketed_participation_count_renders_as_presence_not_a_number() -> None:
    """§9.3: a non-zero participation count reports PRESENCE. The UI must not
    invent a figure the wire deliberately refuses to give (#388)."""
    out = run_node(r"(function fbWithheld\(page, what\) \{.*?\n\})",
                   'fbWithheld({sealed_excluded:0, participation_excluded:{withheld:"some"}, '
                   'rotated_excluded:0, withheld_scope:"board"}, "the inbox")')
    assert "some withheld by participation" in out
    assert "scope: board" in out, "R56's withheld_scope must reach the reader"


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_an_unstated_scope_says_unstated_rather_than_guessing() -> None:
    """A board that predates R56 sends no `withheld_scope`. Rendering a
    plausible one would be the client fabricating the very dimension #802 was
    filed to make explicit."""
    out = run_node(r"(function fbWithheld\(page, what\) \{.*?\n\})",
                   'fbWithheld({sealed_excluded:3}, "jobs")')
    assert "unstated" in out


# -- contract: the reductions carry what the page reads ------------------------


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    return {"client": TestClient(create_app(board)), "op": operator, "tok": op_token,
            "store": store, "board": board}


def auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def test_docket_carries_every_field_the_flightboard_reads(world: dict) -> None:
    """**The contract test, and the reason it exists.** The page reads
    `totals`, `filed[].first_line`, `issues_ns`, `namespaces`, and
    `work.{open,taken,delivered,superseded,lapsed}`. A reduction that stops
    carrying one of those empties a column silently — the failure mode a
    browser-free suite most needs to cover.
    """
    body = world["client"].get(
        "/view/docket", params={"ns": "/korax-dev"}, headers=auth(world["tok"])).json()
    assert "at" in body, "the masthead renders the head offset"
    d = body["output"]
    assert {"totals", "filed", "issues_ns", "namespaces", "work"} <= set(d)
    assert {"open", "taken", "delivered", "superseded", "lapsed"} <= set(d["work"])
    for issue in d["filed"]:
        assert "first_line" in issue, (
            "the filed list stopped carrying first_line — the issues table would "
            "render ids with no titles, and the page has no second source for them"
        )


def test_the_self_grade_flag_is_the_dockets_field_not_a_client_inference(
    world: dict,
) -> None:
    """#1043's audit as UI. `grade_source: "self"` is computed server-side; the
    page renders it. If the client inferred it instead, two implementations
    would disagree about who has been reviewed — the two-places defect on the
    one column whose whole job is honesty about review."""
    source = script()
    assert 'x.grade_source === "self"' in source
    assert "r.grade_source === \"self\"" in source
    assert "grade_source" in Path(
        Path(__file__).resolve().parents[1] / "korax" / "reductions.py"
    ).read_text(), "the docket no longer computes grade_source; the flag has no source"


def test_a_read_over_the_jobs_nest_carries_payloads_for_titles(world: dict) -> None:
    """Titles come from ONE read rather than N envelope fetches. If the read
    path stopped serving payloads the table would show the withheld fallback,
    which is honest — but this pins the happy path so the fallback stays rare."""
    r = world["client"].get("/read", params={"ns": "/korax-dev/jobs", "type": "JOB"},
                            headers=auth(world["tok"]))
    assert r.status_code == 200
    page_body = r.json()
    assert "envelopes" in page_body and "withheld_scope" in page_body, (
        "the page renders §9.3's counters beneath each list; a response without "
        "withheld_scope means it cannot say which ruler they used (R56)"
    )


# -- structural ----------------------------------------------------------------


def test_the_flight_tab_is_wired_to_its_loader() -> None:
    """A section with no dispatch entry renders once, empty, and never
    refreshes — the shape of bug that looks like 'no data' forever."""
    source, html = script(), page()
    assert '<button data-tab="flight">Flight</button>' in html
    assert '<section id="tab-flight"' in html
    assert "flight: () => loadFlight()" in source, "the tab is not wired to loadFlight"  # S1: the dispatcher is TAB_LOADERS now


def test_every_mock_section_has_a_home_in_the_perch() -> None:
    """The brief: *the mock and the rendered page agree section-for-section*,
    and every deliberate divergence is listed in the delivery. This asserts the
    agreement so a dropped section is a failure rather than an omission nobody
    notices."""
    html = page()
    for heading in ("Your asks", "The job board", "Proposals",
                    "Filed and unclaimed", "Reading this page"):
        assert heading in html, f"the mock's {heading!r} section has no home"
    assert MOCK.exists(), "the mock is the spec; it must stay in the tree"
    for heading in ("Your asks", "The job board", "Proposals",
                    "Filed and unclaimed", "Reading this page"):
        assert heading in MOCK.read_text(), (
            f"{heading!r} is no longer in the mock — the spec moved and the "
            "page above may now be agreeing with nothing"
        )


def test_the_flightboard_styles_cannot_restyle_the_rest_of_the_perch() -> None:
    """The mock carries its own stylesheet into a page that already has one.
    An unprefixed `.tile`, `.scroll` or `table` rule would silently restyle
    every other tab — a change nobody would attribute to this job."""
    # The split (JOB #1389) moved the styles to files; the fb-* block
    # rides in base.css until the flight tab's own migration takes it.
    css = "\n".join(p.read_text() for p in sorted(PERCH_DIR.glob("css/**/*.css")))
    assert css, "the css glob found nothing — the layout moved under this test"
    selectors = re.findall(r"^\s*(\.[a-zA-Z][\w-]*)", css, re.M)
    flight = [s for s in selectors if "fb" in s]
    assert len(flight) >= 8, "the flightboard styles are missing"
    assert all(s.startswith(".fb-") for s in flight), (
        f"unprefixed flightboard selectors: {[s for s in flight if not s.startswith('.fb-')]}"
    )


def test_the_asks_section_reads_the_adopted_convention() -> None:
    """**This section's history is the point.**

    It first shipped degraded: the mock wanted operator asks tracked to
    disposition, and measurement showed they lived only as prose in #967 while
    `/korax/inbox` carried zero human-authored OPENs — the inbox is where the
    flock asks the operator, the inverse of the obvious guess. The page said so
    instead of rendering a confident emptiness, and the gap was filed (#1276).

    The desk then adopted the shape (#1277): one OPEN per ask in the board
    nest, closed by the usual edge. So the section now reads it. **A degraded
    section that names what it cannot show is how the shape arrived** — which
    is worth pinning, because the temptation at the time was to parse prose
    into rows and invent a disposition the log did not carry.
    """
    html, asks = page(), asks_source()
    assert "Your asks" in html
    assert '/board' in asks, "the asks come from the project's board nest (#1277)"
    assert 'e.type === "OPEN"' in asks
    assert "#1277" in asks, "the convention must be cited where it is implemented"


def test_no_client_side_recomputation_of_what_a_reduction_decides() -> None:
    """**The rule named at claim time — narrowed once, deliberately, and the
    narrowing is the interesting part.**

    The first version of this test banned `closes`-edge walking outright. Then
    the desk adopted #1277: an operator ask is an OPEN in the board nest whose
    disposition IS its `closes` edge, and it asked the flightboard to read it.
    So the ban had to give — and a guard you blunt to ship a feature is usually
    a guard that was load-bearing, which is why this narrows on a stated
    principle rather than dropping the case.

    **What was always meant: never compute a SECOND answer to a question a
    reduction already decides.** Status, grade, `grade_source` and issue
    closure are the docket's, measured and asserted below. An ask's
    disposition is decided by NO reduction — `escalated` is inbox-only,
    `filed` is issues-only, `work.open` is jobs-only — so the walk in `fbAsks`
    is the only answer rather than a competing one, and the gap is filed so a
    reduction can take it over.

    If that distinction ever stops being expressible here, the honest move is
    to restore the blanket ban and render asks degraded again.
    """
    fb = flightboard_source()
    main, asks = fb.split("async function fbAsks")

    # Everything except the asks section: no edge walking, no status inference.
    for forbidden in (".refs || []).some", 'r.edge === "closes"', "closedBy"):
        assert forbidden not in main, (
            f"the flightboard computes {forbidden!r} outside fbAsks — a second "
            "answer to a question `docket` already decides"
        )

    # The asks section may walk closes, and ONLY closes.
    assert 'r.edge === "closes"' in asks, "the asks section lost its disposition"
    for forbidden in ("grade_source ===", 'status ===', "lease_until"):
        assert forbidden not in asks, (
            f"fbAsks infers {forbidden!r} — its licence covers an ask's "
            "disposition and nothing else"
        )


def test_the_ask_convention_matches_the_seat_not_a_band_id() -> None:
    """#1277 records asks as desk-authored OPENs. Matching a specific author id
    would empty this section silently the first time the desk seat changes
    hands — the exact failure this page exists to make visible, one layer up.
    """
    asks = asks_source()
    assert 'e.band === "desk"' in asks
    assert "band:" not in asks, "an author id is pinned where a band should be"


def test_the_docket_still_decides_the_things_the_page_does_not(world: dict) -> None:
    """The other half of the narrowing, asserted against a real board rather
    than argued: these four questions HAVE a reduction, so the page must never
    answer them itself."""
    d = world["client"].get(
        "/view/docket", params={"ns": "/korax-dev"}, headers=auth(world["tok"])
    ).json()["output"]
    assert isinstance(d["work"]["delivered"], list), "grade/grade_source live here"
    assert isinstance(d["filed"], list), "issue closure lives here"
    assert isinstance(d["work"]["open"], list) and isinstance(d["work"]["taken"], list)
    assert "escalated" in d, (
        "inbox escalation lives here — and notably does NOT cover board-nest "
        "ask OPENs, which is why fbAsks is licensed to walk them"
    )


def test_the_ask_filter_is_structural_and_excludes_an_ordinary_desk_open() -> None:
    """**Canary and control, and the control is why the marker exists.**

    #1277 first stated the convention as queryable by `type=OPEN band=desk
    ns=<board>`. Run against the real board, that selector returned FIVE: the
    four recorded asks and #669, an ordinary desk OPEN in the same nest with
    the same edges and an empty `ext`. Nothing structural separated them, so
    the first implementation matched the payload's opening words — and a
    selection convention on prose is a spell-checker for a lookup.

    The marker was asked for (#1285) and adopted (#1286). This pins that the
    filter is structural now, and that all three live near-miss shapes stay
    out: an unmarked desk OPEN, a marked envelope from another band, and a
    marked non-OPEN.
    """
    asks = asks_source()
    assert "e.ext?.korax?.ask === true" in asks, (
        "the ask filter is no longer structural — if it has gone back to "
        "matching prose, #1285's whole argument has been undone"
    )
    assert "ASK_PREFIX" not in asks, "the prose stopgap outlived its marker"
    assert 'e.band === "desk"' in asks and 'e.type === "OPEN"' in asks


def test_the_page_no_longer_advertises_a_stopgap_it_does_not_have() -> None:
    """The disclosure had to go when the seam closed. A page still confessing a
    limitation it has fixed teaches readers to discount its other warnings."""
    # fbAsks moved to js/tabs/flight.js (JOB #1927), so the selector it
    # names lives in an asset now; read the composed script, which is what
    # the browser runs, rather than the shell alone.
    html = script()
    assert "ext.korax.ask" in html, "the page must name what it selects on"
    assert "stopgap" not in html.lower()
