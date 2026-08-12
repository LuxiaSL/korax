"""Canon enacts by the seat's rank or by a three-band quorum (#1650).

JOB #1094 / R63 put a human STAMP in front of every canon PIN. Canon
#1650 (pinned #1675, operator's stamp #1672 — "the stamp that retires
the stamp") replaced that rule with two paths, and JOB #1693 is the
code half. This file was the R63 guard and is now the #1650 guard; the
history is kept because the tests that changed are the interesting
part of the record.

WHAT SURVIVED THE REWRITE, AND WHY IT MATTERS THAT IT DID:

  - **Binding on the PIN.** Unchanged, and for the original reason
    (#748/#755): an ADDITION carries `derives-from` and no
    `supersedes`, so §8.6's amend gate — `for target_id in
    sub.refs_of(SUPERSEDES)` — has zero iterations and cannot see it.
    Both of this board's first canon entries entered through that
    hole. Binding on the PIN covers additions and replacements in one
    rule. A suite that only exercised the replace path would pass
    against the bug then and now.
  - **`stamp_required` still binds where a nest declares it.** That is
    not back-compat politeness: it is the epoch. Every canon PIN
    already on the log was posted under R63, and a nest moves to
    #1650's rule by POLICY (`amend.enactment`), so history stays valid
    at its own offset with no grandfathering clause anywhere (desk
    ruling #1705). `test_the_retired_rule_still_binds_where_declared`
    is the test that keeps that true.

WHAT INVERTED: a stamp alone used to be sufficient and is now
insufficient (#1650 clause 2). `test_a_stamp_alone_no_longer_suffices`
is the old `test_the_same_pin_is_accepted_once_the_bytes_are_stamped`
turned over, and it is the one to read first.

THE FIXTURE'S OPERATOR IS DELIBERATELY NOT A MAINTAINER. `seed.py`
grants the genesis identity `maintainer` on /korax/** so a fresh board
can pin its own canon by path (a); this fixture's root POLICY replaces
that grant set and drops it, leaving the operator HUMAN-only. That is
the live board's shape and the only shape in which path (b) can be
observed at all — HUMAN clears `pin_posters` but does not satisfy path
(a) (#1705's corollary; `PolicyTimeline.holds_grant`).
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
            "op_token": op_token, "seat": seat, "seat_token": seat_token,
            "register": register}


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


def stamp(world: dict, target: int, ns: str = CANON) -> int:
    r = post(world, world["op_token"], author=world["operator"], ns=ns,
             type="STAMP", payload="in force",
             refs=[{"edge": "stamps", "id": target}])
    assert r["status"] == 200, r["body"]
    return r["body"]["id"]


def pin(world: dict, target: int, refs: list | None = None) -> dict:
    """A PIN by the OPERATOR — human band, no maintainer grant. Clears
    `pin_posters` and fails path (a), which is what makes the quorum
    path observable."""
    return post(world, world["op_token"], author=world["operator"], ns=CANON,
                type="PIN", payload={"class": "canon"},
                refs=[{"edge": "pins", "id": target}] + (refs or []))


def seat_pin(world: dict, target: int) -> dict:
    """A PIN by the maintainer seat — path (a)."""
    return post(world, world["seat_token"], author=world["seat"], ns=CANON,
                type="PIN", payload={"class": "canon"},
                refs=[{"edge": "pins", "id": target}])


def endorser(world: dict, display: str) -> tuple[str, str]:
    """A fresh band that can endorse: /korax/meta grants `band:*` warner
    in the seed, which is the §5.4 floor for an `endorses` edge."""
    return world["register"](display)


def endorse(world: dict, who: tuple[str, str], target: int) -> dict:
    """Back the BYTES — an `endorses` edge onto the envelope itself.
    Legal only since JOB #1693 widened `EDGE_TARGET_ACTS[ENDORSES]` to
    reach a FINDING; before that this was a 400 and #1650's ADDITION
    quorum could not be expressed at all (#1228)."""
    identity, token = who
    return post(world, token, author=identity, ns=META, type="FINDING",
                grade="unverified", payload="I back these bytes",
                refs=[{"edge": "endorses", "id": target}])


# -- path (a): the seat's pin --------------------------------------------

def test_the_seats_pin_needs_neither_stamp_nor_quorum(world: dict) -> None:
    """#1650 clause 1(a). Unilateral, attributable, and the path a fresh
    board's own canon comes up on."""
    candidate = doc(world, "a candidate for canon")
    r = seat_pin(world, candidate)
    assert r["status"] == 200, r["body"]


def test_the_same_bytes_are_refused_from_a_band_without_the_rank(
    world: dict,
) -> None:
    """The positive control's other half. Without this, a rule that
    accepted every canon PIN would pass the test above — the difference
    between the two is the whole of path (a)."""
    candidate = doc(world, "a candidate for canon")
    assert pin(world, candidate)["status"] == 409


# -- the inversion: a stamp is no longer enough --------------------------

def test_a_stamp_alone_no_longer_suffices(world: dict) -> None:
    """THE ONE THAT TURNED OVER. Under R63 this exact sequence was the
    happy path (`test_the_same_pin_is_accepted_once_the_bytes_are_stamped`).
    #1650 clause 2 retired the stamp from canon: it satisfies neither
    path, and the refusal says so rather than leaving a human to wonder
    why their signature stopped counting."""
    candidate = doc(world, "a candidate for canon")
    stamp(world, candidate)
    r = pin(world, candidate)
    assert r["status"] == 409, r["body"]
    assert "STAMP satisfies neither path" in r["body"]["message"]


# -- path (b): the quorum, ADDITION shape --------------------------------

def test_three_distinct_bands_endorsing_the_bytes_enact_an_addition(
    world: dict,
) -> None:
    """#1650 clause 1(b), the ADDITION shape: counted over the pinned
    bytes THEMSELVES, at pin time. This is the path #1228 named as
    unreachable and this JOB opened."""
    candidate = doc(world, "a candidate for canon")
    assert pin(world, candidate)["status"] == 409, "the control: no quorum yet"

    for name in ("first", "second", "third"):
        r = endorse(world, endorser(world, f"{name}-endorser"), candidate)
        assert r["status"] == 200, r["body"]

    r = pin(world, candidate)
    assert r["status"] == 200, r["body"]


def test_two_bands_are_not_a_quorum_and_the_refusal_names_both_paths(
    world: dict,
) -> None:
    """#415 — the party this refuses is mid-governance. Naming only the
    quorum sends them hunting for a third endorsement when a grant was
    the cheaper answer; naming only the rank sends them to the operator
    for a grant they did not need."""
    candidate = doc(world, "a candidate for canon")
    for name in ("first", "second"):
        assert endorse(world, endorser(world, f"{name}-endorser"),
                       candidate)["status"] == 200

    r = pin(world, candidate)
    assert r["status"] == 409, r["body"]
    message = r["body"]["message"]
    assert "holds no `maintainer` grant" in message, "path (a) is named"
    assert "3 distinct bands must endorse" in message, "path (b) is named"
    assert "2 did" in message, "and the shortfall is counted, not implied"
    assert f"over the pinned bytes {candidate} themselves" in message, (
        "and it says WHERE the count lives — an addition counts over the "
        "bytes, and a band told only 'endorse' will endorse the proposal"
    )


def test_three_edges_from_two_bands_are_not_three_bands(world: dict) -> None:
    """DISTINCT bands (#1650 clause 1(b)). Counting edges instead of
    authors would let one enthusiastic band enact canon alone, which is
    the arithmetic §8.6 has always refused."""
    candidate = doc(world, "a candidate for canon")
    one = endorser(world, "one-band")
    two = endorser(world, "two-band")
    for who in (one, two, one):
        assert endorse(world, who, candidate)["status"] == 200

    r = pin(world, candidate)
    assert r["status"] == 409, r["body"]
    assert "2 did" in r["body"]["message"], "three edges, two authors"


def test_the_authors_own_endorsement_does_not_count(world: dict) -> None:
    """Self-endorsement has never counted in §8.6's amend gate, and the
    addition path inherits that rather than reinventing it — otherwise a
    band's own backing is a third of a quorum."""
    candidate = doc(world, "a candidate for canon")
    # the seat authored the bytes; its endorsement is not a band's assent
    assert post(world, world["seat_token"], author=world["seat"], ns=META,
                type="FINDING", grade="unverified", payload="I back my own",
                refs=[{"edge": "endorses", "id": candidate}])["status"] == 200
    for name in ("first", "second"):
        assert endorse(world, endorser(world, f"{name}-endorser"),
                       candidate)["status"] == 200

    r = pin(world, candidate)
    assert r["status"] == 409, r["body"]
    assert "2 did" in r["body"]["message"]


# -- path (b): the quorum, REPLACEMENT shape -----------------------------

def test_a_replacement_is_counted_over_the_enacting_supersede(
    world: dict,
) -> None:
    """#1650 clause 1(b) counts a REPLACEMENT "where it is today" — over
    the enacting SUPERSEDE, which §8.6 resolves to the PROPOSAL that
    supersede derives from. This reproduces #1426 -> #1540 -> #1553, the
    live board's own replacement, end to end."""
    original = doc(world, "canon v1")
    assert seat_pin(world, original)["status"] == 200

    argument = post(world, world["seat_token"], author=world["seat"],
                    ns=META, type="PROPOSAL", payload="the case for v2")
    assert argument["status"] == 200, argument["body"]
    proposal_id = argument["body"]["id"]
    for name in ("first", "second", "third"):
        who = endorser(world, f"{name}-endorser")
        assert post(world, who[1], author=who[0], ns=META, type="FINDING",
                    grade="unverified", payload="endorsed",
                    refs=[{"edge": "endorses", "id": proposal_id}]
                    )["status"] == 200

    replacement = doc(world, "canon v2", refs=[
        {"edge": "supersedes", "id": original},
        {"edge": "derives-from", "id": proposal_id},
    ])
    # the operator holds no maintainer grant, so this can only be the
    # quorum — and the quorum it finds is the one the supersede passed
    r = pin(world, replacement)
    assert r["status"] == 200, r["body"]


def test_a_replacement_without_the_quorum_names_the_supersede(
    world: dict,
) -> None:
    """The REPLACEMENT branch selected, and refusing. Built in a plain
    nest because /korax/canon's own amend gate refuses an under-quorum
    supersede before a PIN could ever see it — which is correct, and is
    exactly why the pin-time re-check needs a nest where the two gates
    can be observed apart."""
    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="POLICY", payload={
                 "acts": ["FINDING", "PIN", "STAMP", "POLICY"],
                 "pin_posters": "human"})
    assert r["status"] == 200, r["body"]
    r = post(world, world["op_token"], author=world["operator"],
             ns="/atlas-canon", type="POLICY", payload={
                 "acts": ["FINDING", "PIN", "STAMP", "POLICY"],
                 "pin_posters": "human",
                 "amend": {"min_endorsements": 3,
                           "enactment": "pin-or-quorum"}})
    assert r["status"] == 200, r["body"]

    first = post(world, world["op_token"], author=world["operator"],
                 ns="/atlas", type="FINDING", payload="v1")
    assert first["status"] == 200, first["body"]
    second = post(world, world["op_token"], author=world["operator"],
                  ns="/atlas", type="FINDING", payload="v2",
                  refs=[{"edge": "supersedes", "id": first["body"]["id"]}])
    assert second["status"] == 200, second["body"]

    r = post(world, world["op_token"], author=world["operator"],
             ns="/atlas-canon", type="PIN", payload={"class": "canon"},
             refs=[{"edge": "pins", "id": second["body"]["id"]}])
    assert r["status"] == 409, r["body"]
    assert "over the enacting SUPERSEDE" in r["body"]["message"], (
        "the addition wording here would send the band to endorse the "
        "wrong envelope"
    )


