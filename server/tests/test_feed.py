"""§11.2 — the unified feed. JOB #255 phase 2, design #317 endorsed #324.

The properties under test, in the order the design argues them:

* the union is a DISJUNCTION and it DEDUPES — one envelope matching three
  lanes arrives once, carrying three reasons (D3);
* reasons ride BESIDE the envelopes, never inside them (D3);
* the counters are UNION-scoped — the desk made the failing test the
  acceptance criterion at #324 D3, not a comment;
* a band that guesses every namespace wrong still hears everything
  addressed to it (#223, the scenario the brief names);
* a subscription is an envelope: supersede retires it, and the window it
  leaves behind replays (D1);
* descent is opt-in, R19c is per-lane (D2);
* a selector naming what you cannot read is refused at post time, and a
  mention into a nest the mentioned band cannot read is refused too (D1/D5).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.access import verdict
from korax.api import create_app
from korax.board import Board
from korax.feed import SUBSCRIPTIONS_NS, _ns_refusal
from korax.counters import bucketed
from korax.seed import seed_board
from korax.store import Store


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


def register(world: dict, display: str) -> tuple[str, str]:
    r = world["client"].post("/identity", json={"display": display},
                             headers=auth(world["op_token"]))
    return r.json()["id"], r.json()["token"]


def grant(world: dict, *pairs: tuple[str, str, str]) -> None:
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/",
        "type": "POLICY", "grade": "n/a", "refs": [], "ext": {},
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            *({"identity": i, "ns": ns, "band": b} for i, ns, b in pairs),
        ]},
    })
    assert r.status_code == 200, r.text


ALL_ACTS = ["NOTE", "FINDING", "OPEN", "CLAIM", "PROPOSAL", "WARN",
            "SUPERSEDE", "BESIDE", "HANDOVER", "ACK", "POLICY", "STAMP",
            "SUBSCRIBE"]


def open_nest(world: dict, ns: str, *members: str, acts: list[str] | None = None,
              **extra) -> None:
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": ns,
        "type": "POLICY", "grade": "n/a", "refs": [], "ext": {},
        "payload": {
            "acts": acts or ALL_ACTS,
            "grades": True,
            "require_lease": False,
            "retention": {"mode": "permanent"},
            "view_floor": "unverified",
            "grants": [{"identity": m, "band": "claimant"} for m in members]
                      or [{"identity": "band:*", "band": "claimant"}],
            **extra,
        },
    })
    assert r.status_code == 200, r.text


def post(world: dict, token: str, author: str, expect: int = 200, **body) -> dict:
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": author, "ns": "/work",
        "grade": "n/a", "refs": [], "ext": {}, **body,
    })
    assert r.status_code == expect, r.text
    return r.json()


def feed(world: dict, token: str, **params) -> dict:
    params.setdefault("timeout", 0.05)
    r = world["client"].get("/feed", params=params, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def ids(page: dict) -> list[int]:
    return [e["id"] for e in page["envelopes"]]


def lanes_for(page: dict, env_id: int) -> set[str]:
    return {r["lane"] for r in page["reasons"][str(env_id)]}


@pytest.fixture()
def scene(world: dict) -> dict:
    """One band with a mailbox, authored work, claimed work, and a peer
    generating all four kinds of signal at it."""
    me, my_token = register(world, "me")
    peer, peer_token = register(world, "peer")
    grant(world,
          (me, "/work/**", "claimant"), (peer, "/work/**", "claimant"),
          (me, "/quiet/**", "claimant"), (peer, "/quiet/**", "claimant"),
          (me, f"{SUBSCRIPTIONS_NS}/**", "poster"),
          (peer, f"{SUBSCRIPTIONS_NS}/**", "poster"),
          (me, "/dm/**", "poster"), (peer, "/dm/**", "poster"))
    open_nest(world, "/work", me, peer)
    open_nest(world, "/quiet", me, peer)
    open_nest(world, SUBSCRIPTIONS_NS, me, peer, acts=["SUBSCRIBE", "SUPERSEDE"],
              grades=False)
    open_nest(world, "/dm", me, peer, grades=False)

    anchor = post(world, my_token, me, type="OPEN", payload="my own OPEN")
    claim = post(world, my_token, me, type="CLAIM", payload="taking it",
                 refs=[{"edge": "claims", "id": anchor["id"]}],
                 ext={"lease_until": "2099-01-01T00:00:00Z"})
    return {"me": me, "my_token": my_token, "peer": peer,
            "peer_token": peer_token, "anchor": anchor["id"],
            "claim": claim["id"], **world}


# -- the disjunction, and the dedup that pays for it ----------------------

def test_one_envelope_three_lanes_arrives_once(scene: dict) -> None:
    """D3 — the mechanical answer to "appears once with both reasons, not
    twice", and the property that turns 357 wakes into 295 (#301)."""
    hit = post(scene, scene["peer_token"], scene["peer"], type="FINDING",
               payload="touches everything",
               refs=[{"edge": "derives-from", "id": scene["anchor"]},
                     {"edge": "derives-from", "id": scene["claim"]}],
               ext={"korax": {"mentions": [scene["me"]]}})

    page = feed(scene, scene["my_token"])
    assert ids(page).count(hit["id"]) == 1, "the union must dedup by id"
    # to_author (it edges my CLAIM), to_worked (it edges what I claimed),
    # mention (it names me) — three lanes, one envelope, three reasons.
    assert lanes_for(page, hit["id"]) == {"to_author", "to_worked", "mention"}


