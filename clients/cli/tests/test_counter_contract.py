"""The exclusion-counter contract, per surface — JOB #1090, #292/#662.

These fields are the board's promise that a filtered projection never
renders as complete (§9.3). A promise the CLIENT can supply for itself
is not a promise, which is why every counter is required with no default
— and why a counter the server genuinely does not serve must be OMITTED
rather than required, because a model demanding a field the contract
never sends is the same defect reflected.

The contracts below were MEASURED against the live board before being
written (survey log rides with the delivery), not inferred from the
server's source. That distinction is the job: a client that models what
it believes the server sends is the thing being fixed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from korax_cli.wire import (
    NeighbourhoodResult,
    ReadPage,
    SearchResult,
    ViewResult,
)

# What each surface actually serves. Anything absent here is absent on
# the wire, deliberately.
READ_PAGE = {
    "envelopes": [], "cursor": 7,
    "sealed_excluded": 0, "rotated_excluded": 0, "participation_excluded": 0,
    "withheld_scope": "slice",
}
VIEW_RESULT = {
    "view": "docket", "at": 12, "output": {},
    "sealed_excluded": 0, "rotated_excluded": 0, "participation_excluded": 0,
    "withheld_scope": "slice",
}
SEARCH = {
    "q": "x", "results": [], "returned": 0, "truncated_at_limit": False,
    "sealed_excluded": 0, "participation_excluded": 0,
    "withheld_scope": "board",
}
NEIGHBOURHOOD = {
    "root": 1, "depth": 2, "nodes": 3, "hops": [], "truncated": False,
    "node_budget": 400,
    "sealed_excluded": 0, "participation_excluded": 0,
    "withheld_scope": "board",
}

SURFACES = [
    pytest.param(ReadPage, READ_PAGE, id="read"),
    pytest.param(ViewResult, VIEW_RESULT, id="view"),
    pytest.param(SearchResult, SEARCH, id="search"),
    pytest.param(NeighbourhoodResult, NEIGHBOURHOOD, id="neighbourhood"),
]


@pytest.mark.parametrize(("model", "body"), SURFACES)
def test_a_well_formed_response_validates(model, body) -> None:
    """THE CONTROL, and it is not decoration.

    Every assertion below is that something is REFUSED. Without this,
    a model that rejected everything would pass the entire file.
    """
    assert model.model_validate(body)


@pytest.mark.parametrize(("model", "body"), SURFACES)
def test_every_counter_the_surface_serves_is_required(model, body) -> None:
    """Drop each counter in turn and watch it refuse.

    Absence must never render as zero. `extra="allow"` means an omitted
    counter arrives as no key at all, so a client that did not model it
    could not refuse it — which is how two of these went unnoticed while
    a comment four lines up explained why they mattered.
    """
    counters = [k for k in body if k.endswith("_excluded")] + ["withheld_scope"]
    for field in counters:
        partial = {k: v for k, v in body.items() if k != field}
        with pytest.raises(ValidationError, match=r"[Ff]ield required"):
            model.model_validate(partial)


@pytest.mark.parametrize(("model", "body"), SURFACES)
def test_the_suppressed_marker_is_accepted_not_just_integers(model, body) -> None:
    """Posture two (#662): a count exists and is withheld, with its why.

    §9.3 buckets rather than answering an exact count on a room you are
    not in. A model admitting only integers would refuse the live board's
    ordinary answer — the failure this typing exists to avoid, and the
    one a zeros-only fixture would never catch.
    """
    suppressed = {**body, "participation_excluded": {
        "withheld": "some", "why": "presence only",
    }}
    parsed = model.model_validate(suppressed)
    assert parsed.participation_excluded.withheld == "some"


@pytest.mark.parametrize(("model", "body"), SURFACES)
def test_a_boolean_is_not_a_count(model, body) -> None:
    """pydantic takes `True` as an integer in lax mode, so without
    StrictInt a boolean on the wire renders as the count `1`. In a model
    whose whole subject is values nobody sent, that is the defect."""
    with pytest.raises(ValidationError):
        model.model_validate({**body, "sealed_excluded": True})


def test_search_and_neighbourhood_do_not_require_a_rotation_count() -> None:
    """**The contract statement, asserted rather than left implicit.**

    `/search` and `/neighbourhood` do not serve `rotated_excluded` — a
    surface that never rotates says so by omitting the key, where zero
    would claim the horizon looked and took nothing (desk #1172).

    So this is not leniency: requiring a field the server never sends
    would refuse every real response, which is the same class of bug as
    defaulting one it does send. If these surfaces ever begin serving it,
    this test still passes and the model should be tightened
    deliberately — the failure it guards is the opposite direction.
    """
    assert "rotated_excluded" not in SEARCH
    assert "rotated_excluded" not in NEIGHBOURHOOD
    assert SearchResult.model_validate(SEARCH)
    assert NeighbourhoodResult.model_validate(NEIGHBOURHOOD)


@pytest.mark.parametrize(("model", "body"), SURFACES)
def test_unknown_fields_still_survive(model, body) -> None:
    """§13 — required counters must not have cost us forward
    compatibility. A minor version may add fields; dropping one produces
    a projection wrong in a way nobody can see."""
    parsed = model.model_validate({**body, "invented_later": {"deep": [1]}})
    assert parsed.model_dump(mode="json")["invented_later"] == {"deep": [1]}
