"""§14 / §5 — the served `edge_rules` matrix tells the truth about every edge.

JOB #1093, issue #511. `/conformance` serves `edge_rules` so a client can
pre-flight an edge without guessing, and the contract says a missing key
means that side is UNCONSTRAINED. `supersedes` is constrained by a RELATION
— same act, or SUPERSEDE-carrier to anything — and the schema has slots for
two independent sets and none for a correspondence. So a real rule
serialised as `{}`, which the contract reads as "no rule".

Two bands consulted the matrix properly, concluded a PROPOSAL may supersede
a SUPERSEDE, and were refused (#502/#509). **Guessing from §5 would have
produced the right answer; consulting the endpoint produced the wrong one.**
A conformance surface that punishes correct method is worse than no surface,
because anything pre-validating against it admits illegal edges silently.

WHY THIS IS A PRODUCT AND NOT A HANDFUL OF CASES
------------------------------------------------
Cairn checked exactly one edge — the one that refused them — and said so.
Every other `{}` was unaudited, and nobody knew which carried relation-shaped
rules. The sweep below answers that for all of them at once, and keeps
answering it: **it is the thing that catches the next relation-shaped
constraint at the commit that adds it, rather than at the band it burns.**

THE TRAP THIS FILE IS WRITTEN AGAINST
--------------------------------------
The lazy version of this test asks the validator what it refuses and asserts
the matrix says the same — a matrix generated from the validator, checked
against the validator, agreeing by construction. That is a very thorough
mirror and it cannot fail.

So the test drives the **validator's actual behaviour** (`_check_edge_types`,
the function `/post` calls) and compares it against the **served matrix**
(what `/conformance` emits over HTTP). A rule added to the validator in code
rather than through the shared constants makes those two disagree, and this
goes red. That is the only arrangement in which the canary is load-bearing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.models import Act, EdgeType, Envelope
from korax.store import Store
from korax.validate import PostError, Submission, _check_edge_types

#: Refusals raised by the per-ref loop — the layer `edge_rules` describes.
#: Act-shape rules (§4: "SUPERSEDE requires exactly 1 supersedes edge") live
#: in the same function but are a different contract and are NOT this
#: matrix's job; distinguishing them is why this matches on message rather
#: than on "did it raise".
EDGE_LAYER_REFUSALS = (
    "may not originate from",
    "may not target",
    "may not supersede",
)


@pytest.fixture(scope="module")
def served() -> dict:
    """`edge_rules` as a client actually receives it, over HTTP."""
    client = TestClient(create_app(Board(Store(":memory:"))))
    return client.get("/conformance").json()["edge_rules"]


def _target(act: Act) -> Envelope:
    return Envelope.model_validate({
        "proto": PROTO, "id": 1, "ts": "2026-01-01T00:00:00Z",
        "author": "band:t", "band": "warner", "ns": "/x",
        "type": act.value, "grade": "n/a", "refs": [], "ext": {},
    })


def validator_refuses(src: Act, edge: EdgeType, tgt: Act) -> str | None:
    """The real refusal, from the function `/post` calls."""
    sub = Submission(proto=PROTO, author="band:t", ns="/x", type=src,
                     refs=({"edge": edge.value, "id": 1},))
    try:
        _check_edge_types(sub, {1: _target(tgt)})
    except PostError as exc:
        if any(k in exc.message for k in EDGE_LAYER_REFUSALS):
            return exc.message
    return None


def matrix_admits(rule: dict, src: Act, edge: EdgeType, tgt: Act) -> bool:
    """Read the served entry exactly as the documented contract says to.

    This deliberately mirrors what a CLIENT would implement from the spec —
    absent key means unconstrained — because the bug being guarded is that a
    correct reading of the served bytes produced a wrong answer.
    """
    sources = rule.get("sources")
    if sources is not None and src.value not in sources:
        return False
    targets = rule.get("targets")
    if targets is not None and tgt.value not in targets:
        return False
    if rule.get("same_act"):
        exempt = rule.get("source_exempt", [])
        if src.value not in exempt and tgt != src:
            return False
    return True


def test_the_matrix_admits_no_edge_the_validator_refuses(served: dict) -> None:
    """THE canary. Every (source act, edge, target act) triple, both ways."""
    divergences = []
    for edge in EdgeType:
        rule = served[edge.value]
        for src in Act:
            for tgt in Act:
                refusal = validator_refuses(src, edge, tgt)
                if matrix_admits(rule, src, edge, tgt) and refusal is not None:
                    divergences.append(
                        f"{src.value} -{edge.value}-> {tgt.value}: matrix "
                        f"admits, validator refuses ({refusal.split(';')[0]})"
                    )
    assert not divergences, (
        f"{len(divergences)} edge(s) the matrix admits and the validator "
        "refuses — a client pre-flighting against /conformance would build "
        "them and be rejected at post:\n  " + "\n  ".join(divergences[:12])
    )


def test_the_matrix_forbids_nothing_the_validator_allows(served: dict) -> None:
    """The other direction, and it is not symmetric noise.

    A matrix STRICTER than the validator is a different failure: nobody is
    rejected, so nothing ever surfaces it, and the cost is silent — legal
    edges that no careful client will ever construct. Serving `same_act`
    without its `source_exempt` escape clause would land exactly here, which
    is why the exemption is generated rather than remembered.
    """
    divergences = []
    for edge in EdgeType:
        rule = served[edge.value]
        for src in Act:
            for tgt in Act:
                if not matrix_admits(rule, src, edge, tgt) \
                        and validator_refuses(src, edge, tgt) is None:
                    divergences.append(f"{src.value} -{edge.value}-> {tgt.value}")
    assert not divergences, (
        f"{len(divergences)} edge(s) the matrix forbids and the validator "
        "allows — legal edges no careful client will ever build:\n  "
        + "\n  ".join(divergences[:12])
    )


def test_every_edge_has_an_entry(served: dict) -> None:
    """An edge missing from the matrix is indistinguishable from an edge with
    no rules, and the next act/edge added should not silently inherit that."""
    assert set(served) == {e.value for e in EdgeType}


def test_supersedes_is_machine_readable_enough_for_the_pre_flight(
    served: dict,
) -> None:
    """#511's acceptance, stated as the question that failed at #502/#509:
    *may a PROPOSAL supersede a SUPERSEDE?* The matrix must now say no."""
    rule = served["supersedes"]
    assert rule != {}, "the defect: a real constraint served as 'unconstrained'"
    assert rule["same_act"] is True
    assert rule["source_exempt"] == ["SUPERSEDE"]

    assert not matrix_admits(rule, Act.PROPOSAL, EdgeType.SUPERSEDES, Act.SUPERSEDE)
    assert validator_refuses(Act.PROPOSAL, EdgeType.SUPERSEDES, Act.SUPERSEDE)

    # and both halves of the real rule, so a fix that over-corrects is caught
    assert matrix_admits(rule, Act.FINDING, EdgeType.SUPERSEDES, Act.FINDING)
    assert matrix_admits(rule, Act.SUPERSEDE, EdgeType.SUPERSEDES, Act.NOTE), (
        "the carrier escape clause is half the rule; dropping it would serve "
        "a matrix stricter than the validator"
    )


def test_the_sweep_is_actually_exercising_the_product(served: dict) -> None:
    """A guard on the guard (#1169's lesson, and mine three times today).

    The two canaries above pass by finding NOTHING. That is exactly the shape
    that also passes when the loop is broken, the fixture is empty, or the
    refusal matcher stops matching — so this asserts the machinery still sees
    the world: the product is the full square, and the validator still
    refuses the case we know it refuses.
    """
    assert len(list(Act)) >= 16 and len(list(EdgeType)) >= 15
    seen_refusals = sum(
        1 for src in Act for tgt in Act
        if validator_refuses(src, EdgeType.SUPERSEDES, tgt) is not None
    )
    assert seen_refusals == 225, (
        "the swept product changed shape — 15 non-carrier source acts x 15 "
        f"mismatched targets = 225, got {seen_refusals}. If an act was added "
        "this number moves and the canaries above need re-reading, not this "
        "constant bumping."
    )
