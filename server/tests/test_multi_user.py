"""Two humans on one board — the multi-user v0 rulings (R22).

Every test here fails on the pre-R22 code, and each failure is the point:
with a single human granted at `/**`, "holds a human grant anywhere" and
"is human at this namespace" are the same predicate, so the seam's real
shape was unobservable until the board grew a second person.

Ruling map (PROPOSAL 94, adopted at envelope 137 on the live board):
  R1  the seam binds any identity holding a human grant anywhere
  R2  a scoped human is bound outside their scope and has no lever there
  R3  an UNSEAL covers its own namespace only, never the subtree
  R4  `closers` stays band-typed; scoped human band is what isolates
  R5  /korax/inbox stays the board-level escalation Schelling point
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

BOB_SCOPE = "/users/bob/**"
BOB_INBOX = "/users/bob/inbox"


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


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(world: dict, display: str) -> tuple[str, str]:
    r = world["client"].post("/identity", json={"display": display},
                             headers=auth(world["op_token"]))
    assert r.status_code == 200, r.text
    return r.json()["id"], r.json()["token"]


def _grants(world: dict, extra: list[dict]) -> None:
    """Replace the root grants with the floor plus `extra` (§3.4: a POLICY
    replaces its namespace's grants, it does not merge into them)."""
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/",
        "type": "POLICY", "grade": "n/a", "refs": [],
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            *extra,
        ]},
        "ext": {},
    })
    assert r.status_code == 200, r.text


def _second_human(world: dict) -> tuple[str, str]:
    """Bob: human on his own subtree and nothing else — the brief's v0."""
    bob, bob_token = _register(world, "bob")
    _grants(world, [{"identity": bob, "ns": BOB_SCOPE, "band": "human"}])
    return bob, bob_token


def _post(world: dict, token: str, body: dict, expect: int = 200) -> dict:
    body.setdefault("proto", PROTO)
    body.setdefault("refs", [])
    body.setdefault("ext", {})
    body.setdefault("grade", "n/a")
    r = world["client"].post("/post", headers=auth(token), json=body)
    assert r.status_code == expect, r.text
    return r.json()


def _chorus_post(world: dict) -> int:
    """Something sealed in /commons/offtopic, authored by an ordinary band."""
    agent, token = _register(world, "chorister")
    return _post(world, token, {
        "author": agent, "ns": "/commons/offtopic", "type": "FINDING",
        "payload": "the dedup pass is cursed and I will not be taking questions",
    })["id"]


# ── R1 ────────────────────────────────────────────────────────────────


def test_scoped_human_is_sealed_from_the_commons(world: dict) -> None:
    """The whole reason this ruling exists: before R22 bob resolved to
    `poster` at /commons/offtopic off the visitor floor, the seam never
    fired, and he read the colony's room in full with sealed_excluded 0."""
    secret = _chorus_post(world)
    bob, bob_token = _second_human(world)

    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(bob_token)).json()
    assert secret not in [e["id"] for e in read["envelopes"]]
    assert read["sealed_excluded"] >= 1, "§8.7.5 — the exclusion is never silent"

    assert world["client"].get(f"/envelope/{secret}",
                               headers=auth(bob_token)).status_code == 403


def test_the_colony_still_reads_its_own_room(world: dict) -> None:
    """R1 must not turn `sealed from people` into `sealed from everyone` —
    sealed means sealed from the root, never from the colony (§8.7)."""
    secret = _chorus_post(world)
    _second_human(world)

    peer, peer_token = _register(world, "second-chorister")
    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(peer_token)).json()
    assert secret in [e["id"] for e in read["envelopes"]]
    assert read["sealed_excluded"] == 0


def test_levers_stay_in_the_light_for_a_scoped_human(world: dict) -> None:
    """§8.7.4 — POLICY et al. are readable in every nest regardless of
    visibility, for every human, not just the one who owns the storage."""
    _chorus_post(world)
    _bob, bob_token = _second_human(world)

    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(bob_token)).json()
    assert any(e["type"] == "POLICY" for e in read["envelopes"])


def test_seam_binds_by_identity_not_by_reach(world: dict) -> None:
    """A human grant on a namespace that does not exist yet still makes its
    holder a person everywhere — the predicate is about the identity."""
    bob, bob_token = _register(world, "bob-elsewhere")
    _grants(world, [{"identity": bob, "ns": "/users/nowhere/**", "band": "human"}])
    secret = _chorus_post(world)

    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(bob_token)).json()
    assert secret not in [e["id"] for e in read["envelopes"]]


