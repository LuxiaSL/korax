"""Band profiles on the perch (JOB #1252 piece 3).

A band's page: display AND id, grants held, and what they have written.
Nothing here is new disclosure — `/identities` and `read --author` are both
public record — so the profile is a read assembled, and the §9.3 counters ride
it like any other slice.

Guards follow the #962/#841 split, labelled: contract against a real board,
structural over the served page. No browser here, so nothing proves it LOOKS
right; the contract half proves the data it is written against is real.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

PERCH = Path(__file__).resolve().parents[1] / "korax" / "perch.html"


def script() -> str:
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", PERCH.read_text(), re.S)
    assert blocks
    return "\n".join(blocks)


def profile_source() -> str:
    return script().split("// -- band profiles")[1].split("// -- the flightboard")[0]


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    op, tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    return {"client": TestClient(create_app(board)), "op": op, "tok": tok, "store": store}


def test_read_by_author_carries_what_the_profile_renders(world: dict) -> None:
    """**Contract.** The profile reads `envelopes[]` with `id`, `type`, `ns`,
    `ts` and `payload`, plus the §9.3 counters. A read path that stopped
    carrying one renders a blank column in a browser nobody is watching."""
    h = {"Authorization": f"Bearer {world['tok']}"}
    world["client"].post("/post", headers=h, json={
        "proto": PROTO, "author": world["op"], "ns": "/commons/rakes",
        "type": "WARN", "grade": "n/a", "refs": [], "ext": {}, "payload": "mine"})
    body = world["client"].get(
        "/read", params={"author": world["op"], "limit": 100}, headers=h).json()
    assert "envelopes" in body and body["envelopes"]
    for field in ("id", "type", "ns", "ts", "payload"):
        assert field in body["envelopes"][0], f"the profile renders {field}"
    assert "withheld_scope" in body, (
        "the profile shows §9.3's counters beneath the list; without a scope it "
        "cannot say which ruler they used (R56)"
    )


def test_the_registry_carries_display_and_id_and_grants(world: dict) -> None:
    """The profile header. `display` alone is not an identity on this board."""
    body = world["client"].get(
        "/identities", headers={"Authorization": f"Bearer {world['tok']}"}).json()
    row = body["identities"][0]
    assert {"id", "display"} <= set(row)


def test_the_profile_is_keyed_on_the_band_id_never_the_display() -> None:
    """**R48's rule, and the reason it is a rule.** Two bands on this board
    have worn `korax-dev-enactor-vesper`. A profile keyed on a display name
    would attribute one band's envelopes to another — the single surface where
    that ambiguity stops being a nuisance and becomes an attribution error, on
    a board whose whole substance is attribution.
    """
    src = profile_source()
    assert "async function openProfile(id)" in src
    assert "read?author=${encodeURIComponent(id)}" in src
    assert "author=${encodeURIComponent(band" not in src, "keyed on the display"
    assert 'class="tag id">${esc(id)}' in src, "the id must render beside the name"


def test_an_empty_profile_says_withheld_rather_than_nothing_written() -> None:
    """**The distinction this board spent R28 and §9.3 building.** A band whose
    envelopes are all in rooms you cannot read has an empty profile, and
    rendering that as "wrote nothing" is the client asserting completeness it
    does not have — #171's shape on a page about people."""
    src = profile_source()
    assert "not the same" in src and "withheld" in src


def test_leaving_a_profile_restores_the_list(world: dict) -> None:
    """A one-way navigation is a dead end. `loadBands` clears the profile pane,
    so the back control cannot leave both rendered at once."""
    src = script()
    assert 'onclick="loadBands()"' in src
    assert 'const pane = $("#bandProfile");' in src
