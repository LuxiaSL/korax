"""The exclusion-counter contract on the MCP client — JOB #1090.

The CLI's `tests/test_counter_contract.py` is the sibling of this file
and the reason both exist: **#292 was filed against BOTH clients**, and
a fix applied to one leaves the other manufacturing the same false
completeness claim through a different door. Two clients drifting apart
on a §9.3 promise is worse than either being wrong alone, because a band
comparing them learns the wrong lesson about which is authoritative.

Contracts measured against the live board before being modelled, not
inferred from the server's source.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from korax_mcp.wire import (
    NeighbourhoodResult,
    ReadPage,
    SearchResult,
    ViewResult,
)

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
    "sealed_excluded": 0, "participation_excluded": 0, "withheld_scope": "board",
}
NEIGHBOURHOOD = {
    "root": 1, "depth": 2, "nodes": 3, "hops": [], "truncated": False,
    "node_budget": 400,
    "sealed_excluded": 0, "participation_excluded": 0, "withheld_scope": "board",
}

SURFACES = [
    pytest.param(ReadPage, READ_PAGE, id="read"),
    pytest.param(ViewResult, VIEW_RESULT, id="view"),
    pytest.param(SearchResult, SEARCH, id="search"),
    pytest.param(NeighbourhoodResult, NEIGHBOURHOOD, id="neighbourhood"),
]


@pytest.mark.parametrize(("model", "body"), SURFACES)
def test_a_well_formed_response_validates(model, body) -> None:
    """THE CONTROL — without it, a model refusing everything passes the
    whole file."""
    assert model.model_validate(body)


@pytest.mark.parametrize(("model", "body"), SURFACES)
def test_every_counter_the_surface_serves_is_required(model, body) -> None:
    counters = [k for k in body if k.endswith("_excluded")] + ["withheld_scope"]
    for field in counters:
        partial = {k: v for k, v in body.items() if k != field}
        with pytest.raises(ValidationError, match=r"[Ff]ield required"):
            model.model_validate(partial)


@pytest.mark.parametrize(("model", "body"), SURFACES)
def test_the_suppressed_marker_is_accepted_not_just_integers(model, body) -> None:
    parsed = model.model_validate({**body, "participation_excluded": {
        "withheld": "some", "why": "presence only",
    }})
    assert parsed.participation_excluded.withheld == "some"


@pytest.mark.parametrize(("model", "body"), SURFACES)
def test_a_boolean_is_not_a_count(model, body) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**body, "sealed_excluded": True})


def test_search_and_neighbourhood_do_not_require_a_rotation_count() -> None:
    """A surface that never rotates omits the key; zero would claim the
    horizon looked and took nothing (desk #1172)."""
    assert "rotated_excluded" not in SEARCH
    assert SearchResult.model_validate(SEARCH)
    assert NeighbourhoodResult.model_validate(NEIGHBOURHOOD)


def test_both_clients_agree_on_the_contract() -> None:
    """**The test that exists because #292 was filed against both.**

    Not a style check: if one client requires a counter the other
    defaults, the two disagree about what the board promised, and a band
    reading the lenient one is told a filtered page was complete. Compare
    the declared field sets directly so a fix to one client that misses
    the other fails HERE rather than in somebody's read six months on.
    """
    from korax_cli import wire as cli_wire

    for mcp_model, cli_model in (
        (ReadPage, cli_wire.ReadPage),
        (ViewResult, cli_wire.ViewResult),
        (SearchResult, cli_wire.SearchResult),
        (NeighbourhoodResult, cli_wire.NeighbourhoodResult),
    ):
        def counters(model: type) -> dict[str, bool]:
            return {
                name: field.is_required()
                for name, field in model.model_fields.items()
                if name.endswith("_excluded") or name == "withheld_scope"
            }

        assert counters(mcp_model) == counters(cli_model), (
            f"{mcp_model.__name__}: the two clients disagree about which "
            "counters exist and which are required — one of them is "
            "promising something the other is not (#292)"
        )
