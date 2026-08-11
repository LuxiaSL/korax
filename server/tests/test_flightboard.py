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

PERCH = Path(__file__).resolve().parents[1] / "korax" / "perch.html"
MOCK = Path(__file__).resolve().parents[2] / "docs" / "mockups" / "korax-flightboard.html"
NODE = shutil.which("node")


def page() -> str:
    return PERCH.read_text(encoding="utf-8")


def script() -> str:
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", page(), re.S)
    assert blocks, "the perch serves no script block"
    return "\n".join(blocks)


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
    assert "flight: loadFlight" in source, "the tab is not wired to loadFlight"


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
    styles = re.search(r"<style>(.*?)</style>", page(), re.S)
    assert styles
    selectors = re.findall(r"^\s*(\.[a-zA-Z][\w-]*)", styles.group(1), re.M)
    flight = [s for s in selectors if "fb" in s]
    assert len(flight) >= 8, "the flightboard styles are missing"
    assert all(s.startswith(".fb-") for s in flight), (
        f"unprefixed flightboard selectors: {[s for s in flight if not s.startswith('.fb-')]}"
    )


def test_the_asks_section_renders_what_the_board_can_answer_and_names_what_it_cannot() -> None:
    """**The brief's data question, answered by measurement rather than guess.**

    The mock tracked ten operator asks to disposition. Measured at head: #967
    (the envelope the mock cites) is a desk FINDING of PROSE on the board nest,
    and `/korax/inbox` carries 0 human-authored OPENs — the inbox is where the
    flock asks the OPERATOR, the inverse of the obvious guess. So the operator's
    own asks have no structured home and cannot be tracked to disposition
    without parsing prose into rows.

    The section therefore renders `docket.escalated` — reduction-computed —
    and SAYS what it cannot show. This pins both halves, because a degraded
    section that stops admitting it is degraded is worse than one that never
    tried.
    """
    html, source = page(), script()
    assert "Waiting on you" in html, "the heading must not promise the mock's section"
    assert "d.escalated" in source, (
        "the section must render the reduction's answer, not a client-side "
        "re-derivation of which OPENs are closed"
    )
    assert 'There is no' in html and 'ask' in html
    assert "openEnvelope(967)" in html, (
        "the page must point at where the asks actually live, or the reader is "
        "told a section is empty without being told why"
    )


def test_no_client_side_recomputation_of_what_a_reduction_decides() -> None:
    """**The rule named at claim time**, asserted rather than promised: a
    wiring job invites recomputing open/taken/delivered from raw envelopes
    because a tile wants a number the docket does not quite give. That is the
    two-places defect this loop paid for five times.

    The page may READ envelopes for titles and prose. It must not decide
    status, grade or closure — those are the docket's.
    """
    fb = script().split("// -- the flightboard")[1].split("// -- ledger")[0]
    for forbidden in (".refs || []).some", 'edge === "closes"', "closedBy"):
        assert forbidden not in fb, (
            f"the flightboard computes {forbidden!r} — a second answer to a "
            "question `docket` already decides"
        )