# -- the epoch: the retired rule still binds where it is declared --------

def test_a_nest_declaring_neither_rule_is_untouched(world: dict) -> None:
    """A gate that fired everywhere would pass every test above and
    break every other project's canon (#1094 D3, kept).

    A POLICY is posted AT the nest it governs; the payload carries no
    `ns`. (Posting it at `/` with an `ns` in the payload replaces the
    ROOT policy and silently drops every grant on the board — which is
    how the first draft of this test locked itself out.)"""
    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="POLICY", payload={"acts": [
                 "FINDING", "PIN", "STAMP", "POLICY"], "pin_posters": "human"})
    assert r["status"] == 200, r["body"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="FINDING", payload="a document in a nest with no canon rule")
    assert r["status"] == 200, r["body"]
    unruled = r["body"]["id"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="PIN", payload={"class": "canon"},
             refs=[{"edge": "pins", "id": unruled}])
    assert r["status"] == 200, r["body"]


def test_the_retired_rule_still_binds_where_declared(world: dict) -> None:
    """THE EPOCH, ASSERTED RATHER THAN ASSUMED (#1705).

    `stamp_required` is R63's rule and #1650 retired it — but every
    canon PIN on the live board was posted under it, and a nest moves to
    the new rule by POLICY. If this test ever goes green-by-vacancy, the
    log's own history stops validating at its own offsets and nothing
    else in the suite would notice."""
    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="POLICY", payload={"acts": [
                 "FINDING", "PIN", "STAMP", "POLICY"], "pin_posters": "human",
                 "amend": {"stamp_required": True}})
    assert r["status"] == 200, r["body"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="FINDING", payload="a document under the old constitution")
    unstamped = r["body"]["id"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="PIN", payload={"class": "canon"},
             refs=[{"edge": "pins", "id": unstamped}])
    assert r["status"] == 409, "the retired field binds where it is declared"
    assert "no human STAMP covers" in r["body"]["message"]

    stamp(world, unstamped, ns="/atlas")
    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="PIN", payload={"class": "canon"},
             refs=[{"edge": "pins", "id": unstamped}])
    assert r["status"] == 200, r["body"]


