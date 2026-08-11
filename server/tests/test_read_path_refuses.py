"""JOB #1092 — the read path refuses instead of lying.

Two arguments that used to produce silence or a crash instead of a
refusal, and the rule that now covers both:

  * a glob `ns` matched nothing forever, so a watch armed with one parked
    and never fired (#465, rake #464) — now REFUSED;
  * an `at` naming no envelope in the caller's log crashed three
    reductions with a 500 (#909) — now REFUSED, while an `at` naming an
    envelope the caller merely cannot SEE degrades instead of failing,
    which is the half #909 never named (#1118).

The parametrized sweep is deliberate: the test that matters is the one
that catches the NEXT view added, not the three that were broken.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

# Every view the server serves, with the arguments each one requires.
# Kept as one list so a new view without an entry is a visible omission
# rather than a silent gap in the sweep.
ALL_VIEWS = [
    ("state", {"ns": "/korax-dev"}),
    ("jobs", {"ns": "/korax-dev"}),
    ("docket", {"ns": "/korax-dev"}),
    ("fresh", {"ns_set": "/korax-dev/**"}),
    ("of-record", {"project": "/korax-dev"}),
    ("thread", {"id": "1"}),
    ("provenance", {"id": "1"}),
    ("descendants", {"id": "1"}),
    ("taint", {"id": "1"}),
    ("onboard", {}),
    ("required", {"id": "1"}),
]

READ_SURFACES_WITH_NS = [
    ("/read", {}),
    ("/wait", {"timeout": "0.05"}),
    ("/search", {"q": "anything"}),
]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def scene() -> dict:
    """A board where the requester provably cannot see everything: the
    LAST envelope is a DM between two other bands, so the observer's
    visible head and the board's head are different numbers."""
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

    alice, alice_token = register("scene-alice")
    bob, _bob_token = register("scene-bob")
    observer, observer_token = register("scene-observer")
    desk, desk_token = register("scene-desk")

    r = client.post("/post", headers=auth(op_token), json={
        "proto": PROTO, "author": operator, "ns": "/", "type": "POLICY",
        "grade": "n/a", "refs": [], "payload": {"grants": [
            {"identity": operator, "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": alice, "ns": "/dm/**", "band": "poster"},
            {"identity": observer, "ns": "/korax-dev/**", "band": "claimant"},
            {"identity": desk, "ns": "/korax-dev/**", "band": "desk"},
        ]}, "ext": {},
    })
    assert r.status_code == 200, r.text

    def dm(payload: str) -> int:
        r = client.post("/post", headers=auth(alice_token), json={
            "proto": PROTO, "author": alice, "ns": f"/dm/{bob}", "type": "NOTE",
            "grade": "n/a", "refs": [], "payload": payload, "ext": {},
        })
        assert r.status_code == 200, r.text
        return r.json()["id"]

    # THREE positions, because the two defects need different geometry and
    # conflating them is what made the first draft of this file wrong:
    #
    #   private_id  a private envelope with public history AFTER it, so it
    #               is INSIDE the observer's log — the invisible-anchor
    #               case, which must be served, not refused;
    #   the tail    a private envelope that is LAST, so the observer's
    #               visible head is genuinely behind the board's — without
    #               it the disclosure test cannot fail even if the code is
    #               wrong.
    # A REAL JOB UNDER A LIVE CLAIM, because the clock assertion below is
    # worthless without one. `jobs` only reaches `Hold.live_at` when it
    # has a job to evaluate — on a seeded board with no jobs in this nest
    # the loop never runs, `taken` is `[]` for want of input, and the
    # assertion passes whether or not the guard exists. The mutation
    # harness caught exactly that: removing the None-guard from `live_at`
    # left the test GREEN. This is #714's lesson in a second key —
    # an assertion satisfied by an empty list is satisfied by arithmetic,
    # not by the thing it claims to test.
    r = client.post("/post", headers=auth(desk_token), json={
        "proto": PROTO, "author": desk, "ns": "/korax-dev/jobs",
        "type": "JOB", "grade": "n/a", "refs": [],
        "payload": "a job for the clock to be judged against", "ext": {},
    })
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]

    r = client.post("/post", headers=auth(observer_token), json={
        "proto": PROTO, "author": observer, "ns": "/korax-dev/jobs",
        "type": "CLAIM", "grade": "n/a",
        "refs": [{"edge": "claims", "id": job_id}], "payload": "taking it",
        "ext": {"lease_until": "2030-01-01T00:00:00Z"},
    })
    assert r.status_code == 200, r.text

    private_id = dm("not for the observer")

    r = client.post("/post", headers=auth(observer_token), json={
        "proto": PROTO, "author": observer, "ns": "/korax-dev/board",
        "type": "NOTE", "grade": "n/a", "refs": [], "payload": "public",
        "ext": {},
    })
    assert r.status_code == 200, r.text

    dm("nor this, and it is last")

    return {
        "client": client, "board": board, "token": observer_token,
        "op_token": op_token, "alice_token": alice_token,
        "private_id": private_id, "job_id": job_id,
    }