def test_reasons_ride_beside_the_envelopes_never_inside(scene: dict) -> None:
    """D3's deepest line: an envelope must not gain fields depending on how
    it was found, or replay and signature verification die together."""
    hit = post(scene, scene["peer_token"], scene["peer"], type="FINDING",
               payload="found by mention", ext={"korax": {"mentions": [scene["me"]]}})

    page = feed(scene, scene["my_token"])
    served = next(e for e in page["envelopes"] if e["id"] == hit["id"])
    assert "reasons" not in served and "lane" not in served

    # The same envelope by a plain /read must be byte-identical.
    r = scene["client"].get("/read", params={"ns": "/work"},
                            headers=auth(scene["my_token"]))
    plain = next(e for e in r.json()["envelopes"] if e["id"] == hit["id"])
    assert served == plain


# -- #223: the scenario the brief names -----------------------------------

def test_a_band_that_guesses_every_namespace_wrong_still_hears(scene: dict) -> None:
    """The bare form is the thing you cannot park wrong.

    This band has subscribed to nothing and would have parked its watches
    on namespaces that do not exist. Under `/wait` that is indistinguishable
    from a quiet board (#223). Under `/feed` it hears everything addressed
    to it, because the default lanes come from its identity, not from a
    string it had to guess."""
    dm = post(scene, scene["peer_token"], scene["peer"], ns=f"/dm/{scene['me']}",
              type="NOTE", payload="a message")
    edge = post(scene, scene["peer_token"], scene["peer"], type="FINDING",
                payload="builds on your claim",
                refs=[{"edge": "derives-from", "id": scene["claim"]}])
    named = post(scene, scene["peer_token"], scene["peer"], ns="/quiet",
                 type="NOTE", payload="over here",
                 ext={"korax": {"mentions": [scene["me"]]}})

    # The mis-keyed watch, in both of its live shapes: a namespace nobody
    # posts in, and (rake #464) a glob the read path can never match. Only
    # one of them parks — `board.wait_for`'s condition binds to the event
    # loop of the first request that touches it, and TestClient gives each
    # request its own loop, so a second park in one test fails on the
    # harness rather than on anything under test.
    dead = scene["client"].get("/wait", params={"ns": "/work/**", "timeout": 0.05},
                               headers=auth(scene["my_token"]))
    assert dead.json()["envelopes"] == [], "a glob ns is a dead tripwire (#464)"
    r = scene["client"].get("/read", params={"ns": "/nowhere"},
                            headers=auth(scene["my_token"]))
    assert r.json()["envelopes"] == [], "and so is a namespace nobody posts in"

    got = ids(feed(scene, scene["my_token"]))
    assert dm["id"] in got and edge["id"] in got and named["id"] in got


# -- the counters (the desk's acceptance criterion, #324 D3) --------------

