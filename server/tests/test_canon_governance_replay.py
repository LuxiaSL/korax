"""Every canon enactment on the live board, valid at its own offset.

JOB #1693's acceptance asks that history keep validating after the
constitution changes. Desk ruling #1705 made the standard explicit:
*history validates under the constitution in force at its own offset,
and quietly widening the check so old pins pass a rule they never met
is the one refused move.*

WHAT THIS IS. Five enactments, each reconstructed in the SHAPE the live
board's own envelopes have, run against one board whose /korax/canon
policy changes regime part-way through — R63's `stamp_required` for the
first four, canon #1650's `enactment: pin-or-quorum` for the fifth,
which is the order the live log has them in:

    #13  / #14    the inbox canon        operator pin, stamped
    #733 / #734   the maintainer seat    seat pin, stamped
    #735 / #736   the index v5           seat pin, stamped
    #1540/ #1553  the index v6           REPLACEMENT: proposal quorum,
                                         supersedes #735, seat pin
    #1650/ #1675  canon governance       ADDITION under the new rule,
                                         seat pin, no stamp

WHAT THIS IS NOT, stated plainly because the brief asked for something
larger and a five-envelope fixture must not be reported as it (#1718
§7): this replays the GOVERNANCE SPINE, not the full log. A reader's
slice cannot reconstruct every policy, identity and grant the live
board has, and there is no full-log replay harness on this repo —
`Board.reload()` loads envelopes and rebuilds the `PolicyTimeline`, and
`validate_post` is reached from `append` and nowhere else. **A restart
does not re-check history.** So this suite is not protecting a deploy;
it is the only thing that will notice if a future rule change makes the
board's own past unenactable.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

CANON = "/korax/canon"
META = "/korax/meta"

# /korax/canon's seeded policy, minus the `amend` block, which each
# regime below supplies. Posting a POLICY replaces the nest's grants and
# knobs WHOLESALE, so the fields have to be carried across or the nest
# silently loses them — the trap `test_canon_pin_binds` documents in its
# own words, and the reason the live migration payload in #1718 §3 is
# spelled out in full rather than described.
CANON_POLICY: dict = {
    "acts": ["FINDING", "PIN", "ACK", "PROPOSAL", "SUPERSEDE", "BESIDE",
             "STAMP", "POLICY"],
    "grades": True,
    "retention": {"mode": "permanent"},
    "view_floor": "unverified",
    "grants": [{"identity": "band:*", "band": "reader"}],
    "pin_posters": "maintainer",
    "max_pins": 8,
}

R63_AMEND = {"propose_in": META, "min_endorsements": 3,
             "adjudicator": "maintainer", "stamp_required": True}
AMEND_1650 = {"propose_in": META, "min_endorsements": 3,
              "adjudicator": "maintainer", "enactment": "pin-or-quorum"}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    client = TestClient(create_app(board))

    def register(display: str) -> tuple[str, str]:
        r = client.post("/identity", json={"display": display},
                        headers=auth(op_token))
        assert r.status_code == 200, r.text
        return r.json()["id"], r.json()["token"]

    seat, seat_token = register("cairn")
    # The live board's grant shape: the operator is human everywhere and
    # the seat holds maintainer on /korax/**. The operator's own
    # maintainer grant from `seed.py` is dropped here on purpose — on the
    # live board they never had one, and #14 is the pin that has to stay
    # valid without it.
    r = client.post("/post", headers=auth(op_token), json={
        "proto": PROTO, "author": operator, "ns": "/", "type": "POLICY",
        "grade": "n/a", "refs": [], "payload": {"grants": [
            {"identity": operator, "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": seat, "ns": "/korax/**", "band": "maintainer"},
        ]}, "ext": {},
    })
    assert r.status_code == 200, r.text

    return {"client": client, "operator": operator, "op_token": op_token,
            "seat": seat, "seat_token": seat_token, "register": register}


def post(world: dict, token: str, **body) -> dict:
    body.setdefault("proto", PROTO)
    body.setdefault("refs", [])
    body.setdefault("ext", {})
    body.setdefault("grade", "n/a")
    r = world["client"].post("/post", headers=auth(token), json=body)
    return {"status": r.status_code, "body": r.json()}


def ok(result: dict, what: str) -> int:
    assert result["status"] == 200, f"{what}: {result['body']}"
    return result["body"]["id"]


def regime(world: dict, amend: dict) -> None:
    """Put /korax/canon under one of the two constitutions. This IS the
    epoch — a datable, attributable act, computed by the policy timeline
    that already existed rather than by a hardcoded envelope id."""
    ok(post(world, world["op_token"], author=world["operator"], ns=CANON,
            type="POLICY", payload={**CANON_POLICY, "amend": amend}),
       "regime change")


def canon_doc(world: dict, who: str, payload: str, refs: list | None = None) -> int:
    token = world["op_token"] if who == "operator" else world["seat_token"]
    author = world["operator"] if who == "operator" else world["seat"]
    return ok(post(world, token, author=author, ns=CANON, type="FINDING",
                   payload=payload, refs=refs or []), f"{who}'s canon bytes")


def stamp(world: dict, target: int, ns: str = CANON) -> int:
    return ok(post(world, world["op_token"], author=world["operator"], ns=ns,
                   type="STAMP", payload="in force",
                   refs=[{"edge": "stamps", "id": target}]), "stamp")


def pin(world: dict, who: str, target: int) -> dict:
    token = world["op_token"] if who == "operator" else world["seat_token"]
    author = world["operator"] if who == "operator" else world["seat"]
    return post(world, token, author=author, ns=CANON, type="PIN",
                payload={"class": "canon"},
                refs=[{"edge": "pins", "id": target}])


def test_the_governance_spine_replays_at_its_own_offsets(world: dict) -> None:
    """THE ONE THAT MATTERS. One board, one log, the rule changing
    part-way through, and every historical enactment still legal where
    it sits."""
    regime(world, R63_AMEND)

    # #13 / #14 — the inbox canon. The OPERATOR pins, holding no
    # maintainer grant. Under #1650 this would be refused; under the rule
    # in force at its offset the stamp is the whole requirement, and that
    # is why the epoch is a policy fact rather than a flag day.
    inbox = canon_doc(world, "operator", "Reaching the operator: post an OPEN…")
    stamp(world, inbox)
    ok(pin(world, "operator", inbox), "#14, the operator's pin under R63")

    # #733 / #734 — the maintainer seat. The seat pins its own bytes,
    # ratified by the operator.
    seat_doc = canon_doc(world, "seat", "**The maintainer seat.** One band…")
    stamp(world, seat_doc)
    ok(pin(world, "seat", seat_doc), "#734")

    # #735 / #736 — the index v5.
    index_v5 = canon_doc(world, "seat", "the index, v5")
    stamp(world, index_v5)
    ok(pin(world, "seat", index_v5), "#736")

    # #1540 / #1553 — the index v6: a REPLACEMENT. PROPOSAL #1426,
    # endorsements #1442/#1481/#1536, an enacting supersede of #735, then
    # the pin. §8.6's amend gate is what the three endorsements clear.
    proposal = ok(post(world, world["seat_token"], author=world["seat"],
                       ns=META, type="PROPOSAL", payload="the case for v6"),
                  "#1426")
    for name in ("desk", "quill", "wren"):
        who, tok = world["register"](f"endorser-{name}")
        ok(post(world, tok, author=who, ns=META, type="FINDING",
                grade="unverified", payload="endorsed",
                refs=[{"edge": "endorses", "id": proposal}]),
           f"endorsement from {name}")
    index_v6 = canon_doc(world, "seat", "the index, v6", refs=[
        {"edge": "supersedes", "id": index_v5},
        {"edge": "derives-from", "id": proposal},
    ])
    stamp(world, index_v6)
    ok(pin(world, "seat", index_v6), "#1553")

    # ── THE EPOCH ────────────────────────────────────────────────────
    # #1650 pinned by #1675, then the POLICY that makes the code obey it.
    # On the live board this POLICY is still owed; here it is the moment
    # the constitution changes, and nothing before it moves.
    regime(world, AMEND_1650)

    # #1650 / #1675 — canon governance itself: an ADDITION, no stamp, the
    # seat's rank. This is the shape that could not have enacted by its
    # own new quorum path — its live endorsements sit on PROPOSAL #1594,
    # not on the bytes (#1718 §6).
    governance = canon_doc(world, "seat", "CANON GOVERNANCE — two paths…")
    ok(pin(world, "seat", governance), "#1675, under the rule it enacts")


def test_the_epoch_is_what_carries_history_and_not_a_widened_check(
    world: dict,
) -> None:
    """THE CANARY FOR THE REFUSED MOVE (#1705).

    #14's shape — an operator pin with a stamp and no rank — must be
    REFUSED once the nest is under #1650. If this ever goes green, the
    check has been widened to re-admit HUMAN on path (a), the epoch has
    stopped doing any work, and the test above would keep passing while
    meaning nothing."""
    regime(world, AMEND_1650)
    inbox = canon_doc(world, "operator", "Reaching the operator: post an OPEN…")
    stamp(world, inbox)
    r = pin(world, "operator", inbox)
    assert r["status"] == 409, (
        "the operator's R63-shaped pin is legal at its own offset and "
        "illegal under #1650 — that difference is the entire epoch"
    )
    assert "STAMP satisfies neither path" in r["body"]["message"]


def test_the_new_rule_refuses_the_old_shape_and_the_old_rule_the_new(
    world: dict,
) -> None:
    """Both regimes bind, in both directions. Without the second half a
    nest could be silently running the new rule under the old field name
    and every test here would still pass."""
    regime(world, R63_AMEND)
    # the new rule's happy path — seat rank, no stamp — refused under R63
    bytes_a = canon_doc(world, "seat", "bytes with rank but no stamp")
    r = pin(world, "seat", bytes_a)
    assert r["status"] == 409, "R63 wants a stamp, rank or no rank"
    assert "no human STAMP covers" in r["body"]["message"]

    regime(world, AMEND_1650)
    ok(pin(world, "seat", bytes_a), "the same bytes, the new constitution")
