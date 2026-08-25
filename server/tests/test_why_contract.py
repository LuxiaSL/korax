"""`why`'s contract, held where the implementation now lives — JOB #3765.

This file replaces `clients/{mcp,cli}/tests/test_why_contract.py`, which
held the same literals twice because `why` was implemented twice.

**THE RATIONALE FOR HOLDING LITERALS SURVIVES THE MOVE; THE RATIONALE FOR
HOLDING THEM TWICE DOES NOT.** The client files argued two things: (a) a
test that read its expectations out of the code it guards would pass
through any change to that code, and (b) two sibling clients had to meet
one contract independently, so duplication was the mechanism. (a) is
still true and is why the tables below are literals rather than imports
of `why.ROUTE_NAMES`. (b) is now false by construction — there is one
implementation — so the duplication goes, and that is a REDUCTION in
coverage of exactly nothing: the second copy guarded a second
implementation that no longer exists.

(#3996 adopted the (a)/(b) distinction as property 2's boundary of
record while ruling on the neighbouring JOB. This is that boundary
applied to its own original instance.)
"""

from __future__ import annotations

import pytest

from korax import why as why_mod
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store
from korax.why import why

#: Every route, in emission order. Order is part of the contract: a
#: reader comparing two answers should not have to sort them.
ROUTES = (
    "inbound-edges",
    "closes-on-target",
    "attested-on-target",
    "sha-in-prose",
)

#: `verified` ONLY — `unverified` is what a delivery posts itself with
#: and `n/a` is the ABSENCE of grading, the only grade an envelope can
#: legally carry in an ungraded nest. Reading `!= unverified` as
#: attestation would label every FINDING in `/korax-dev/issues` as gated.
ATTESTING_GRADES = {"verified"}

#: #2205's rows. `invalidates` deliberately absent pending #2242.
STATE_CHANGING = {"supersedes", "closes"}

#: STAMPs are caught on the EDGE, never in the grade field.
STAMPING_EDGES = {"stamps"}

#: The three things a route can say about itself. Collapsing any two is
#: the defect (#2183 family A).
STATUSES = {"searched", "not-applicable", "bounded"}

#: Six, not five: `attested_on_targets` is the key JOB #3765 split out of
#: `gated`. A reader who wants what `gated` used to report reads it here.
ANSWER_KEYS = {
    "gated", "attested_on_targets", "disposed", "superseded", "stamped", "cited",
}


@pytest.fixture()
def board() -> Board:
    store = Store(":memory:")
    operator, _ = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    b = Board(store)
    seed_board(b, operator)
    return b


def test_route_table_matches_the_contract() -> None:
    assert why_mod.ROUTE_NAMES == ROUTES


def test_attesting_grades_match_the_contract() -> None:
    assert set(why_mod.ATTESTING_GRADES) == ATTESTING_GRADES


def test_stamped_is_not_treated_as_a_grade() -> None:
    """It is not in the lattice, so a test against it could never fire —
    a dead branch reading as coverage of the most state-changing act on
    the board."""
    assert "stamped" not in why_mod.ATTESTING_GRADES
    assert set(why_mod.STAMPING_EDGES) == STAMPING_EDGES


def test_state_changing_set_matches_the_contract() -> None:
    assert set(why_mod.STATE_CHANGING) == STATE_CHANGING


def test_every_route_reports_with_a_status_and_a_basis(board: Board) -> None:
    """The shape the reduction promises, exercised on a subject with no
    edges and no pointer — the case where a lazier implementation would
    emit nothing at all."""
    body = why(board.log, board.head, 1)
    assert [r["route"] for r in body["routes"]] == list(ROUTES)
    for report in body["routes"]:
        assert report["status"] in STATUSES
        assert report["basis"], f"{report['route']} emitted no basis"
        assert "count" in report


def test_the_answers_block_is_the_six_questions(board: Board) -> None:
    body = why(board.log, board.head, 1)
    assert set(body["answers"]) == ANSWER_KEYS
    for answer in body["answers"].values():
        assert answer["from_routes"], "an answer must name the routes it came from"


def test_drift_between_table_and_emission_raises(board: Board, monkeypatch) -> None:
    """The canary: a declared route that stops reporting must raise, not
    serve a short answer that looks complete."""
    monkeypatch.setattr(why_mod, "ROUTE_NAMES", why_mod.ROUTE_NAMES + ("unemitted",))
    with pytest.raises(AssertionError, match="route table drift"):
        why(board.log, board.head, 1)


def test_an_intact_table_stays_quiet__control(board: Board) -> None:
    """THE CONTROL for the canary above — a guard that raised
    unconditionally would pass it while making the verb unusable."""
    body = why(board.log, board.head, 1)
    assert [r["route"] for r in body["routes"]] == list(ROUTES)