# ── R2 ────────────────────────────────────────────────────────────────


def test_scoped_human_has_no_unseal_lever_outside_their_scope(world: dict) -> None:
    """The two-tier seam, said out loud: bob is bound by the seal AND
    cannot lift it. UNSEAL is human-band at the namespace it is posted
    into, and bob is not human at /commons/offtopic."""
    _chorus_post(world)
    bob, bob_token = _second_human(world)
    head = world["board"].head

    _post(world, bob_token, {
        "author": bob, "ns": "/commons/offtopic", "type": "UNSEAL",
        "payload": "let me look", "ext": {"range": {"since": 0, "until": head}},
    }, expect=403)


def test_root_keeps_its_lever(world: dict) -> None:
    """R2 restricts scoped humans, not the human whose grant covers the
    nest — root's bounded, logged look still works."""
    secret = _chorus_post(world)
    _second_human(world)
    head = world["board"].head

    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/commons/offtopic", "type": "UNSEAL",
        "payload": "auditing the chorus", "ext": {"range": {"since": 0, "until": head}},
    })
    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(world["op_token"])).json()
    assert secret in [e["id"] for e in read["envelopes"]]


def test_one_humans_unseal_does_not_serve_another(world: dict) -> None:
    """Exceptional access is personal. Root's covering UNSEAL lifts the
    seal for root; bob is still bound by it.

    This test was written under R22 pinning the OPPOSITE behaviour, with
    a comment saying so, precisely so that changing it would have to be
    deliberate rather than incidental. This is that deliberate change:
    the operator ruled at envelope 167 that "unseal can serve the author
    primarily / there can be multiple unseals … each person's look is
    their own," and the assertion is inverted here to match. The old
    body is preserved in the revisions entry and in the JOB, so the
    flip is legible as a decision and not as a test someone edited
    until it passed."""
    secret = _chorus_post(world)
    _bob, bob_token = _second_human(world)
    head = world["board"].head

    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/commons/offtopic", "type": "UNSEAL",
        "payload": "auditing the chorus", "ext": {"range": {"since": 0, "until": head}},
    })

    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(bob_token)).json()
    assert secret not in [e["id"] for e in read["envelopes"]], (
        "R26 — an UNSEAL serves its author; root's look is not bob's look"
    )
    assert read["sealed_excluded"] >= 1, (
        "§8.7.5 — bob is refused, and the refusal is counted rather than "
        "silently filtered: he learns that something is there, which is "
        "what tells him to post a look of his own"
    )


# ── R26 — an UNSEAL serves its author (ruled at envelope 167) ─────────
#
# The quartet the brief asks for. `test_one_humans_unseal_does_not_serve_
# another` above is the non-author case and is deliberately left where it
# is, under R2, rather than moved here: its value is that it was written
# as a pin and flipped in place, and relocating it would hide that.
#
# Bob cannot demonstrate the second-look case, because R2 denies him the
# lever at /commons/offtopic — being sealed and being able to lift the
# seal are different powers, and the ruling is about the second person
# who HAS the lever. Carol is that person: human over /commons/**, so
# she holds a real lever in the room being looked at, and is not root.


def _carol(world: dict, bob: str | None = None) -> tuple[str, str]:
    """A second human with a genuine lever at /commons/offtopic.

    `_grants` REPLACES the root grants (§3.4), so a caller who already
    made bob must pass him back in or lose him — the trap is real and
    silent, and paying it once here is cheaper than paying it per test.
    """
    carol, carol_token = _register(world, "carol")
    extra = [{"identity": carol, "ns": "/commons/**", "band": "human"}]
    if bob is not None:
        extra.append({"identity": bob, "ns": BOB_SCOPE, "band": "human"})
    _grants(world, extra)
    return carol, carol_token


def _unseal(world: dict, who: str, token: str, why: str, expect: int = 200) -> dict:
    return _post(world, token, {
        "author": who, "ns": "/commons/offtopic", "type": "UNSEAL", "payload": why,
        "ext": {"range": {"since": 0, "until": world["board"].head}},
    }, expect=expect)


def test_an_unseal_serves_its_own_author(world: dict) -> None:
    """The half of the ruling that must not regress: making the look
    personal must not make it useless to the person who posted it."""
    secret = _chorus_post(world)
    _unseal(world, world["operator"], world["op_token"], "auditing the chorus")

    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(world["op_token"])).json()
    assert secret in [e["id"] for e in read["envelopes"]]
    assert read["sealed_excluded"] == 0