def test_counters_are_union_scoped_not_zero_while_withholding(world: dict) -> None:
    """THE acceptance criterion: a counter must never report 0 while the
    feed withholds something that would have matched a lane.

    Written to fail against a `scoped()` that re-applies a conjunctive
    filter or returns a board-wide length — the two ways this has gone
    wrong one layer down (R28/#204) and one layer up (#468)."""
    me, my_token = register(world, "me")
    peer, peer_token = register(world, "peer")
    third, third_token = register(world, "third")
    grant(world, (me, "/dm/**", "poster"), (peer, "/dm/**", "poster"),
          (third, "/dm/**", "poster"))
    open_nest(world, "/dm", me, peer, third, grades=False)

    # A mailbox neither `me` nor the requester participates in: withheld
    # from `third` by participation (§7.2), and it WOULD have matched
    # `me`'s mailbox lane.
    post(world, peer_token, peer, ns=f"/dm/{me}", type="NOTE", payload="private")

    mine = feed(world, my_token)
    assert mine["participation_excluded"] == 0
    assert len(mine["envelopes"]) == 1, "my own mailbox is mine to read"

    # `third` sees neither the envelope nor a false zero. Under JOB #667 the
    # feed takes BOARD scope — it has no `ns` parameter at all — so the DM is
    # counted as withheld from `third` even though it matches no lane of
    # theirs. That is strictly more conservative than the old lane-union:
    # the old answer was 0, and 0 is the completeness claim (§9.3).
    theirs = feed(world, third_token)
    assert theirs["envelopes"] == []
    assert theirs["participation_excluded"] == bucketed(1), (
        "board scope must report that something is withheld from this "
        "requester, whether or not it would have matched one of their lanes"
    )


    # Now make the withheld envelope match one of `third`'s lanes: peer
    # mentions `third` inside `me`'s mailbox. The mention lane would match;
    # participation withholds it. The counter MUST report it.
    post(world, peer_token, peer, ns=f"/dm/{me}", type="NOTE",
         payload="naming a non-participant",
         ext={"korax": {"mentions": [third]}}, expect=403)


def test_zero_survives_board_scope_where_it_matters(world: dict) -> None:
    """#790's check on JOB #667: board scope must not cost §9.3's guarantee.

    The worry about widening the feed's counter to the board is that zero
    stops being sayable. It does not: if nothing is withheld from you
    board-wide then nothing is withheld from your feed, so **zero remains
    an exact completeness claim** and only the non-zero case loses
    precision. This is the surface where losing it would have been worst.
    """
    me, my_token = register(world, "solo")
    grant(world, (me, "/dm/**", "poster"))
    open_nest(world, "/dm", me, grades=False)
    post(world, my_token, me, ns=f"/dm/{me}", type="NOTE", payload="mine alone")

    mine = feed(world, my_token)
    assert mine["participation_excluded"] == 0, (
        "nothing is withheld from this band board-wide, so the feed must "
        "still be able to say so exactly"
    )


def test_a_withheld_envelope_that_matches_a_lane_is_counted(world: dict) -> None:
    """The counter's live case, built where the seam and a lane actually
    overlap: `third` authored an envelope, a reply to it lands inside a
    mailbox `third` cannot read, and `to_author` would have matched."""
    me, my_token = register(world, "me")
    peer, peer_token = register(world, "peer")
    third, third_token = register(world, "third")
    grant(world, (me, "/dm/**", "poster"), (peer, "/dm/**", "poster"),
          (third, "/work/**", "claimant"), (peer, "/work/**", "claimant"))
    open_nest(world, "/dm", me, peer, grades=False)
    open_nest(world, "/work", third, peer)

    anchor = post(world, third_token, third, type="NOTE", payload="third's own")
    # peer replies to third's envelope, but inside me's mailbox — visible to
    # me and to peer, withheld from third by participation.
    post(world, peer_token, peer, ns=f"/dm/{me}", type="NOTE",
         payload="reply out of reach",
         refs=[{"edge": "replies", "id": anchor["id"]}])

    page = feed(world, third_token)
    assert page["envelopes"] == [], "third cannot read the mailbox"
    assert page["participation_excluded"] == bucketed(1), (
        "it was withheld AND it would have matched third's to_author lane; "
        "reporting 0 here is the false-completeness class this test exists "
        "to catch"
    )


# -- subscriptions are envelopes (D1) -------------------------------------

def subscribe(scene: dict, token: str, who: str, **select) -> dict:
    return post(scene, token, who, ns=SUBSCRIPTIONS_NS, type="SUBSCRIBE",
                grade="n/a", payload="standing interest",
                ext={"select": select})


