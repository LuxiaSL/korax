"""`why` is ONE contract with two implementations — JOB #2209, Shape 3.

`korax_cli/why.py` and `korax_mcp/why.py` are siblings, because these
clients share no runtime code by design (`clients/mcp` declares only
mcp/httpx/pydantic; each client is written against
`docs/korax-protocol.md`, never against the other). This is the same
trade `korax_mcp/backoff.py` documents and `test_backoff_contract.py`
enforces, and the same one `test_counter_contract.py` makes for the
§9.3 counters — whose docstring names the stake exactly: a fix applied
to one client "leaves the other manufacturing the same false claim
through a different door".

**That door is wide open for this verb in particular.** `why` exists to
stop an empty answer reading as absence. A client whose route table
silently lost a row would go on answering — confidently, in the
documented shape, with `routes_declared` still listing four names — and
be wrong in exactly the way the verb was built to prevent. So the
tables are asserted as LITERALS here, duplicated in the sibling file on
purpose: change one client's vocabulary and its test goes red against
constants the other still meets.

The literals below are the contract. They are not imported from either
module, because a test that read its expectations out of the code it
guards would pass through any change to that code.
"""

from __future__ import annotations

from korax_mcp import why

#: Every route, in emission order. Order is part of the contract: a
#: reader comparing two clients' output should not have to sort it.
ROUTES = (
    "inbound-edges",
    "closes-on-target",
    "attested-on-target",
    "sha-in-prose",
)

#: `verified` ONLY. `n/a` is the ABSENCE of grading (`validate.py:342-350`
#: resolves it for every ungraded nest — in `/korax-dev/issues` it is the
#: only grade an envelope can legally carry, across ~97 FINDINGs), and
#: `unverified` is what a delivery posts itself with. The mill measured
#: this and corrected it at #2242 before either client shipped.
ATTESTING_GRADES = {"verified"}

#: #2205's three rows, minus the graded-FINDING row which is a grade test
#: rather than an edge test. `invalidates` is deliberately absent: the
#: gavel has an open question at #2242 about widening this set, and a
#: client that ran ahead of the ruling would put its own opinion where a
#: ruling belongs, indistinguishably.
STATE_CHANGING = {"supersedes", "closes"}

#: STAMPs are caught on the EDGE, never in the grade field — `stamped` is
#: an effective grade and is not a member of the lattice.
STAMPING_EDGES = {"stamps"}

#: The three things a route can say about itself. Collapsing any two of
#: these is the defect (#2183 family A).
STATUSES = {"searched", "not-applicable", "bounded"}


def test_route_table_matches_the_contract() -> None:
    assert why.ROUTE_NAMES == ROUTES


def test_attesting_grades_match_the_contract() -> None:
    assert set(why.ATTESTING_GRADES) == ATTESTING_GRADES


def test_stamped_is_not_treated_as_a_grade() -> None:
    """It is not in the lattice, so a test against it could never fire —
    a dead branch reading as coverage of the most state-changing act on
    the board."""
    assert "stamped" not in why.ATTESTING_GRADES
    assert set(why.STAMPING_EDGES) == STAMPING_EDGES


def test_state_changing_set_matches_the_contract() -> None:
    assert set(why.STATE_CHANGING) == STATE_CHANGING


def test_every_route_reports_with_a_status_and_a_basis() -> None:
    """The shape both clients promise, exercised on an empty subject —
    the case where a lazier implementation would emit nothing at all."""
    subject = {"id": 1, "type": "NOTE", "ns": "/x", "author": "band:a", "grade": "n/a"}
    body = why.build(subject, [], {}, search_body=None, sha=None)

    assert [r["route"] for r in body["routes"]] == list(ROUTES)
    for report in body["routes"]:
        assert report["status"] in STATUSES
        assert report["basis"], f"{report['route']} emitted no basis"
        assert "count" in report


def test_the_answers_block_is_the_same_five_questions() -> None:
    subject = {"id": 1, "type": "NOTE", "ns": "/x", "author": "band:a", "grade": "n/a"}
    body = why.build(subject, [], {}, search_body=None, sha=None)
    assert set(body["answers"]) == {"gated", "disposed", "superseded", "stamped", "cited"}
    for answer in body["answers"].values():
        assert answer["from_routes"], "an answer must name the route it came from"


def test_drift_between_table_and_emission_raises() -> None:
    """The canary, asserted on this side too: the guard must exist in
    BOTH clients, not just in the one whose suite happened to grow it."""
    import pytest

    original = why.ROUTE_NAMES
    why.ROUTE_NAMES = original + ("unemitted",)
    try:
        with pytest.raises(AssertionError, match="route table drift"):
            why.build({"id": 1}, [], {}, search_body=None, sha=None)
    finally:
        why.ROUTE_NAMES = original


def test_an_intact_table_stays_quiet__control() -> None:
    """THE CONTROL for the canary above — a guard that raised
    unconditionally would pass it while making the verb unusable."""
    body = why.build({"id": 1}, [], {}, search_body=None, sha=None)
    assert [r["route"] for r in body["routes"]] == list(ROUTES)
