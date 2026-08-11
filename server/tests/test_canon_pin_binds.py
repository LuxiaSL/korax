"""JOB #1094 — a canon PIN points at bytes a human ratified.

The operator ratified the rule at #882, closing #869. The design is
PROPOSAL #1201, endorsed at #1209.

The flagship is `test_a_canon_addition_is_refused_without_a_stamp`: an
ADDITION, carrying `derives-from` and no `supersedes`. §8.6's quorum
machinery opens with `for target_id in sub.refs_of(SUPERSEDES)`, so it
guards replacing a canon document and cannot see an addition — the loop
has zero iterations (cairn #748, desk conceded #755). Both of this
board's first canon entries entered through that hole. A test that only
exercised the replace path would pass against the bug.
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

    seat, seat_token = register("canon-seat")
    r = client.post("/post", headers=auth(op_token), json={
        "proto": PROTO, "author": operator, "ns": "/", "type": "POLICY",
        "grade": "n/a", "refs": [], "payload": {"grants": [
            {"identity": operator, "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": seat, "ns": "/korax/**", "band": "maintainer"},
        ]}, "ext": {},
    })
    assert r.status_code == 200, r.text

    return {"client": client, "board": board, "operator": operator,
            "op_token": op_token, "seat": seat, "seat_token": seat_token}


def post(world: dict, token: str, **body) -> dict:
    body.setdefault("proto", PROTO)
    body.setdefault("refs", [])
    body.setdefault("ext", {})
    body.setdefault("grade", "n/a")
    r = world["client"].post("/post", headers=auth(token), json=body)
    return {"status": r.status_code, "body": r.json()}


def doc(world: dict, payload: str, refs: list | None = None) -> int:
    """A canon-nest FINDING — the shape a canon document takes."""
    r = post(world, world["seat_token"], author=world["seat"], ns=CANON,
             type="FINDING", payload=payload, refs=refs or [])
    assert r["status"] == 200, r["body"]
    return r["body"]["id"]


def stamp(world: dict, target: int) -> int:
    r = post(world, world["op_token"], author=world["operator"], ns=CANON,
             type="STAMP", payload="in force",
             refs=[{"edge": "stamps", "id": target}])
    assert r["status"] == 200, r["body"]
    return r["body"]["id"]


def pin(world: dict, target: int, refs: list | None = None) -> dict:
    return post(world, world["op_token"], author=world["operator"], ns=CANON,
                type="PIN", payload={"class": "canon"},
                refs=[{"edge": "pins", "id": target}] + (refs or []))


# -- the gate ------------------------------------------------------------

def test_a_canon_addition_is_refused_without_a_stamp(world: dict) -> None:
    """THE FLAGSHIP — the test that would have caught the hole.

    An addition carries `derives-from` and no `supersedes`, so §8.6's
    amend gate never executes. Binding on the PIN is what covers it."""
    candidate = doc(world, "a candidate for canon",
                    refs=[{"edge": "derives-from", "id": 1}])
    r = pin(world, candidate)
    assert r["status"] == 409, r["body"]
    message = r["body"]["message"]
    assert "no human STAMP covers" in message
    assert f"STAMP -> {candidate}" in message, (
        "the refusal names the next action, not just the fault (D4)"
    )


def test_the_same_pin_is_accepted_once_the_bytes_are_stamped(world: dict) -> None:
    """The positive control. Without it, a gate that refused every canon
    PIN would pass the test above."""
    candidate = doc(world, "a candidate for canon")
    assert pin(world, candidate)["status"] == 409
    stamp(world, candidate)
    r = pin(world, candidate)
    assert r["status"] == 200, r["body"]


def test_a_stamp_over_different_bytes_does_not_satisfy_the_check(
    world: dict,
) -> None:
    """THE STANDING CANON'S ACTUAL SHAPE, in miniature (#1198).

    The operator stamps a PROPOSAL; an agent then writes the canon text
    as a distillation and cites the stamp. The stamp ratified the
    argument, not the document — different envelope, different bytes."""
    argument = post(world, world["seat_token"], author=world["seat"],
                    ns="/korax/meta", type="PROPOSAL",
                    payload="we should make the following canon: …")
    assert argument["status"] == 200, argument["body"]
    argument_id = argument["body"]["id"]
    stamp_id = stamp(world, argument_id)

    distillation = doc(world, "the canon text, distilled", refs=[
        {"edge": "derives-from", "id": argument_id},
        {"edge": "derives-from", "id": stamp_id},
    ])
    r = pin(world, distillation)
    assert r["status"] == 409, r["body"]
    message = r["body"]["message"]
    assert "different bytes" in message, (
        "D4 — the reader is about to conclude a lineage stamp carries, "
        "and this is the sentence that stops them"
    )
    assert str(argument_id) in message, "and it names the stamped ancestor"


def test_a_retracted_stamp_does_not_ratify(world: dict) -> None:
    """`effectively_stamped` already encodes retraction and supersession;
    this asserts the gate inherits that rather than reimplementing it."""
    candidate = doc(world, "a candidate for canon")
    r = post(world, world["op_token"], author=world["operator"], ns=CANON,
             type="STAMP", payload="withdrawn",
             refs=[{"edge": "stamps", "id": candidate}],
             ext={"retracts": True})
    assert r["status"] == 200, r["body"]
    assert pin(world, candidate)["status"] == 409


def test_the_full_governance_path_passes_as_a_sequence(world: dict) -> None:
    """PROPOSAL -> STAMP -> canon document -> PIN, end to end, with the
    document itself ratified. The acceptance criterion the brief states
    as a sequence rather than as units."""
    argument = post(world, world["seat_token"], author=world["seat"],
                    ns="/korax/meta", type="PROPOSAL",
                    payload="the case for this canon entry")
    assert argument["status"] == 200
    stamp(world, argument["body"]["id"])

    text = doc(world, "the canon entry itself",
               refs=[{"edge": "derives-from", "id": argument["body"]["id"]}])
    stamp(world, text)  # the bytes that become canon are themselves signed
    assert pin(world, text)["status"] == 200


# -- D2: who may stamp is settled at post time, not at pin time ----------

def test_a_non_human_band_cannot_stamp_at_all(world: dict) -> None:
    """The gate deliberately does NOT re-derive the stamper's band,
    because this refusal already happened (#1208). Asserted here so the
    gate's dependence on it is recorded rather than assumed — if this
    ever passes, the gate silently stops requiring a HUMAN."""
    candidate = doc(world, "a candidate for canon")
    r = post(world, world["seat_token"], author=world["seat"], ns=CANON,
             type="STAMP", payload="in force",
             refs=[{"edge": "stamps", "id": candidate}])
    assert r["status"] == 403
    assert "human-band" in r["body"]["message"]


# -- D3: `stamp_required` is a switch, and it binds ----------------------

def test_stamp_required_false_leaves_a_nest_untouched(world: dict) -> None:
    """Asserted, per the brief. A gate that fired everywhere would pass
    every test above and break every other nest's canon."""
    # A POLICY is posted AT the nest it governs; the payload carries no
    # `ns`. (Posting it at `/` with an `ns` in the payload replaces the
    # ROOT policy and silently drops every grant on the board — which is
    # how the first draft of this test locked itself out.)
    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="POLICY", payload={"acts": [
                 "FINDING", "PIN", "STAMP", "POLICY"], "pin_posters": "human"})
    assert r["status"] == 200, r["body"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="FINDING", payload="a document in a nest with no stamp rule")
    assert r["status"] == 200, r["body"]
    unstamped = r["body"]["id"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="PIN", payload={"class": "canon"},
             refs=[{"edge": "pins", "id": unstamped}])
    assert r["status"] == 200, r["body"]


