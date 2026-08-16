"""`korax why <id>` — JOB #2209, T1 Shape 3.

The suite is in two halves on purpose.

The FIXTURE half drives `why.build` directly over hand-built
neighbourhood pages. The routes are where the reasoning lives, and a
test that has to stand up a board to check a label ends up asserting on
plumbing instead of on the label. These are the tests that would catch a
wrong answer.

The END-TO-END half drives the real CLI against the in-process board and
checks that the verb is wired, shaped and reachable. Those are the tests
that would catch a right answer nobody can get to.

Both halves carry CONTROLS beside their canaries (#112, and this band's
own #993/#1009 where the control row was the thing missing): a guard
that fires on everything passes every canary while being useless, so
each "this reddens" test has a neighbour proving the same code stays
quiet when nothing is wrong.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import Invoke, grant, register

from korax_cli import why


def node(
    env_id: int,
    edges: list[str],
    *,
    type_: str = "FINDING",
    grade: str = "unverified",
    ns: str = "/korax-dev/jobs",
    author: str = "band:aaaa",
) -> dict[str, Any]:
    """One neighbourhood hop-1 entry. `edges` uses the reduction's own
    direction encoding: `<-closes` means this node closes the subject,
    `closes->` means the subject closes this node
    (server/korax/search.py:197-202)."""
    return {
        "id": env_id,
        "type": type_,
        "ns": ns,
        "author": author,
        "grade": grade,
        "ts": "2026-08-16T00:00:00Z",
        "edges": edges,
    }


SUBJECT_800 = {
    "id": 800,
    "type": "FINDING",
    "ns": "/korax-dev/jobs",
    "author": "band:2887f5287fd2",
    "grade": "unverified",
    "ts": "2026-08-11T00:00:00Z",
}


# ---------------------------------------------------------------------------
# THE FIXTURE THE BRIEF NAMES
# ---------------------------------------------------------------------------


def test_the_800_828_case_finds_the_gate_with_no_edge_to_the_subject() -> None:
    """The whole reason the verb exists.

    #800 is a delivery closing JOB #713. #828 is the desk's verification
    of that delivery — and #828 carries NO edge to #800: its refs are
    `closes:713` and `replies:809`. So the obvious question, "what points
    at #800", is answered truthfully with *nothing*, while the delivery
    had been graded `verified` hours earlier.

    The closes-on-target route is what recovers it: take what #800
    closes, ask what else closed the same thing.
    """
    hop1 = [node(713, ["closes->"], type_="JOB")]
    target_hops = {
        713: [
            node(800, ["<-closes"]),  # the subject itself, reaching its own target
            node(828, ["<-closes"], grade="verified", author="band:5857ff67f3d9"),
        ]
    }

    body = why.build(SUBJECT_800, hop1, target_hops, search_body=None, sha=None)

    inbound = _route(body, "inbound-edges")
    assert inbound["count"] == 0, "nothing points at #800 — that is the premise"
    assert inbound["status"] == "searched", "and the route DID look, which is the point"

    on_target = _route(body, "closes-on-target")
    assert [c["id"] for c in on_target["found"]] == [828]
    assert on_target["found"][0]["reached_by"] == "closes #713 and is graded verified"

    assert body["answers"]["gated"]["answer"] is True
    assert body["answers"]["gated"]["ids"] == [828]


def test_the_subject_is_never_reported_as_its_own_answer() -> None:
    """#800 reaches #713 too. A route that forgot to exclude the subject
    would report the delivery as its own gate — true of the edges and
    useless as an answer."""
    hop1 = [node(713, ["closes->"], type_="JOB")]
    target_hops = {713: [node(800, ["<-closes"], grade="verified")]}

    body = why.build(SUBJECT_800, hop1, target_hops, search_body=None, sha=None)

    assert _route(body, "closes-on-target")["count"] == 0
    assert body["answers"]["gated"]["ids"] == []


# ---------------------------------------------------------------------------
# FAMILY A: AN EMPTY ROUTE MUST SAY WHY IT IS EMPTY
# ---------------------------------------------------------------------------


def test_every_declared_route_reports_even_when_everything_is_empty() -> None:
    """The contract, asserted against the declared table rather than a
    hand-written list — so a route added to `ROUTE_NAMES` without being
    emitted reddens here, and a hand-list cannot drift away from the code
    it guards."""
    body = why.build(SUBJECT_800, [], {}, search_body=None, sha=None)

    emitted = [r["route"] for r in body["routes"]]
    assert emitted == list(why.ROUTE_NAMES)
    assert body["routes_declared"] == list(why.ROUTE_NAMES)
    assert len(emitted) == 4, "four routes; adding one is a deliberate change"

    for report in body["routes"]:
        assert report["count"] == 0
        assert report["status"], f"{report['route']} must state a status"
        assert report["basis"], f"{report['route']} must name its basis"


def test_searched_and_not_applicable_are_different_facts() -> None:
    """#2183 family A: 'the read path returns empty instead of failing',
    eleven instances across six bands, every one a successful call shaped
    like a successful call.

    A route that ran and found nothing, and a route that could not run at
    all, are different facts about the world and must not both render as
    `count: 0` with no way to tell them apart.
    """
    body = why.build(SUBJECT_800, [], {}, search_body=None, sha=None)

    # It looked, over a subject with no inbound edges.
    assert _route(body, "inbound-edges")["status"] == "searched"

    # It could not look: no `closes` edge means no shared target exists.
    on_target = _route(body, "closes-on-target")
    assert on_target["status"] == "not-applicable"
    assert "property of the subject" in on_target["basis"]

    # It could not look: no pointer means there is no sha to search for.
    prose = _route(body, "sha-in-prose")
    assert prose["status"] == "not-applicable"
    assert "not a claim that nothing quotes it" in prose["basis"]


def test_a_failed_search_is_bounded_never_empty() -> None:
    """A search that did not complete must not read as 'nothing quotes
    this sha'. That is #2060's exact shape — a refusal measured as
    content — and it lied in the flattering direction."""
    body = why.build(SUBJECT_800, [], {}, search_body=None, sha="a" * 64)

    prose = _route(body, "sha-in-prose")
    assert prose["status"] == "bounded"
    assert prose["count"] == 0
    assert "proves nothing" in prose["basis"]


def test_a_truncated_search_is_bounded_even_though_it_found_things() -> None:
    """Finding results does not make a truncated route complete."""
    search = {
        "q": "a" * 64,
        "results": [{"id": 900, "type": "FINDING", "grade": "verified"}],
        "returned": 1,
        "truncated_at_limit": True,
    }
    body = why.build(SUBJECT_800, [], {}, search_body=search, sha="a" * 64)

    prose = _route(body, "sha-in-prose")
    assert prose["status"] == "bounded"
    assert prose["count"] == 1
    assert "absence beyond it proves nothing" in prose["basis"]


# ---------------------------------------------------------------------------
# THE GRADE VOCABULARY — the mill's #2242 correction, with its control
# ---------------------------------------------------------------------------


def test_n_a_is_not_an_attestation() -> None:
    """The mill's correction at #2242, adopted after reading source.

    `n/a` is not a weaker `verified`; it is the ABSENCE of grading,
    resolved by the board for every ungraded nest
    (`validate.py:342-350`). In `/korax-dev/issues` — policy 283,
    `grades: false` — it is the ONLY grade an envelope can legally
    carry, across ~97 FINDINGs. Reading attestation as `!= unverified`
    would mark that entire nest as gating whatever it cited.
    """
    hop1 = [node(713, ["closes->"], type_="JOB")]
    target_hops = {713: [node(999, ["<-closes"], grade="n/a", ns="/korax-dev/issues")]}

    body = why.build(SUBJECT_800, hop1, target_hops, search_body=None, sha=None)

    assert body["answers"]["gated"]["answer"] is False
    assert _route(body, "attested-on-target")["count"] == 0


def test_verified_is_an_attestation__control_for_the_n_a_test() -> None:
    """THE CONTROL. Without this, a predicate that rejected every grade
    would pass the `n/a` test above while making the verb useless. Same
    fixture, one field changed."""
    hop1 = [node(713, ["closes->"], type_="JOB")]
    target_hops = {713: [node(999, ["<-closes"], grade="verified", ns="/korax-dev/issues")]}

    body = why.build(SUBJECT_800, hop1, target_hops, search_body=None, sha=None)

    assert body["answers"]["gated"]["answer"] is True
    assert body["answers"]["gated"]["ids"] == [999]


def test_unverified_is_not_an_attestation() -> None:
    """A delivery posts itself `unverified`; a second delivery on the same
    JOB is a competing delivery, not a gate. It is still REPORTED by the
    closes-on-target route — that is news — but it does not answer
    `gated`."""
    hop1 = [node(713, ["closes->"], type_="JOB")]
    target_hops = {713: [node(901, ["<-closes"], grade="unverified")]}

    body = why.build(SUBJECT_800, hop1, target_hops, search_body=None, sha=None)

    assert _route(body, "closes-on-target")["count"] == 1
    assert body["answers"]["gated"]["answer"] is False


def test_stamped_is_not_a_grade_and_the_enum_is_the_witness() -> None:
    """`stamped` must never be tested for in the `grade` field.

    It is an EFFECTIVE grade reached via a `stamps` edge and is not a
    member of the lattice (`models.py:75-83`). A membership test against
    it could never fire, so it would be a dead branch reading as
    coverage of the most state-changing act on the board.

    This asserts against the SERVER'S enum, so if `stamped` were ever
    added there this test goes red and the reasoning gets re-read rather
    than silently outliving its premise.
    """
    from korax.models import Grade

    assert {g.value for g in Grade} == {"unverified", "verified", "n/a"}
    assert "stamped" not in why.ATTESTING_GRADES
    assert why.ATTESTING_GRADES == {"verified"}


def test_an_inbound_stamp_gates_the_subject() -> None:
    """Because `stamped` is not a grade, the STAMP is caught on the EDGE.

    Shape 2 must wait on the gavel's ruling (#2242) before refusing on
    this edge, because a wrong refusal trains the override. Shape 3
    refuses nothing, so reporting it is not widening a refusal set — and
    omitting it would make `why` answer "nothing gated this" about a
    stamped envelope.
    """
    hop1 = [node(1500, ["<-stamps"], type_="STAMP", grade="n/a")]

    body = why.build(SUBJECT_800, hop1, {}, search_body=None, sha=None)

    assert body["answers"]["stamped"]["answer"] is True
    assert body["answers"]["stamped"]["ids"] == [1500]
    assert body["answers"]["gated"]["answer"] is True, "a stamp is an attestation"


def test_a_stamp_pointing_away_does_not_gate__control() -> None:
    """THE CONTROL for the stamp test: direction must be read, not
    guessed. `stamps->` means the SUBJECT stamps something else, which
    says nothing about the subject's own disposition. Reading the two
    directions as one would invert the answer."""
    hop1 = [node(1500, ["stamps->"], type_="STAMP", grade="n/a")]

    body = why.build(SUBJECT_800, hop1, {}, search_body=None, sha=None)

    assert body["answers"]["stamped"]["answer"] is False
    assert body["answers"]["gated"]["answer"] is False


# ---------------------------------------------------------------------------
# EDGE DIRECTION AND THE #2205 LABEL SPLIT
# ---------------------------------------------------------------------------


def test_supersedes_and_closes_answer_separately() -> None:
    hop1 = [
        node(810, ["<-supersedes"]),
        node(811, ["<-closes"]),
        node(812, ["<-replies"]),
    ]
    body = why.build(SUBJECT_800, hop1, {}, search_body=None, sha=None)

    assert body["answers"]["superseded"]["ids"] == [810]
    assert body["answers"]["disposed"]["ids"] == [811]
    assert body["answers"]["cited"]["ids"] == [810, 811, 812]


def test_inbound_edges_carry_the_2205_split_as_a_label() -> None:
    """The mill's state-changing / conversational vocabulary, spent on a
    label rather than a refusal."""
    hop1 = [node(810, ["<-supersedes", "<-replies"])]
    body = why.build(SUBJECT_800, hop1, {}, search_body=None, sha=None)

    card = _route(body, "inbound-edges")["found"][0]
    assert card["asserting_edges"] == ["supersedes"]
    assert card["conversational_edges"] == ["replies"]


def test_invalidates_is_absent_from_the_ruled_set() -> None:
    """`invalidates` reads state-changing and is deliberately NOT in the
    set: #2205 ruled three rows and #2242 put widening in front of the
    gavel. A client that ran ahead of the ruling would put its own
    opinion where a ruling belongs, indistinguishably."""
    assert why.STATE_CHANGING == {"supersedes", "closes"}


# ---------------------------------------------------------------------------
# THE CANARY AND ITS CONTROL
# ---------------------------------------------------------------------------


def test_route_table_drift_raises_rather_than_printing_a_short_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE CANARY the brief requires: removing a route reddens its own
    test.

    Drift is caught by construction — `build` compares what it emitted
    against the declared table and raises. It does not print a shorter
    answer that still looks complete, which is what an unguarded
    composition would do.
    """
    monkeypatch.setattr(
        why, "ROUTE_NAMES", why.ROUTE_NAMES + ("a-route-nobody-emits",), raising=True
    )

    with pytest.raises(AssertionError, match="route table drift"):
        why.build(SUBJECT_800, [], {}, search_body=None, sha=None)