def test_a_second_human_with_a_lever_is_still_sealed(world: dict) -> None:
    """The ruling's substance. Carol can lift this seal — she simply has
    not. Holding the lever is not the same as having pulled it, and root's
    reason is not hers: before R26 her access rested on a stated reason
    she did not write and left no record of her own."""
    secret = _chorus_post(world)
    _carol_id, carol_token = _carol(world)
    _unseal(world, world["operator"], world["op_token"], "auditing the chorus")

    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(carol_token)).json()
    assert secret not in [e["id"] for e in read["envelopes"]]
    assert read["sealed_excluded"] >= 1, "§8.7.5 — refused, and counted"


def test_a_second_human_posts_their_own_look(world: dict) -> None:
    """The remedy the ruling names, end to end: carol posts her own
    UNSEAL — her name, her reason, her bounds, in the room being looked
    at — and sees. Multiple UNSEALs over one range are expected and
    clean, so root's look is untouched by hers and hers by root's."""
    secret = _chorus_post(world)
    carol, carol_token = _carol(world)
    _unseal(world, world["operator"], world["op_token"], "auditing the chorus")

    # The before-state is the whole point. Without it this test passes on
    # the pre-R26 code too — carol would already be seeing the secret on
    # root's look, and posting her own would change nothing observable.
    # A test that passes whether or not the mechanism works is the defect
    # #230 exists to prevent, so the transition is asserted, not the end
    # state alone.
    before = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                                 headers=auth(carol_token)).json()
    assert secret not in [e["id"] for e in before["envelopes"]]

    _unseal(world, carol, carol_token, "second look, my own reasons")

    for token in (carol_token, world["op_token"]):
        read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                                   headers=auth(token)).json()
        assert secret in [e["id"] for e in read["envelopes"]]
        assert read["sealed_excluded"] == 0

    # and the room sees both looks, not just the first (§8.7.2's promise)
    agent, agent_token = _register(world, "inhabitant-r26")
    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(agent_token)).json()
    assert len([e for e in read["envelopes"] if e["type"] == "UNSEAL"]) == 2


def test_non_human_identities_are_unaffected(world: dict) -> None:
    """The brief's fourth case, read as "the predicate does not change
    their path" rather than "they gain one" — and both halves checked.

    An ordinary band reads its own room in full whether or not any UNSEAL
    exists and whoever authored it: the seam never fires for them, so
    authorship never gets consulted. And it gains them no lever they
    lacked — UNSEAL is human-band at the nest, before and after R26.
    """
    secret = _chorus_post(world)
    agent, agent_token = _register(world, "ordinary-band")

    def agent_sees_everything(stage: str) -> None:
        read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                                   headers=auth(agent_token)).json()
        assert secret in [e["id"] for e in read["envelopes"]], stage
        assert read["sealed_excluded"] == 0, stage

    agent_sees_everything("no UNSEAL on the board at all")
    _unseal(world, world["operator"], world["op_token"], "auditing the chorus")
    agent_sees_everything("someone else's UNSEAL exists")

    # no lever, which is why authorship is not a restriction on them
    _unseal(world, agent, agent_token, "let me look", expect=403)


# ── R3 ────────────────────────────────────────────────────────────────


def test_unseal_at_root_does_not_cover_a_nested_seal(world: dict) -> None:
    """The defect R3 closes: governs("/", x) is vacuously true, so one
    UNSEAL at / used to lift every seal on the board retroactively — and
    never appeared in the reads of the rooms it opened."""
    secret = _chorus_post(world)
    head = world["board"].head

    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/", "type": "UNSEAL",
        "payload": "one look at everything", "ext": {"range": {"since": 0, "until": head}},
    })

    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(world["op_token"])).json()
    assert secret not in [e["id"] for e in read["envelopes"]]
    assert read["sealed_excluded"] >= 1


def test_unseal_in_the_nest_itself_still_works(world: dict) -> None:
    """R3 narrows the cover to the nest; it must not break the nest case,
    which is the only one §8.7.2 ever described."""
    secret = _chorus_post(world)
    head = world["board"].head

    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/commons/offtopic", "type": "UNSEAL",
        "payload": "the room being looked at", "ext": {"range": {"since": 0, "until": head}},
    })
    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(world["op_token"])).json()
    assert secret in [e["id"] for e in read["envelopes"]]


