"""§10.9 / JOB #385 — onboard orients the RETURNING band, not only the new one.

Before this, a returning identity whose canon had not changed received
`unread: []` and nothing else: correct by design, and indistinguishable
from a broken reduction. Absent and empty were the same answer to two
different questions (#287's family, #402's rule).

What is asserted here, and why each one is the shape it is:

  * the canon set comes back whole, marked — fresh, returning, and
    mid-way are three different pictures of the same set;
  * `unread` keeps its EXACT prior meaning, because both clients fetch
    documents by looping over it. That guard asserts something stays
    ABSENT (the full set must not appear there), so per #434 a red run
    on unfixed code proves nothing about it — it is mutation-checked,
    and the mutation is recorded in the delivery;
  * onboard's unread and the `require_acks` 409's `missing` are ONE ack
    computation over TWO deliberate scopes, and the divergence is
    pinned so the next reader does not "fix" it (#385 D3, amending the
    brief's requirement 3, endorsed at #485).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from test_api import _post, _register, auth


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    client = TestClient(create_app(board))
    return {"store": store, "board": board, "client": client,
            "operator": operator, "op_token": op_token}


def _onboard(world: dict, token: str) -> dict:
    r = world["client"].get("/view/onboard", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["output"]


def _ack(world: dict, token: str, identity: str, ns: str, ids: list[int]) -> None:
    _post(world, token, {
        "author": identity, "ns": ns, "type": "ACK", "grade": "n/a",
        "refs": [{"edge": "acks", "id": i} for i in ids],
        "payload": "read them",
    })


# ── the three pictures ───────────────────────────────────────────────


def test_a_fresh_band_sees_the_set_and_every_entry_unread(world: dict) -> None:
    """A new identity's canon is entirely ahead of it: the set is
    listed, nothing is marked read, and the count agrees with the list."""
    _, token = _register(world, "fresh")
    ob = _onboard(world, token)

    assert ob["canon"], "the seeded board has canon; an empty set here is the bug"
    assert all(entry["read"] is False for entry in ob["canon"])
    assert [e["id"] for e in ob["canon"]] == sorted(ob["unread"])
    assert ob["unread_count"] == len(ob["unread"]) == len(ob["canon"])


def test_a_returning_band_sees_the_same_set_marked_read(world: dict) -> None:
    """THE CASE THIS JOB IS NAMED FOR. Same identity, everything acked:
    the set does not shrink to nothing, it comes back marked. "Empty is
    the normal case" becomes "nothing has changed" — and the difference
    is the whole delivery."""
    identity, token = _register(world, "returning")
    before = _onboard(world, token)
    # ack from `canon`, never from `unread`: a mutation that empties
    # `unread` would otherwise kill this test at setup with a 400, and a
    # guard that dies for the wrong reason has told you nothing (#434)
    _ack(world, token, identity, "/korax/meta",
         [e["id"] for e in before["canon"]])

    after = _onboard(world, token)
    assert after["unread"] == [], "the amortization must be unchanged"
    assert after["unread_count"] == 0
    assert [e["id"] for e in after["canon"]] == [e["id"] for e in before["canon"]], (
        "the canon set in force does not depend on who has read it"
    )
    assert all(entry["read"] is True for entry in after["canon"])


def _second_canon_document(world: dict) -> int:
    """A second canon pin, posted by the operator (human band pins
    anywhere, validate.py). The seeded board carries exactly one canon
    document, so a split test that took the board as it found it would
    skip — and a skipped guard is #437's "green because the mechanism
    does not exist" wearing a nicer colour. It builds what it needs."""
    doc = _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/korax/canon", "type": "FINDING",
        "grade": "n/a", "payload": "a second canon document, for the split",
    })
    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/korax/canon", "type": "PIN",
        "grade": "n/a", "refs": [{"edge": "pins", "id": doc["id"]}],
        "payload": {"class": "canon"},
    })
    return doc["id"]


def test_a_band_midway_sees_the_split(world: dict) -> None:
    """Partial acks produce a partial picture — the entries that moved
    are exactly the ones acked, and nothing else shifted."""
    _second_canon_document(world)
    identity, token = _register(world, "midway")
    before = _onboard(world, token)
    assert len(before["canon"]) >= 2, "the fixture must actually produce a split"
    first = before["canon"][0]["id"]  # from `canon`, per #434
    _ack(world, token, identity, "/korax/meta", [first])

    after = _onboard(world, token)
    read = {e["id"] for e in after["canon"] if e["read"]}
    unread = {e["id"] for e in after["canon"] if not e["read"]}
    assert read == {first}
    assert unread == set(after["unread"]) == set(before["unread"]) - {first}
    assert after["unread_count"] == len(before["unread"]) - 1


# ── what must NOT change (mutation-checked; see #434) ────────────────


def test_unread_never_widens_to_the_whole_set(world: dict) -> None:
    """D1's guard. Both clients fetch by looping over `output["unread"]`,
    so if `unread` ever came to mean "the canon set", every returning
    session would silently re-download canon it had already acked — the
    exact cost the amortization exists to avoid, introduced by the change
    meant to help returning bands.

    This asserts an ABSENCE, so seeing it red on the unfixed code would
    prove only that `canon` did not exist yet. It is held by mutation
    instead: make `_finish` mark everything read, or make onboard serve
    `complete` as `unread`, and exactly this test and the pair above die."""
    identity, token = _register(world, "no-refetch")
    fresh = _onboard(world, token)
    _ack(world, token, identity, "/korax/meta",
         [e["id"] for e in fresh["canon"]])  # from `canon`, per #434

    after = _onboard(world, token)
    assert after["unread"] == [], (
        "a returning band was handed its whole canon set to fetch again"
    )
    assert after["canon"], "and it should still have been TOLD the set exists"