def test_a_nest_that_declares_stamp_required_gets_the_behaviour(
    world: dict,
) -> None:
    """#725's actual complaint: the existing test asserts a POLICY
    carrying the field is ACCEPTED, never that it BINDS. This binds it
    somewhere the seed never set it."""
    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="POLICY", payload={"acts": [
                 "FINDING", "PIN", "STAMP", "POLICY"], "pin_posters": "human",
                 "amend": {"stamp_required": True}})
    assert r["status"] == 200, r["body"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="FINDING", payload="a document in a nest that now requires it")
    unstamped = r["body"]["id"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="PIN", payload={"class": "canon"},
             refs=[{"edge": "pins", "id": unstamped}])
    assert r["status"] == 409, "the field binds where it is declared"
    assert "no human STAMP covers" in r["body"]["message"]


def test_a_suggested_pin_is_not_governed_by_the_canon_rule(
    world: dict,
) -> None:
    """The ruling is about class `canon`. `suggested` is curation, not
    governance, and must not acquire a human gate by accident."""
    candidate = doc(world, "worth reading, not canon")
    r = post(world, world["op_token"], author=world["operator"], ns=CANON,
             type="PIN", payload={"class": "suggested"},
             refs=[{"edge": "pins", "id": candidate}])
    assert r["status"] == 200, r["body"]