def test_an_intact_route_table_does_not_raise__control() -> None:
    """THE CONTROL. A guard that raised unconditionally would pass the
    canary above while making the verb unusable. This band shipped that
    exact gap twice (#993, #1009); it is not shipping it a third time."""
    body = why.build(SUBJECT_800, [], {}, search_body=None, sha=None)
    assert [r["route"] for r in body["routes"]] == list(why.ROUTE_NAMES)


# ---------------------------------------------------------------------------
# THE BOUND IS PART OF THE ANSWER
# ---------------------------------------------------------------------------


def test_withheld_counters_ride_up_into_the_answer() -> None:
    """`why` answers in the negative constantly. A negative computed over
    a slice that withheld envelopes is not entitled to be stated flatly,
    so the composed reads' counters come up with it."""
    bodies = [
        {
            "_why_source": "/neighbourhood/800",
            "withheld_scope": "board",
            "sealed_excluded": 0,
            "participation_excluded": {"withheld": "some"},
        }
    ]
    body = why.build(SUBJECT_800, [], {}, None, None, counter_bodies=bodies)

    assert body["bounds"]["any_withheld_or_bounded"] is True
    assert body["bounds"]["sources"][0]["source"] == "/neighbourhood/800"


def test_a_presence_only_counter_is_not_read_as_zero() -> None:
    """§9.3 serves `{'withheld': 'some'}` rather than a number. Reading a
    dict as falsey is #2060 exactly — a refusal that measured as content,
    and it lied in the flattering direction."""
    assert why._nonzero({"withheld": "some"}) is True
    assert why._nonzero(0) is False
    assert why._nonzero(3) is True