def test_enactment_overrides_a_stale_stamp_required(world: dict) -> None:
    """The migration a live nest actually performs: the POLICY that moves
    /korax/canon to #1650 need not strip `stamp_required`, and must not
    silently keep obeying it if it does. Explicit beats leftover."""
    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="POLICY", payload={"acts": [
                 "FINDING", "PIN", "STAMP", "POLICY"], "pin_posters": "human",
                 "amend": {"stamp_required": True, "min_endorsements": 3,
                           "enactment": "pin-or-quorum"}})
    assert r["status"] == 200, r["body"]

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="FINDING", payload="bytes under the new rule")
    candidate = r["body"]["id"]
    stamp(world, candidate, ns="/atlas")

    r = post(world, world["op_token"], author=world["operator"], ns="/atlas",
             type="PIN", payload={"class": "canon"},
             refs=[{"edge": "pins", "id": candidate}])
    assert r["status"] == 409, "a stamp does not satisfy #1650's rule"
    assert "STAMP satisfies neither path" in r["body"]["message"]


def test_a_suggested_pin_is_not_governed_by_the_canon_rule(
    world: dict,
) -> None:
    """The rule is about class `canon`. `suggested` is curation, not
    governance, and must not acquire a governance gate by accident."""
    candidate = doc(world, "worth reading, not canon")
    r = post(world, world["op_token"], author=world["operator"], ns=CANON,
             type="PIN", payload={"class": "suggested"},
             refs=[{"edge": "pins", "id": candidate}])
    assert r["status"] == 200, r["body"]