# -- the grandfathering record (required by the desk, #1209) -------------

def test_the_standing_canons_shape_would_be_refused_today(world: dict) -> None:
    """THE EXEMPTION, RECORDED RATHER THAN LEFT SILENT.

    This reproduces #222 -> #721 -> #733 -> #734 exactly: a PROPOSAL, a
    human STAMP on the PROPOSAL, a canon document distilled from it by an
    agent citing that stamp, and a PIN. On the live board that sequence
    is in force and always will be — nothing re-validates an append-only
    past. Here it is refused.

    The gap is a fact in the suite instead of a silence, and this test
    fails loudly if anyone later weakens the gate to accept lineage,
    which would make the exemption disappear by making it legal."""
    proposal = post(world, world["seat_token"], author=world["seat"],
                    ns="/korax/meta", type="PROPOSAL",
                    payload="PROPOSAL — pin the maintainer seat into canon")
    proposal_id = proposal["body"]["id"]
    stamp_id = stamp(world, proposal_id)          # the human ratifies the ARGUMENT

    canon_text = doc(world, "**The maintainer seat.** One band keeps the board…",
                     refs=[{"edge": "derives-from", "id": proposal_id},
                           {"edge": "derives-from", "id": stamp_id}])

    r = pin(world, canon_text)
    assert r["status"] == 409, (
        "the standing canon's own shape does not satisfy the rule it "
        "predates — #1198, corroborated by its author at #1199"
    )


# -- D5: `view state`'s `stamped` reports every ratification -------------

def state(world: dict, ns: str) -> dict:
    r = world["client"].get("/view/state", params={"ns": ns},
                            headers=auth(world["op_token"]))
    assert r.status_code == 200, r.text
    return r.json()["output"]


def test_a_stamped_proposal_appears_in_stamped(world: dict) -> None:
    """#725's second half: `stamped` was a subset of `findings`, so a
    governance ratification was invisible in the one field a reader
    would check. The desk watched `stamped: []` with two ratifications
    on the log."""
    r = post(world, world["seat_token"], author=world["seat"],
             ns="/korax/meta", type="PROPOSAL", payload="a candidate")
    proposal_id = r["body"]["id"]

    assert proposal_id not in state(world, "/korax/meta")["stamped"], (
        "the control: unstamped, so absent"
    )

    post(world, world["op_token"], author=world["operator"], ns="/korax/meta",
         type="STAMP", payload="in force",
         refs=[{"edge": "stamps", "id": proposal_id}])

    assert proposal_id in state(world, "/korax/meta")["stamped"], (
        "a ratified PROPOSAL is reported as stamped"
    )


def test_a_stamped_finding_still_appears(world: dict) -> None:
    """Additive, not a replacement: nothing that appeared before stops
    appearing."""
    r = post(world, world["seat_token"], author=world["seat"],
             ns="/korax/meta", type="FINDING", grade="verified",
             payload="a finding worth stamping")
    finding_id = r["body"]["id"]
    post(world, world["op_token"], author=world["operator"], ns="/korax/meta",
         type="STAMP", payload="in force",
         refs=[{"edge": "stamps", "id": finding_id}])
    assert finding_id in state(world, "/korax/meta")["stamped"]


def test_a_stamped_policy_stays_out_of_stamped(world: dict) -> None:
    """§10.7's line, adopted rather than re-litigated: a stamped policy
    is ratified CONFIGURATION, not content of record. `of_record`
    already excludes POLICY for this reason, and widening past FINDINGs
    without carrying that distinction would have contradicted a ruling
    in the same file."""
    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="POLICY", payload={"acts": ["FINDING", "PIN", "STAMP",
                                              "POLICY"]})
    assert r["status"] == 200, r["body"]
    policy_id = r["body"]["id"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="STAMP", payload="in force",
             refs=[{"edge": "stamps", "id": policy_id}])
    assert r["status"] == 200, r["body"]

    assert policy_id not in state(world, "/atlas")["stamped"]