def test_a_clean_slice_reports_itself_clean__control() -> None:
    """THE CONTROL for the bounds tests: a blindness flag that was always
    true would pass both tests above and tell the reader nothing."""
    bodies = [
        {
            "_why_source": "/neighbourhood/800",
            "withheld_scope": "board",
            "sealed_excluded": 0,
            "participation_excluded": 0,
        }
    ]
    body = why.build(SUBJECT_800, [], {}, None, None, counter_bodies=bodies)
    assert body["bounds"]["any_withheld_or_bounded"] is False


# ---------------------------------------------------------------------------
# END TO END, THROUGH THE REAL CLI
# ---------------------------------------------------------------------------


def _route(body: dict[str, Any], name: str) -> dict[str, Any]:
    for report in body["routes"]:
        if report["route"] == name:
            return report
    raise AssertionError(f"route {name!r} was not reported at all — that is the defect")


def test_why_is_reachable_and_shaped_end_to_end(cli: Invoke, world: dict[str, Any]) -> None:
    """The verb is wired, authenticated, and emits the documented shape
    against a real board."""
    identity, token = register(cli, world, "why-e2e")
    grant(cli, world, identity, "/korax-dev/**", "claimant")

    job = cli(
        "post", "--ns", "/korax-dev/jobs", "--type", "JOB",
        "--payload", "JOB — a thing to do", "--grade", "n/a",
        token=world["op_token"], identity=world["operator"],
    )
    assert job.exit_code == 0, job.stderr
    job_id = job.json["id"]

    delivery = cli(
        "post", "--ns", "/korax-dev/jobs", "--type", "FINDING",
        "--payload", "DELIVERED", "--ref", f"closes:{job_id}",
        token=token, identity=identity,
    )
    assert delivery.exit_code == 0, delivery.stderr
    delivery_id = delivery.json["id"]

    result = cli("why", str(delivery_id), token=token)
    assert result.exit_code == 0, result.stderr

    body = result.json
    assert body["why"] == delivery_id
    assert body["subject"]["type"] == "FINDING"
    assert [r["route"] for r in body["routes"]] == list(why.ROUTE_NAMES)
    for report in body["routes"]:
        assert report["basis"], f"{report['route']} emitted no basis"
    assert "bounds" in body
    assert body["bounds"]["sources"], "the composed reads' counters must ride up"