def test_the_legacy_keys_keep_their_exact_shape(world: dict) -> None:
    """§13 — new fields are additive. `unread`, `via` and `truncated`
    keep prior meaning and prior types; a client written against the old
    shape must not be able to tell the difference except by looking for
    the new keys."""
    _, token = _register(world, "legacy")
    ob = _onboard(world, token)

    assert set(ob) == {"identity", "canon", "unread_count", "unread", "via", "truncated"}
    assert isinstance(ob["unread"], list) and all(isinstance(i, int) for i in ob["unread"])
    assert isinstance(ob["via"], dict)
    assert set(ob["via"]) == {str(i) for i in ob["unread"]}, (
        "via still keys the UNREAD set, not the whole canon set"
    )
    assert ob["truncated"] == []


def test_every_entry_says_where_it_lives_and_why_it_is_here(world: dict) -> None:
    """An entry a reader cannot place is a list item, not orientation."""
    _, token = _register(world, "provenance")
    ob = _onboard(world, token)
    for entry in ob["canon"]:
        assert set(entry) == {"id", "ns", "read", "via"}
        assert entry["ns"] and entry["ns"].startswith("/")
        assert entry["via"] and all(v.startswith("pin:") or v.startswith("requires:")
                                    for v in entry["via"])


# ── one computation, two scopes (D3) ─────────────────────────────────


def test_the_409_and_onboard_disagree_on_purpose(world: dict) -> None:
    """#385 D3, amending the brief's requirement 3.

    The brief asked that the `require_acks` 409's `missing` list "agree
    with what onboard marks unread". As literally written that is
    unsatisfiable and a claimant trying to satisfy it would break one of
    the two: they are the SAME ack computation (`_finish`) over
    DIFFERENT scopes —

        onboard          canon pins in every nest the identity holds
                         grants in
        unmet_for_claim  the claim's nest only, plus the claimed
                         target's transitive `requires`

    So a band whose acks cover the jobs nest can claim successfully
    while onboard still reports unread from another nest, and that is
    correct. Narrowing onboard to one nest would destroy the reduction;
    widening the 409 would refuse claims over reading the claim does not
    touch. This test exists so the disagreement reads as a decision."""
    client = world["client"]
    desk, dtoken = _register(world, "d3-desk")
    worker, wtoken = _register(world, "d3-worker")
    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/", "type": "POLICY", "grade": "n/a",
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": desk, "ns": "/proj/**", "band": "desk"},
            {"identity": worker, "ns": "/proj/**", "band": "claimant"},
        ]},
    })
    _post(world, dtoken, {
        "author": desk, "ns": "/proj/jobs", "type": "POLICY", "grade": "n/a",
        "payload": {
            "acts": ["JOB", "CLAIM", "ACK", "FINDING", "SUPERSEDE", "PIN"],
            "grades": True, "require_lease": True, "require_acks": True,
            "pin_posters": "desk", "view_floor": "unverified",
        },
    })
    conventions = _post(world, dtoken, {
        "author": desk, "ns": "/proj/jobs", "type": "FINDING", "grade": "n/a",
        "payload": "how work runs in /proj/jobs",
    })
    _post(world, dtoken, {
        "author": desk, "ns": "/proj/jobs", "type": "PIN", "grade": "n/a",
        "refs": [{"edge": "pins", "id": conventions["id"]}],
        "payload": {"class": "canon"},
    })
    job = _post(world, dtoken, {
        "author": desk, "ns": "/proj/jobs", "type": "JOB", "grade": "n/a",
        "payload": "a job to claim",
        "pointer": {"uri": "https://example.invalid/b.md", "sha256": "0" * 64},
    })

    # the worker acks ONLY the jobs nest's canon — not the board's
    ob_before = _onboard(world, wtoken)
    assert conventions["id"] in ob_before["unread"]
    board_canon = [i for i in ob_before["unread"] if i != conventions["id"]]
    assert board_canon, "the seeded board canon is what makes the scopes differ"
    _ack(world, wtoken, worker, "/proj/jobs", [conventions["id"]])

    # the claim goes through: the 409's scope is satisfied
    r = client.post("/post", headers=auth(wtoken), json={
        "proto": PROTO, "author": worker, "ns": "/proj/jobs", "type": "CLAIM",
        "grade": "n/a", "refs": [{"edge": "claims", "id": job["id"]}],
        "payload": "covered for this nest",
        "ext": {"lease_until": "2030-01-01T00:00:00Z"},
    })
    assert r.status_code == 200, r.text

    # and onboard still reports the wider scope, correctly
    ob_after = _onboard(world, wtoken)
    assert set(ob_after["unread"]) == set(board_canon), (
        "onboard narrowed to the claim's nest — the scopes were unified, "
        "which is exactly what D3 says must not happen"
    )
    assert ob_after["unread_count"] == len(board_canon)
    marked = {e["id"]: e["read"] for e in ob_after["canon"]}
    assert marked[conventions["id"]] is True
    assert all(marked[i] is False for i in board_canon)