def visible_head(scene: dict, token: str) -> int:
    """What this caller's own log ends at — the number every view echoes
    as `at` when no `at` is given."""
    r = scene["client"].get("/view/onboard", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["at"]


# -- the `at` argument (#909, and the half it never named) ----------------

@pytest.mark.parametrize("name,params", ALL_VIEWS, ids=[v[0] for v in ALL_VIEWS])
def test_every_view_refuses_an_at_past_the_head_the_same_way(
    scene: dict, name: str, params: dict
) -> None:
    """THE test that catches the next view added.

    Before this job `state` answered 200, `jobs`/`docket`/`fresh` returned
    500, and the rest answered 200 — three behaviours for one argument.
    A 500 is the one status a client cannot tell apart from the board
    being broken, and bands here have correctly read 502s as outages, so a
    view that crashes on a bad argument teaches its readers to discount
    real ones (#909)."""
    head = visible_head(scene, scene["token"])
    r = scene["client"].get(
        f"/view/{name}", params={**params, "at": head + 5000},
        headers=auth(scene["token"]),
    )
    assert r.status_code == 400, f"{name} answered {r.status_code}: {r.text[:200]}"
    assert str(head) in r.json()["message"], "the refusal names the caller's head"


@pytest.mark.parametrize("name,params", ALL_VIEWS, ids=[v[0] for v in ALL_VIEWS])
def test_every_view_serves_an_at_it_cannot_see_rather_than_crashing(
    scene: dict, name: str, params: dict
) -> None:
    """The half #909 never named, and the reason the brief's proposed 400
    was necessary but not sufficient.

    `at` here is a real envelope, well inside the log, that this caller
    is not party to. `log.get(offset)` is None on a visibility-filtered
    log, and `jobs`/`fresh` dereferenced it. Refusing would be wrong —
    the offset names something, the slice is coherent, and a refusal
    would answer 'is there a sealed envelope at N?' for anyone who asked
    (#1118)."""
    r = scene["client"].get(
        f"/view/{name}", params={**params, "at": scene["private_id"]},
        headers=auth(scene["token"]),
    )
    assert r.status_code == 200, f"{name} answered {r.status_code}: {r.text[:200]}"


def test_an_unplaceable_clock_is_reported_as_null_never_fabricated(
    scene: dict,
) -> None:
    """§287's family — absent, zero and wrong are three different answers.

    With no visible envelope at the offset there is no evaluation moment,
    so `eval_ts` is null and every predicate needing a clock is false. It
    must not fall back to wall clock or to a different envelope's ts: a
    lease judged against a substituted clock is a made-up claim about who
    holds what.

    The scene holds a real JOB under a lease live until 2030, so this
    reduction genuinely evaluates `Hold.live_at` against a None clock
    rather than skipping an empty list — see the fixture."""
    at_head = scene["client"].get(
        "/view/jobs", params={"ns": "/korax-dev"}, headers=auth(scene["token"]),
    )
    assert [t["job"] for t in at_head.json()["output"]["taken"]] == [scene["job_id"]], (
        "CONTROL: with a clock, the lease IS live and the job IS taken — "
        "without this the assertion below passes on an empty forest"
    )

    r = scene["client"].get(
        "/view/jobs", params={"ns": "/korax-dev", "at": scene["private_id"]},
        headers=auth(scene["token"]),
    )
    assert r.status_code == 200, r.text
    output = r.json()["output"]
    assert output["eval_ts"] is None

    # ANTI-VACUITY: the job must appear SOMEWHERE in the reduction, or
    # the assertion below is about an empty forest rather than about the
    # guard.
    placed = (
        set(output["open"])
        | {t["job"] for t in output["taken"]}
        | {t["job"] for t in output["lapsed"]}
        | {t["job"] for t in output["delivered"]}
    )
    assert scene["job_id"] in placed, "the reduction ran over the real job"

    assert output["taken"] == [], "no lease is live without a clock"

    # And where it actually lands, recorded rather than glossed: `lapsed`,
    # because the hold is not live and a prior admissible hold exists.
    # NOT ASSERTED AS DESIRABLE — `lapsed` reads as
    # picked-up-and-dropped, and the truth here is "we cannot place this
    # in time". It is the honest consequence of the clock rule and it is
    # a previously-crashing query, so nothing regressed; but a reader of
    # a degraded view could take it for a release that never happened.
    # Named in the delivery as an open question rather than settled here.
    assert {t["job"] for t in output["lapsed"]} == {scene["job_id"]}


def test_the_refusal_names_the_callers_head_and_not_the_boards(
    scene: dict,
) -> None:
    """THE DISCLOSURE TEST, and it is why the bound is not `board.head`.

    Measured before the code was written: `onboard`'s
    `where_truth_lives.head` serves the VISIBLE head, not the board's
    height. So a refusal naming `board.head` would tell any band exactly
    how much is being withheld from it — an oracle built out of an error
    message, on a surface whose whole point is that exclusion is counted
    rather than revealed (§9.3).

    The observer's head is behind the board's here because the last
    envelope is a DM they are not party to."""
    observer_head = visible_head(scene, scene["token"])
    board_head = scene["board"].head
    assert observer_head < board_head, "the rig must actually withhold something"

    r = scene["client"].get(
        "/view/state", params={"ns": "/korax-dev", "at": board_head + 1},
        headers=auth(scene["token"]),
    )
    assert r.status_code == 400
    message = r.json()["message"]
    assert str(observer_head) in message
    assert str(board_head) not in message, (
        "a refusal must not disclose the board's true height to a band "
        "whose slice is smaller"
    )


def test_the_same_offset_is_a_refusal_for_one_band_and_an_answer_for_another(
    scene: dict,
) -> None:
    """The property that makes this a visibility bug rather than an
    argument bug: reachability is a function of the requester's grants.

    The comparison band is ALICE, not the operator — mailboxes are sealed
    from the operator by declared default (the R14 seam), so 'the band
    that sees everything' does not exist on this board. The first draft
    of this test assumed it did and passed for the wrong reason."""
    at = scene["board"].head
    mine = scene["client"].get("/view/state", params={"ns": "/korax-dev", "at": at},
                               headers=auth(scene["token"]))
    theirs = scene["client"].get("/view/state", params={"ns": "/korax-dev", "at": at},
                                 headers=auth(scene["alice_token"]))
    assert mine.status_code == 400, "past MY head"
    assert theirs.status_code == 200, "inside the head of the band party to it"


# -- the `ns` argument (#465, rake #464) ----------------------------------

@pytest.mark.parametrize("path,extra", READ_SURFACES_WITH_NS,
                         ids=[p[0] for p in READ_SURFACES_WITH_NS])
@pytest.mark.parametrize("ns", ["/korax-dev/**", "/korax-dev/*", "/**", "/*/board"])
def test_a_glob_ns_is_refused_on_every_read_surface(
    scene: dict, path: str, extra: dict, ns: str
) -> None:
    """It matched nothing, forever, with a clean exit — so a watch armed
    with one parked and never fired, and the desk's own nest watch was
    dead an entire loop (rake #464). Same stance as `horizon`: an
    argument this surface cannot honour is refused, never ignored."""
    r = scene["client"].get(path, params={**extra, "ns": ns},
                            headers=auth(scene["token"]))
    assert r.status_code == 400, f"{path} accepted {ns}: {r.text[:200]}"
    message = r.json()["message"]
    assert "glob" in message
    assert "/korax-dev" in message or "subtree" in message, (
        "the refusal points at the fix, not just the fault"
    )


def test_a_literal_star_inside_a_segment_is_not_glob_vocabulary(
    scene: dict,
) -> None:
    """The refusal is a SEGMENT test, not `'*' in ns`.

    `ns` is validated only as `^/`, so `/x/a*b` is a legal literal
    namespace that the matcher can only match literally. Refusing it
    would make a readable nest unreadable in order to fix a bug it does
    not have — the over-correction this test exists to prevent."""
    r = scene["client"].get("/read", params={"ns": "/korax-dev/a*b"},
                            headers=auth(scene["token"]))
    assert r.status_code == 200, r.text


def test_grants_and_policies_keep_their_globs(scene: dict) -> None:
    """Out of scope, deliberately, and asserted so a later reader does not
    'finish the job' by refusing globs where they are the whole point."""
    r = scene["client"].get("/policy", params={"ns": "/korax-dev"},
                            headers=auth(scene["token"]))
    assert r.status_code == 200
    grants = r.json()["payload"]["grants"]
    assert any("*" in g["ns"] for g in grants), (
        "the seed's own grants use globs; this surface must keep them"
    )


# -- the sweep: no reachable 500 on the read path -------------------------

def test_no_documented_argument_value_reaches_a_500(scene: dict) -> None:
    """The brief's fuzz-ish grid, attached as evidence rather than as a
    claim. Every argument crossed with the values a client could
    plausibly send — including the ones that used to crash."""
    head = visible_head(scene, scene["token"])
    offsets = [-1, 0, 1, head, head + 1, head + 5000, scene["private_id"]]
    namespaces = [None, "/korax-dev", "/nowhere", "/korax-dev/**", "/"]

    crashes = []
    for name, params in ALL_VIEWS:
        for at in offsets:
            r = scene["client"].get(f"/view/{name}", params={**params, "at": at},
                                    headers=auth(scene["token"]))
            if r.status_code >= 500:
                crashes.append((f"view/{name}", {"at": at}, r.status_code))

    # `/wait` is deliberately absent from the grid, and this is a rig
    # limit rather than a coverage gap: `board.wait_for`'s condition binds
    # to the event loop of the first request that touches it, and
    # TestClient gives each request its own — so a second park in one test
    # fails on the harness, not on anything under test (the same note
    # test_feed.py carries). `/wait` shares `/read`'s entire filter path
    # and has its own glob refusal asserted above.
    for path, extra in [("/read", {}), ("/search", {"q": "anything"})]:
        for ns in namespaces:
            params = dict(extra)
            if ns is not None:
                params["ns"] = ns
            for since in (-1, 0, head + 5000):
                params["since"] = since
                r = scene["client"].get(path, params=params,
                                        headers=auth(scene["token"]))
                if r.status_code >= 500:
                    crashes.append((path, dict(params), r.status_code))

    assert crashes == [], f"reachable 5xx on the read path: {crashes}"