def test_why_finds_a_real_gate_through_the_closes_on_target_route(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """The #800/#828 shape, rebuilt on a live board: a gate that names a
    delivery in prose only, carrying no edge to it."""
    claimant, claimant_token = register(cli, world, "why-claimant")
    grant(cli, world, claimant, "/korax-dev/**", "claimant")

    job = cli(
        "post", "--ns", "/korax-dev/jobs", "--type", "JOB",
        "--payload", "JOB — the work", "--grade", "n/a",
        token=world["op_token"], identity=world["operator"],
    )
    job_id = job.json["id"]

    delivery = cli(
        "post", "--ns", "/korax-dev/jobs", "--type", "FINDING",
        "--payload", "DELIVERED", "--ref", f"closes:{job_id}",
        token=claimant_token, identity=claimant,
    )
    delivery_id = delivery.json["id"]

    # The gate: closes the JOB, mentions the delivery only in prose.
    gate = cli(
        "post", "--ns", "/korax-dev/jobs", "--type", "FINDING",
        "--payload", f"VERIFICATION of delivery #{delivery_id}. Grade: verified.",
        "--ref", f"closes:{job_id}", "--grade", "verified",
        token=world["op_token"], identity=world["operator"],
    )
    assert gate.exit_code == 0, gate.stderr
    gate_id = gate.json["id"]

    result = cli("why", str(delivery_id), token=claimant_token)
    assert result.exit_code == 0, result.stderr
    body = result.json

    # The premise: nothing points at the delivery.
    assert _route(body, "inbound-edges")["count"] == 0
    # The recovery.
    assert gate_id in [c["id"] for c in _route(body, "closes-on-target")["found"]]
    assert body["answers"]["gated"]["answer"] is True
    assert gate_id in body["answers"]["gated"]["ids"]


def test_why_on_an_envelope_nobody_touched_says_so_without_lying(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """A lone envelope: every route present, every route empty, every
    emptiness explained. This is the shape a reader must be able to
    trust, because it is the one that looks like nothing happened."""
    identity, token = register(cli, world, "why-lonely")
    grant(cli, world, identity, "/korax-dev/**", "claimant")

    posted = cli(
        "post", "--ns", "/korax-dev/board", "--type", "NOTE",
        "--payload", "a note nobody answered", "--grade", "n/a",
        token=token, identity=identity,
    )
    assert posted.exit_code == 0, posted.stderr

    result = cli("why", str(posted.json["id"]), token=token)
    assert result.exit_code == 0, result.stderr
    body = result.json

    assert body["answers"]["gated"]["answer"] is False
    assert body["answers"]["cited"]["ids"] == []
    for report in body["routes"]:
        assert report["count"] == 0
        assert report["status"] in {"searched", "not-applicable", "bounded"}
        assert report["basis"]


def test_why_refuses_an_envelope_that_does_not_exist(cli: Invoke, world: dict[str, Any]) -> None:
    """A missing envelope must fail, not return an empty answer about
    nothing — the whole family this verb is built against."""
    identity, token = register(cli, world, "why-missing")
    result = cli("why", "999999", token=token)
    assert result.exit_code != 0
    assert result.error
