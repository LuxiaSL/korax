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


import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from perch_source import script as _script


def script() -> str:
    return _script()


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
    assert body.get("envelopes")
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
    """A one-way navigation is a dead end. Since S1 (JOB #1969) the back
    control ROUTES to #/bands — the router calls `loadBands`, which clears
    the profile pane, so the back control cannot leave both rendered at
    once and the URL tracks the leave."""
    src = script()
    assert "location.hash='#/bands'" in src
    assert 'const pane = $("#bandProfile");' in src


def test_the_profile_button_lives_where_its_variable_is_bound() -> None:
    """**The defect the desk caught at #1301, and the test that would have.**

    The `profile` button interpolates `i.id` — the identity being mapped in
    `loadBands`. A positional edit put it inside `openProfile` instead, where
    `i` is unbound: evaluating the template throws `ReferenceError`, the
    innerHTML assignment never happens, and the profile renders as nothing.

    **No browser in this suite, so an unbound identifier in a template literal
    is invisible to every other test here.** The suites were green. This pins
    the binding by location, which is the cheapest thing that could have
    caught it.
    """
    src = script()
    # S1 (JOB #1969) split openProfile into navigate + render; the template
    # this test polices lives in renderProfile now. Targeting the old name
    # would make this test VACUOUS, not red (#1960's class), so it follows
    # the template.
    profile_fn = src.split("async function renderProfile(id)")[1].split("\n}")[0]
    assert "i.id" not in profile_fn and "i.display" not in profile_fn, (
        "renderProfile references `i`, which is bound only inside loadBands' "
        "identity map — evaluating this throws and the pane stays empty"
    )
    bands_fn = src.split("async function loadBands()")[1].split("\n}")[0]
    assert "openProfile('${esc(i.id)}')" in bands_fn, (
        "the profile button is not in loadBands' card, so either it moved "
        "again or the band list has no way into a profile"
    )


def test_every_interpolation_in_the_profile_view_is_a_bound_name() -> None:
    """The general form of the above, as far as a string check honestly goes.

    Every `${...}` in `openProfile`'s template may only reference names the
    function actually binds. This cannot catch a typo'd property, but it
    catches the whole class the desk found: a fragment pasted from a scope it
    does not live in.
    """
    src = script()
    # renderProfile carries the template since S1 — see the comment in the
    # binding test above.
    body = src.split("async function renderProfile(id)")[1].split("\n}\n")[0]
    # locals + helpers this file defines, plus the JS globals a template may
    # legitimately call. `encodeURIComponent` is one and tripped the first
    # draft — a too-narrow allowlist reports correct code as a defect, which
    # is the opposite failure and just as expensive to chase.
    bound = {"id", "band", "page", "envs", "grants", "esc", "who", "fbWithheld",
             "fbFirstLine", "openEnvelope", "loadBands", "REG", "api", "$",
             "registry", "e", "g", "a", "b",
             "encodeURIComponent", "JSON", "String", "Object", "Array"}
    import re as _re
    names = set(_re.findall(r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*)", body))
    unbound = names - bound
    assert not unbound, (
        f"interpolations reference names openProfile does not bind: {sorted(unbound)}"
    )