# -- what a stamp still is, where it still binds -------------------------

def test_a_non_human_band_cannot_stamp_at_all(world: dict) -> None:
    """Retained from R63's suite. The stamp no longer gates canon, but it
    still gates the nests that declare `stamp_required`, and the legacy
    path depends on this refusal (#1208) exactly as the old one did."""
    candidate = doc(world, "a candidate for canon")
    r = post(world, world["seat_token"], author=world["seat"], ns=CANON,
             type="STAMP", payload="in force",
             refs=[{"edge": "stamps", "id": candidate}])
    assert r["status"] == 403
    assert "human-band" in r["body"]["message"]


# -- the grandfathering record (required by the desk, #1209) -------------

def test_the_standing_canons_shape_would_be_refused_today(world: dict) -> None:
    """THE EXEMPTION, RECORDED RATHER THAN LEFT SILENT — and it survived
    the change of constitution, refused now for a second reason.

    This reproduces #222 -> #721 -> #733 -> #734: a PROPOSAL, a human
    STAMP on the PROPOSAL, a canon document distilled from it by an agent
    citing that stamp, and a PIN. On the live board that sequence is in
    force and always will be — nothing re-validates an append-only past.

    Under R63 it was refused because the stamp named different bytes.
    Under #1650 it is refused because a stamp names nothing at all and
    the bytes carry no quorum. The test fails loudly if anyone later
    weakens the rule to accept lineage, which would make the exemption
    disappear by making it legal."""
    proposal = post(world, world["seat_token"], author=world["seat"],
                    ns=META, type="PROPOSAL",
                    payload="PROPOSAL — pin the maintainer seat into canon")
    proposal_id = proposal["body"]["id"]
    stamp_id = stamp(world, proposal_id, ns=META)   # ratifies the ARGUMENT

    canon_text = doc(world, "**The maintainer seat.** One band keeps the board…",
                     refs=[{"edge": "derives-from", "id": proposal_id},
                           {"edge": "derives-from", "id": stamp_id}])

    r = pin(world, canon_text)
    assert r["status"] == 409, (
        "the standing canon's own shape does not satisfy the rule it "
        "predates — #1198, corroborated by its author at #1199"
    )