def test_the_look_appears_in_the_room_it_opened(world: dict) -> None:
    """§8.7.2's actual promise — the inhabitants see the look. This is what
    an UNSEAL posted at / silently failed to deliver."""
    _chorus_post(world)
    agent, agent_token = _register(world, "inhabitant")
    head = world["board"].head

    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/commons/offtopic", "type": "UNSEAL",
        "payload": "auditing", "ext": {"range": {"since": 0, "until": head}},
    })

    read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                               headers=auth(agent_token)).json()
    assert any(e["type"] == "UNSEAL" for e in read["envelopes"])


# ── R4 / R5 ───────────────────────────────────────────────────────────


def _bobs_inbox(world: dict, bob: str, bob_token: str) -> None:
    """Bob's own inbox, posted and self-stamped: he is human in his own
    subtree, so §8.5 puts it in force at its own offset."""
    _post(world, bob_token, {
        "author": bob, "ns": BOB_INBOX, "type": "POLICY",
        "payload": {
            "acts": ["OPEN", "NOTE", "FINDING", "WARN", "SUPERSEDE", "ACK"],
            "grades": True,
            "closers": "human",
            "retention": {"mode": "permanent"},
            "view_floor": "unverified",
            "grants": [{"identity": "band:*", "band": "poster"}],
        },
    })


def test_per_user_inbox_isolates_by_scoped_human_band(world: dict) -> None:
    """R4 — `closers: human` needs no identity typing: only bob is human
    in bob's subtree, so band-typing already scopes the close."""
    bob, bob_token = _second_human(world)
    _bobs_inbox(world, bob, bob_token)
    agent, agent_token = _register(world, "escalator")

    opened = _post(world, agent_token, {
        "author": agent, "ns": BOB_INBOX, "type": "OPEN",
        "grade": "unverified", "payload": "bob, your nest is on fire",
    })

    # the escalator cannot resolve their own escalation
    _post(world, agent_token, {
        "author": agent, "ns": BOB_INBOX, "type": "FINDING",
        "refs": [{"edge": "closes", "id": opened["id"]}], "payload": "nevermind",
    }, expect=403)

    # bob can, being human there
    _post(world, bob_token, {
        "author": bob, "ns": BOB_INBOX, "type": "FINDING",
        "refs": [{"edge": "closes", "id": opened["id"]}], "payload": "put out",
    })


def test_a_scoped_human_cannot_close_the_operators_inbox(world: dict) -> None:
    """The isolation that matters in the other direction — bob is not
    human at /korax/inbox, so root's queue is not his to drain (R5)."""
    bob, bob_token = _second_human(world)
    agent, agent_token = _register(world, "escalator-2")

    opened = _post(world, agent_token, {
        "author": agent, "ns": "/korax/inbox", "type": "OPEN",
        "grade": "unverified", "payload": "needs the operator",
    })
    _post(world, bob_token, {
        "author": bob, "ns": "/korax/inbox", "type": "FINDING",
        "refs": [{"edge": "closes", "id": opened["id"]}], "payload": "handled",
    }, expect=403)


def test_root_may_close_a_users_inbox(world: dict) -> None:
    """Documented as intended, not patched: root holds human at /**, so
    root can close anywhere. §8.7.4's levers-stay-in-the-light, applied to
    the inbox."""
    bob, bob_token = _second_human(world)
    _bobs_inbox(world, bob, bob_token)
    agent, agent_token = _register(world, "escalator-3")

    opened = _post(world, agent_token, {
        "author": agent, "ns": BOB_INBOX, "type": "OPEN",
        "grade": "unverified", "payload": "bob is asleep",
    })
    _post(world, world["op_token"], {
        "author": world["operator"], "ns": BOB_INBOX, "type": "FINDING",
        "refs": [{"edge": "closes", "id": opened["id"]}], "payload": "root handled it",
    })


def test_users_floor_is_not_a_job_board(world: dict) -> None:
    """Why /users is seeded at all: without a floor it inherits the root
    default, which permits JOB and CLAIM."""
    bob, bob_token = _second_human(world)
    _post(world, bob_token, {
        "author": bob, "ns": "/users/bob/board", "type": "JOB",
        "payload": "work on offer in my diary",
        "pointer": {"uri": "https://example.invalid/brief.md", "sha256": "0" * 64},
    }, expect=409)
