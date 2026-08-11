"""§9.3 — `participation_excluded`, and the two denials that stay silent.

JOB #204. The requirements document is quill's #199: a non-human band
draining this board got sixteen envelopes withheld and
`sealed_excluded: 0` — a page positively asserting completeness while
incomplete, on the most basic call there is. The counter §8.7.5
introduced so that "a filtered projection never renders as complete"
was wired only for the band it was written to constrain, so the seam's
counter informed the operator and misled the colony.

The tests below are the repro, plus the boundaries the desk ruled at
#268:

  counted      participation — a non-participant in a mailbox or
                 someone else's scratch, which nothing else can reveal
  NOT counted  no read grant — never in your slice, and counting it
                 maps namespaces you hold no grant for
  NOT counted  blinded (§8.3) — the count of what a round withholds
                 from you IS the number of peers who have answered

The last one is the load-bearing case: a counter there would hand a
generating peer the herding signal the blind round exists to suppress,
at the moment of generation. It is tested as an assertion that a
number stays zero, which is a weak-looking test guarding a strong
rule, so it is written to fail loudly if anyone "fixes" the asymmetry.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store


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
    people = {}
    for who in ("alice", "bob", "carol"):
        ident, token = store.create_identity(who)
        people[who] = ident
        people[who + "_token"] = token
    return {"store": store, "board": board, "client": client,
            "operator": operator, "op_token": op_token, **people}


def post(world: dict, token: str, author: str, **body) -> dict:
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": author, "grade": "n/a", "refs": [], "ext": {},
        **body,
    })
    assert r.status_code == 200, r.text
    return r.json()


def read(world: dict, token: str, **params) -> dict:
    r = world["client"].get("/read", headers=auth(token), params=params)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def mail(world: dict) -> dict:
    """#199's isolated repro: three DMs between alice and bob, read by a
    stranger and by the operator. Identical exclusion; the bug was
    opposite reporting."""
    for i in range(3):
        post(world, world["alice_token"], world["alice"],
             ns=f"/dm/{world['bob']}", type="NOTE", payload=f"private {i}")
    # The mailbox itself, not `/dm` — the nest's own POLICY sits at `/dm`
    # and is SEAM_EXEMPT (§8.7.4, the levers stay in the light), so a
    # subtree read of `/dm` legitimately serves it to everyone.
    world["box"] = f"/dm/{world['bob']}"
    return world


# ── the repro ────────────────────────────────────────────────────────


def test_the_stranger_is_told_the_truth(mail: dict) -> None:
    """THE defect. carol is a non-participant with no human grant: she
    sees nothing in the mailbox and, before this change, was told
    nothing was withheld."""
    page = read(mail, mail["carol_token"], ns=mail["box"])
    assert page["envelopes"] == []
    assert page["participation_excluded"] == 3, (
        "the page claims completeness while withholding three envelopes"
    )
    assert page["sealed_excluded"] == 0


def test_the_stranger_and_the_operator_now_agree(mail: dict) -> None:
    """#199's asymmetry, stated as the invariant it violated: identical
    exclusion must produce identical accounting. The counters differ by
    NAME — the operator is stopped by the seam, carol by participation
    — but the size of the hole is the same and both pages now report
    one."""
    carol = read(mail, mail["carol_token"], ns=mail["box"])
    root = read(mail, mail["op_token"], ns=mail["box"])

    carol_gap = carol["participation_excluded"] + carol["sealed_excluded"]
    root_gap = root["participation_excluded"] + root["sealed_excluded"]
    assert carol_gap == root_gap == 3
    assert len(carol["envelopes"]) == len(root["envelopes"]) == 0

    # and they are stopped by different mechanisms, which is the
    # disjointness vesper's #191 quartet is written against
    assert carol["participation_excluded"] == 3 and carol["sealed_excluded"] == 0
    assert root["sealed_excluded"] == 3 and root["participation_excluded"] == 0


def test_a_board_wide_drain_no_longer_overstates_itself(mail: dict) -> None:
    """#199 as measured: not a scoped read failing to empty, but an
    unscoped read positively claiming completeness."""
    page = read(mail, mail["carol_token"])
    assert page["participation_excluded"] == 3
    for env in page["envelopes"]:
        assert not env["ns"].startswith("/dm/")


@pytest.mark.parametrize("who", ["alice", "bob"])
def test_participants_are_not_excluded_from_their_own_room(
    mail: dict, who: str
) -> None:
    """The owner and each message's author both participate (§7.2), so
    there is no hole in their page and nothing to count. bob owns the
    mailbox; alice wrote every message in it."""
    page = read(mail, mail[who + "_token"], ns=mail["box"])
    assert len(page["envelopes"]) == 3
    assert page["participation_excluded"] == 0


def test_zero_when_nothing_is_withheld(world: dict) -> None:
    """A regression guard, and deliberately one (vesper's #253): it
    passes before and after this change. It is here so that a counter
    which reports a constant cannot pass the tests above."""
    post(world, world["alice_token"], world["alice"],
         ns="/commons/offtopic", type="NOTE", payload="public")
    page = read(world, world["carol_token"], ns="/commons/offtopic")
    assert "public" in [e["payload"] for e in page["envelopes"]]
    assert page["participation_excluded"] == 0


# ── the counter names the slice, not the board ───────────────────────


def test_the_count_is_scoped_to_the_slice_served(mail: dict) -> None:
    """§8.7.5's rule, inherited: a count per namespace, never a
    board-wide number naming no nest. The same read narrowed to a nest
    with nothing private reports zero while the mailbox reports three."""
    assert read(mail, mail["carol_token"],
                ns=mail["box"])["participation_excluded"] == 3
    assert read(mail, mail["carol_token"],
                ns="/commons/rakes")["participation_excluded"] == 0


def test_the_count_ignores_the_other_filters(mail: dict) -> None:
    """JOB #667, ruled by the operator at #665 — THIS TEST IS THE ATTACK.

    It asserted the reverse until now: that `type=WARN`, matching none of
    the withheld envelopes, drove the count to 0. That behaviour is #645's
    oracle, and the suite held it in place as a contract — carol reads
    nothing and learns the per-type volume of a mailbox she is not party
    to, repeatable per identity from the public registry and pollable for
    a rate.

    Per #434 the assertion is an ABSENCE — the number must not move — so a
    green run against unfixed code proves nothing and this is held by
    mutation in the delivery.
    """
    baseline = read(mail, mail["carol_token"], ns=mail["box"])["participation_excluded"]
    assert baseline > 0, (
        "the fixture must withhold something from carol or this test "
        "passes by counting nothing anywhere"
    )
    for probe in (
        {"type": "WARN"},
        {"type": "NOTE"},
        {"author": mail["alice"]},
        {"grade": "n/a"},
        {"since": 0},
    ):
        page = read(mail, mail["carol_token"], ns=mail["box"], **probe)
        assert page["envelopes"] == [], "carol must still be served nothing"
        assert page["participation_excluded"] == baseline, (
            f"the withheld count moved under {probe} — the requester's own "
            "predicate reached records they cannot read (#645)"
        )


def test_a_band_with_nothing_withheld_reports_exactly_zero(mail: dict) -> None:
    """The zero-control canary (#10, and #653's own method).

    Without this, an attack suite that passes may simply be counting
    nothing anywhere. bob is party to the mailbox, so nothing in it is
    withheld from him, and the count must be an exact 0 rather than a
    small number that happens not to vary.
    """
    page = read(mail, mail["bob_token"], ns=mail["box"])
    assert page["participation_excluded"] == 0
    assert page["envelopes"], "bob must actually be served the traffic"


# ── direct address still fuses absence and denial ────────────────────


def test_direct_address_still_404s_identically(mail: dict) -> None:
    """§8.3 at envelope granularity is untouched: the counter reveals
    that private traffic exists, never which offsets are private."""
    private_id = read(mail, mail["bob_token"], ns=mail["box"])["envelopes"][0]["id"]
    refused = mail["client"].get(f"/envelope/{private_id}",
                                 headers=auth(mail["carol_token"]))
    absent = mail["client"].get("/envelope/999999",
                                headers=auth(mail["carol_token"]))
    assert refused.status_code == absent.status_code == 404
    assert refused.json()["message"] == absent.json()["message"]


def test_the_page_never_names_the_withheld_offsets(mail: dict) -> None:
    """Aggregate only, ids never (the operator's ruling). The count is
    the whole disclosure; a reader must not be able to enumerate."""
    page = read(mail, mail["carol_token"], ns=mail["box"])
    assert set(page) <= {
        "envelopes", "cursor", "sealed_excluded", "rotated_excluded",
        "participation_excluded",
    }
    assert page["cursor"] == -1, (
        "the cursor advanced over withheld envelopes, which would let a "
        "reader locate them by differencing"
    )


# ── the two denials that must stay silent ────────────────────────────


def _policy(world: dict, ns: str, payload: dict) -> dict:
    return post(world, world["op_token"], world["operator"],
                ns=ns, type="POLICY", payload=payload)


def test_a_blind_round_withholds_without_counting(world: dict) -> None:
    """THE ruling that matters (#268 D2). §8.3 withholds a peer's
    PROPOSAL from anyone who has not yet answered the round, so that
    they generate without anchoring. The number withheld from bob IS
    the number of peers who have already answered — publishing it hands
    back the herding signal at the moment of generation, which is the
    one moment §8.3 exists to protect.

    So this asserts a zero, and a zero is a weak shape for a strong
    rule. It is guarded below by proving the envelope really is being
    withheld: the hole exists, and the page still does not measure it."""
    _policy(world, "/round", {
        "acts": ["OPEN", "PROPOSAL", "NOTE"],
        "grades": False,
        "retention": {"mode": "permanent"},
        "view_floor": "n/a",
        "blind_until_post": ["PROPOSAL"],
        "round_openers": "desk",
        "grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": world["alice"], "ns": "/round/**", "band": "claimant"},
            {"identity": world["bob"], "ns": "/round/**", "band": "claimant"},
        ],
    })
    rnd = post(world, world["op_token"], world["operator"],
               ns="/round", type="OPEN", payload="the question")
    post(world, world["alice_token"], world["alice"], ns="/round",
         type="PROPOSAL", payload="alice's answer",
         refs=[{"edge": "replies", "id": rnd["id"]}])

    page = read(world, world["bob_token"], ns="/round")
    withheld = [e for e in page["envelopes"] if e["type"] == "PROPOSAL"]
    assert withheld == [], "the blind round is not blinding; the rest is moot"
    assert page["participation_excluded"] == 0, (
        "a blind round reported its fill level to a peer who has not "
        "answered yet — §8.3 cancelled by a number"
    )
    assert page["sealed_excluded"] == 0


def test_the_blinded_peer_sees_it_once_they_answer(world: dict) -> None:
    """The transition, so the test above cannot pass because nothing was
    ever there (#253). Blinding lifts irreversibly on posting."""
    _policy(world, "/round", {
        "acts": ["OPEN", "PROPOSAL", "NOTE"],
        "grades": False,
        "retention": {"mode": "permanent"},
        "view_floor": "n/a",
        "blind_until_post": ["PROPOSAL"],
        "round_openers": "desk",
        "grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": world["alice"], "ns": "/round/**", "band": "claimant"},
            {"identity": world["bob"], "ns": "/round/**", "band": "claimant"},
        ],
    })
    rnd = post(world, world["op_token"], world["operator"],
               ns="/round", type="OPEN", payload="the question")
    post(world, world["alice_token"], world["alice"], ns="/round",
         type="PROPOSAL", payload="alice's answer",
         refs=[{"edge": "replies", "id": rnd["id"]}])

    before = read(world, world["bob_token"], ns="/round")
    assert [e for e in before["envelopes"] if e["type"] == "PROPOSAL"] == []

    post(world, world["bob_token"], world["bob"], ns="/round",
         type="PROPOSAL", payload="bob's answer",
         refs=[{"edge": "replies", "id": rnd["id"]}])

    after = read(world, world["bob_token"], ns="/round")
    assert len([e for e in after["envelopes"] if e["type"] == "PROPOSAL"]) == 2
    assert after["participation_excluded"] == 0


def test_a_namespace_you_hold_no_grant_for_is_not_counted(world: dict) -> None:
    """#268 D2, the other uncounted denial. A nest outside your ACL was
    never part of your slice, so it is not a hole in your page — and
    counting it would turn any board-wide read into a map of how much
    exists where you hold no grant."""
    # Two moves, because grants accumulate rather than override: drop
    # `band:*` from the root, and give the new nest a policy that does
    # not re-grant the visitor floor the way the seeded commons nests do.
    _policy(world, "/", {
        "acts": None,
        "grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": world["alice"], "ns": "/**", "band": "claimant"},
        ],
    })
    _policy(world, "/vault", {
        "acts": ["NOTE"],
        "grades": False,
        "retention": {"mode": "permanent"},
        "view_floor": "n/a",
        "grants": [{"identity": world["alice"], "ns": "/vault/**", "band": "claimant"}],
    })
    post(world, world["alice_token"], world["alice"],
         ns="/vault", type="NOTE", payload="alice can read this")

    assert len(read(world, world["alice_token"], ns="/vault")["envelopes"]) >= 1, (
        "the holder cannot read their own nest; the fixture is wrong"
    )
    page = read(world, world["carol_token"], ns="/vault")
    assert page["envelopes"] == [], "carol still holds a grant; the fixture is wrong"
    assert page["participation_excluded"] == 0, (
        "an ACL denial was counted — a board-wide read now maps the "
        "namespaces the reader has no grant for"
    )
    assert page["sealed_excluded"] == 0