def test_a_subscription_opens_a_lane_and_supersede_closes_it(scene: dict) -> None:
    sub = subscribe(scene, scene["my_token"], scene["me"], lane="ns", ns="/quiet")

    during = post(scene, scene["peer_token"], scene["peer"], ns="/quiet",
                  type="NOTE", payload="heard")
    page = feed(scene, scene["my_token"])
    assert during["id"] in ids(page)
    assert lanes_for(page, during["id"]) == {"subscription"}
    assert page["reasons"][str(during["id"])][0]["via"] == sub["id"], (
        "`via` names the SUBSCRIBE, which is the envelope you supersede to "
        "stop hearing it (D3)"
    )

    post(scene, scene["my_token"], scene["me"], ns=SUBSCRIPTIONS_NS,
         type="SUPERSEDE", grade="n/a", payload="unsubscribe",
         refs=[{"edge": "supersedes", "id": sub["id"]}])
    after = post(scene, scene["peer_token"], scene["peer"], ns="/quiet",
                 type="NOTE", payload="not heard")

    page = feed(scene, scene["my_token"])
    assert after["id"] not in ids(page)
    # …and the window replays: the envelope from before the supersede is
    # still in the feed drained from scratch (D1 — a reduction, not a
    # session).
    assert during["id"] in ids(feed(scene, scene["my_token"], since=-1))


def test_a_subscription_is_not_retroactive(scene: dict) -> None:
    """Declaring an interest opens a window at the SUBSCRIBE's own id —
    the arm-at-head rule (#110) holding for declarations."""
    before = post(scene, scene["peer_token"], scene["peer"], ns="/quiet",
                  type="NOTE", payload="posted before I subscribed")
    subscribe(scene, scene["my_token"], scene["me"], lane="ns", ns="/quiet")
    after = post(scene, scene["peer_token"], scene["peer"], ns="/quiet",
                 type="NOTE", payload="posted after")

    got = ids(feed(scene, scene["my_token"], since=-1))
    assert before["id"] not in got and after["id"] in got


def test_the_ns_selector_takes_a_glob_or_a_subtree_root(scene: dict) -> None:
    """Rake #464 in the other direction: neither spelling may be silently
    empty. `/quiet/**` and `/quiet` must both reach `/quiet/deep`."""
    open_nest(scene, "/quiet/deep", scene["me"], scene["peer"])
    for pattern in ("/quiet/**", "/quiet"):
        sub = subscribe(scene, scene["my_token"], scene["me"],
                        lane="ns", ns=pattern)
        hit = post(scene, scene["peer_token"], scene["peer"], ns="/quiet/deep",
                   type="NOTE", payload=f"under {pattern}")
        assert hit["id"] in ids(feed(scene, scene["my_token"])), pattern
        post(scene, scene["my_token"], scene["me"], ns=SUBSCRIPTIONS_NS,
             type="SUPERSEDE", grade="n/a", payload="done",
             refs=[{"edge": "supersedes", "id": sub["id"]}])


def test_descent_is_opt_in_and_one_hop(scene: dict) -> None:
    """D2 — the worst-scoring lane measured (13.4% useful over 119 wakes,
    #301) is a lane you may post, never a lane you are given."""
    target = post(scene, scene["peer_token"], scene["peer"], type="NOTE",
                  payload="a shared referent")
    mine = post(scene, scene["my_token"], scene["me"], type="NOTE",
                payload="I edged it",
                refs=[{"edge": "derives-from", "id": target["id"]}])
    sibling = post(scene, scene["peer_token"], scene["peer"], type="NOTE",
                   payload="somebody else edged the same thing",
                   refs=[{"edge": "derives-from", "id": target["id"]}])

    assert sibling["id"] not in ids(feed(scene, scene["my_token"])), (
        "descent must not be a default lane"
    )

    sub = subscribe(scene, scene["my_token"], scene["me"], lane="descent")
    later = post(scene, scene["peer_token"], scene["peer"], type="NOTE",
                 payload="and again",
                 refs=[{"edge": "derives-from", "id": target["id"]}])
    page = feed(scene, scene["my_token"])
    assert later["id"] in ids(page)
    reason = page["reasons"][str(later["id"])][0]
    assert reason["lane"] == "descent"
    assert reason["via"] == mine["id"], "`via` is YOUR descended envelope (D3)"
    assert reason["sub"] == sub["id"], "…and `sub` is what you supersede"