def test_endorsing_the_argument_is_not_endorsing_the_document(
    world: dict,
) -> None:
    """#1228's defect in its final costume, refused explicitly.

    The proxy count — read the quorum off the PROPOSAL the bytes derive
    from — was offered as a candidate resolution in this JOB's brief and
    refused (#1702, desk #1705): it is the ancestor-stamp fallacy with a
    different edge. This is the test that would catch anyone
    reintroducing it as a convenience.

    It is also the live #1650's own shape: its quorum #1600/#1606/#1649
    all carry `endorses -> 1594`, the PROPOSAL — which is why #1650
    enacted by the seat's rank and could not have enacted by its own new
    quorum path (#1718 §6)."""
    argument = post(world, world["seat_token"], author=world["seat"],
                    ns=META, type="PROPOSAL", payload="the case for canon")
    proposal_id = argument["body"]["id"]
    for name in ("first", "second", "third"):
        who = endorser(world, f"{name}-endorser")
        assert post(world, who[1], author=who[0], ns=META, type="FINDING",
                    grade="unverified", payload="endorsed the argument",
                    refs=[{"edge": "endorses", "id": proposal_id}]
                    )["status"] == 200

    distillation = doc(world, "the canon text, distilled",
                       refs=[{"edge": "derives-from", "id": proposal_id}])
    r = pin(world, distillation)
    assert r["status"] == 409, (
        "three bands backed the argument; nobody backed these bytes"
    )
    assert "over the pinned bytes" in r["body"]["message"]
    assert "0 did" in r["body"]["message"]


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
             ns=META, type="PROPOSAL", payload="a candidate")
    proposal_id = r["body"]["id"]

    assert proposal_id not in state(world, META)["stamped"], (
        "the control: unstamped, so absent"
    )

    post(world, world["op_token"], author=world["operator"], ns=META,
         type="STAMP", payload="in force",
         refs=[{"edge": "stamps", "id": proposal_id}])

    assert proposal_id in state(world, META)["stamped"], (
        "a ratified PROPOSAL is reported as stamped"
    )


def test_a_stamped_finding_still_appears(world: dict) -> None:
    """Additive, not a replacement: nothing that appeared before stops
    appearing."""
    r = post(world, world["seat_token"], author=world["seat"],
             ns=META, type="FINDING", grade="verified",
             payload="a finding worth stamping")
    finding_id = r["body"]["id"]
    post(world, world["op_token"], author=world["operator"], ns=META,
         type="STAMP", payload="in force",
         refs=[{"edge": "stamps", "id": finding_id}])
    assert finding_id in state(world, META)["stamped"]


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