def test_r19c_is_per_lane_and_include_self_overrides_globally(scene: dict) -> None:
    """D2 — on for every identity-shaped lane, on the `self_drop()`
    precedent; `--include-self` keeps its global-override meaning."""
    subscribe(scene, scene["my_token"], scene["me"], lane="ns", ns="/quiet")
    mine = post(scene, scene["my_token"], scene["me"], ns="/quiet",
                type="NOTE", payload="my own post in a nest I subscribed to")

    assert mine["id"] not in ids(feed(scene, scene["my_token"]))
    assert mine["id"] in ids(feed(scene, scene["my_token"], include_self="true"))


def test_your_own_mailbox_is_exempt_from_r19c(scene: dict) -> None:
    """The one lane where the question does not arise: a message you send
    lands in the RECIPIENT's box, so your own mailbox holds other birds'
    envelopes by construction. A DM to yourself is the degenerate case and
    must still arrive."""
    note = post(scene, scene["my_token"], scene["me"], ns=f"/dm/{scene['me']}",
                type="NOTE", payload="note to self")
    assert note["id"] in ids(feed(scene, scene["my_token"]))


# -- post-time refusals (D1, D5) ------------------------------------------

def test_a_selector_naming_someone_elses_mailbox_is_refused(scene: dict) -> None:
    """#223's lesson made structural: an error, never a silently empty lane."""
    r = scene["client"].post("/post", headers=auth(scene["my_token"]), json={
        "proto": PROTO, "author": scene["me"], "ns": SUBSCRIPTIONS_NS,
        "type": "SUBSCRIBE", "grade": "n/a", "refs": [], "payload": "peek",
        "ext": {"select": {"lane": "ns", "ns": f"/dm/{scene['peer']}"}},
    })
    assert r.status_code == 403, r.text
    assert "structurally private" in r.json()["message"]

    # …and the greedy spelling is refused too, though it does cover my own
    wide = scene["client"].post("/post", headers=auth(scene["my_token"]), json={
        "proto": PROTO, "author": scene["me"], "ns": SUBSCRIPTIONS_NS,
        "type": "SUBSCRIBE", "grade": "n/a", "refs": [], "payload": "all boxes",
        "ext": {"select": {"lane": "ns", "ns": "/dm/**"}},
    })
    assert wide.status_code == 403, wide.text


def test_my_own_mailbox_is_a_legal_selector(scene: dict) -> None:
    post(scene, scene["my_token"], scene["me"], ns=SUBSCRIPTIONS_NS,
         type="SUBSCRIBE", grade="n/a", payload="my own box",
         ext={"select": {"lane": "ns", "ns": f"/dm/{scene['me']}"}})


def test_a_malformed_selector_is_400_and_an_unreachable_one_is_403(scene: dict) -> None:
    """The two failures want different next moves from the poster, so they
    carry different codes rather than one code and some prose."""
    bad = scene["client"].post("/post", headers=auth(scene["my_token"]), json={
        "proto": PROTO, "author": scene["me"], "ns": SUBSCRIPTIONS_NS,
        "type": "SUBSCRIBE", "grade": "n/a", "refs": [], "payload": "?",
        "ext": {"select": {"lane": "telepathy"}},
    })
    assert bad.status_code == 400 and "lane" in bad.json()["message"]

    missing = scene["client"].post("/post", headers=auth(scene["my_token"]), json={
        "proto": PROTO, "author": scene["me"], "ns": SUBSCRIPTIONS_NS,
        "type": "SUBSCRIBE", "grade": "n/a", "refs": [], "payload": "?",
        "ext": {},
    })
    assert missing.status_code == 400 and "ext.select" in missing.json()["message"]


def test_a_subscribe_outside_the_declarations_nest_is_refused(scene: dict) -> None:
    """The nest is part of the act's meaning; a SUBSCRIBE posted elsewhere
    would be an envelope no feed honours, which is worse than a refusal."""
    r = scene["client"].post("/post", headers=auth(scene["my_token"]), json={
        "proto": PROTO, "author": scene["me"], "ns": "/work",
        "type": "SUBSCRIBE", "grade": "n/a", "refs": [], "payload": "wrong nest",
        "ext": {"select": {"lane": "type", "type": "JOB"}},
    })
    assert r.status_code == 400 and SUBSCRIPTIONS_NS in r.json()["message"]


def test_you_may_not_mention_a_non_participant_into_a_mailbox(scene: dict) -> None:
    """D1's check applied to the mention lane (ruled #324 D5). Without it a
    mention is a wake pointing at a 404 — citing what your reader cannot
    reach (#197).

    A mailbox is the live case on this board: the visitor floor
    (`band:* reader /**`) means a plain nest is readable by everyone, so
    the only namespaces anyone can be mentioned OUT of are the
    structurally private ones."""
    third, _ = register(scene, "third")
    r = scene["client"].post("/post", headers=auth(scene["peer_token"]), json={
        "proto": PROTO, "author": scene["peer"], "ns": f"/dm/{scene['me']}",
        "type": "NOTE", "grade": "n/a", "refs": [], "payload": "psst",
        "ext": {"korax": {"mentions": [third]}},
    })
    assert r.status_code == 403, r.text
    assert "structurally private" in r.json()["message"]

    # …but naming the box's own owner is exactly what a mention is for.
    post(scene, scene["peer_token"], scene["peer"], ns=f"/dm/{scene['me']}",
         type="NOTE", payload="for you",
         ext={"korax": {"mentions": [scene["me"]]}})


def test_you_may_not_mention_someone_where_they_hold_no_grant(world: dict) -> None:
    """The grant half of the same rule, on a board whose visitor floor is
    narrower than this one's default — the configuration the check exists
    for, built explicitly rather than assumed."""
    me, my_token = register(world, "me")
    outsider, _ = register(world, "outsider")
    # a root POLICY with NO `band:*` floor: reading is granted, not ambient
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/",
        "type": "POLICY", "grade": "n/a", "refs": [], "ext": {},
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": me, "ns": "/private/**", "band": "claimant"},
        ]},
    })
    assert r.status_code == 200, r.text
    open_nest(world, "/private", me)

    r = world["client"].post("/post", headers=auth(my_token), json={
        "proto": PROTO, "author": me, "ns": "/private", "type": "NOTE",
        "grade": "n/a", "refs": [], "payload": "psst",
        "ext": {"korax": {"mentions": [outsider]}},
    })
    assert r.status_code == 403, r.text
    assert "no read grant" in r.json()["message"]


def test_mentions_into_a_readable_nest_are_fine(scene: dict) -> None:
    hit = post(scene, scene["peer_token"], scene["peer"], type="NOTE",
               payload="hello", ext={"korax": {"mentions": [scene["me"]]}})
    assert lanes_for(feed(scene, scene["my_token"]), hit["id"]) == {"mention"}


# -- the canary on the duplicated privacy rule ----------------------------

def test_ns_readable_agrees_with_verdict(world: dict) -> None:
    """feed._ns_refusal restates access.py's structural-privacy rules
    because there is no envelope to judge when a SUBSCRIBE is posted.
    Restating a rule is how two copies drift apart, so this is the assertion
    that makes the divergence loud (#111): for every structurally private
    root, the namespace-level answer must match the envelope-level one.

    If access.py grows a third private prefix, this fails — which is the
    entire reason the duplication is acceptable.
    """
    me, my_token = register(world, "me")
    other, other_token = register(world, "other")
    grant(world, (me, "/dm/**", "poster"), (other, "/dm/**", "poster"))
    open_nest(world, "/dm", me, other, grades=False)

    board = world["board"]
    head = board.head
    cases = [
        (f"/dm/{me}", True),      # my own room
        (f"/dm/{other}", False),  # somebody else's
    ]
    for ns, expected_readable in cases:
        # envelope-level: a real envelope authored by `other`, in `ns`
        post(world, other_token, other, ns=ns, type="NOTE", payload="probe")
        env = board.log.envelopes[-1]
        env_ok = verdict(board.log, board.timeline, env, me, board.head) == "ok"
        # namespace-level: the selector check
        sel_ok = _ns_refusal(board.timeline, me, ns, head) is None
        assert env_ok == sel_ok == expected_readable, (
            f"{ns}: verdict says {env_ok}, selector check says {sel_ok}"
        )
