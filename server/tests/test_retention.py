"""§8.2 — retention as a read-side default.

Two layers. The engine tests build envelopes with explicit timestamps, so
a horizon can be exercised across days without waiting for any. The API
tests drive the real wire and run the board's clock FORWARD between posts
— history is never rewritten, because the append-only trigger refuses
UPDATE outright (§1.1.1) and should. Both layers take their cutoff from
log time, so neither rots: a suite that passes today passes next month.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.log import Log
from korax.models import Act, Envelope
from korax.policy import PolicyTimeline
from korax.retention import (
    ROTATION_EXEMPT_ACTS,
    eval_ts_at,
    is_rotated,
    parse_horizon,
    project,
    split,
)
from korax.seed import seed_board
from korax import store as store_module
from korax.store import Store

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def env(
    env_id: int,
    ns: str,
    type_: Act | str,
    *,
    day: int = 0,
    author: str = "band:worker",
    payload: object = "x",
    grade: str = "n/a",
    band: str = "warner",
) -> Envelope:
    return Envelope.model_validate({
        "proto": PROTO,
        "id": env_id,
        "ts": (T0 + timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": author,
        "band": band,
        "ns": ns,
        "type": type_.value if isinstance(type_, Act) else type_,
        "grade": grade,
        "refs": [],
        "payload": payload,
        "ext": {},
    })


def policy_env(env_id: int, ns: str, retention: dict, *, day: int = 0) -> Envelope:
    # human band so the policy is self-stamping at its own offset (§8.5);
    # a below-human POLICY would sit inert and govern nothing.
    return env(
        env_id, ns, Act.POLICY, day=day,
        author="band:operator", band="human",
        payload={
            "acts": ["NOTE", "FINDING", "WARN", "POLICY", "STAMP", "PIN", "UNSEAL"],
            "grades": False,
            "retention": retention,
            "view_floor": "n/a",
            "grants": [{"identity": "band:*", "band": "warner"}],
        },
    )


def build(*envelopes: Envelope) -> tuple[Log, PolicyTimeline]:
    log = Log(list(envelopes))
    return log, PolicyTimeline(log)


# ---------------------------------------------------------------- engine


def test_permanent_nest_never_rotates() -> None:
    log, tl = build(
        policy_env(0, "/keep", {"mode": "permanent"}),
        env(1, "/keep", Act.FINDING, day=0),
        env(2, "/keep", Act.FINDING, day=400),
    )
    kept, rotated = split(log, tl, log.envelopes, offset=2)
    assert rotated == []
    assert [e.id for e in kept] == [0, 1, 2]


def test_rotate_drops_only_what_is_past_the_horizon() -> None:
    log, tl = build(
        policy_env(0, "/chorus", {"mode": "rotate", "horizon": "P30D"}),
        env(1, "/chorus", Act.NOTE, day=1),    # 39 days before eval — gone
        env(2, "/chorus", Act.NOTE, day=20),   # 20 days before eval — kept
        env(3, "/chorus", Act.NOTE, day=40),   # the anchor
    )
    kept, rotated = split(log, tl, log.envelopes, offset=3)
    assert [e.id for e in rotated] == [1]
    assert [e.id for e in kept] == [0, 2, 3]


def test_the_anchor_never_rotates() -> None:
    """A reduction anchoring on log.get(offset) keeps its anchor: the
    envelope at the evaluation offset defines eval_ts, so no non-negative
    horizon can exclude it. Guarded because state() reads its eval_ts from
    exactly that envelope and would silently stop computing lease
    liveness if it vanished."""
    log, tl = build(
        policy_env(0, "/chorus", {"mode": "rotate", "horizon": "P0D"}),
        env(1, "/chorus", Act.NOTE, day=1),
        env(2, "/chorus", Act.NOTE, day=2),
    )
    kept, rotated = split(log, tl, log.envelopes, offset=2)
    assert 2 in [e.id for e in kept]
    assert [e.id for e in rotated] == [1]
    rot_log, _ = project(log, tl, log, offset=2)
    assert rot_log.get(2) is not None


def test_governance_acts_survive_any_horizon() -> None:
    """§8.2 — an audit trail with a horizon is not an audit trail."""
    log, tl = build(
        policy_env(0, "/chorus", {"mode": "rotate", "horizon": "P1D"}),
        env(1, "/chorus", Act.STAMP, day=0),
        env(2, "/chorus", Act.PIN, day=0),
        env(3, "/chorus", Act.UNSEAL, day=0),
        env(4, "/chorus", Act.NOTE, day=0),
        env(5, "/chorus", Act.NOTE, day=100),
    )
    kept, rotated = split(log, tl, log.envelopes, offset=5)
    assert [e.id for e in rotated] == [4]
    assert {0, 1, 2, 3} <= {e.id for e in kept}


def test_job_rotates_and_is_the_deliberate_difference_from_the_seam() -> None:
    """ROTATION_EXEMPT_ACTS is not SEAM_EXEMPT_ACTS. JOB is the difference:
    a stale job offer in a rotating nest is exactly what should fall out of
    default view. If this test starts failing because the two lists were
    fused, that is the regression, not the test."""
    from korax.models import SEAM_EXEMPT_ACTS

    assert Act.JOB in SEAM_EXEMPT_ACTS
    assert Act.JOB not in ROTATION_EXEMPT_ACTS
    assert ROTATION_EXEMPT_ACTS < SEAM_EXEMPT_ACTS

    log, tl = build(
        policy_env(0, "/chorus", {"mode": "rotate", "horizon": "P1D"}),
        env(1, "/chorus", Act.JOB, day=0),
        env(2, "/chorus", Act.NOTE, day=100),
    )
    _kept, rotated = split(log, tl, log.envelopes, offset=2)
    assert [e.id for e in rotated] == [1]


def test_horizon_follows_the_policy_in_force_at_read_time() -> None:
    """§8.1 governs validation at post offset; retention is a projection,
    so it is read at the read offset. Same envelope, two offsets, two
    answers — and the later answer wins because rotation bounds discovery,
    never access."""
    log, tl = build(
        policy_env(0, "/chorus", {"mode": "permanent"}),
        env(1, "/chorus", Act.NOTE, day=0),
        env(2, "/chorus", Act.NOTE, day=100),
        policy_env(3, "/chorus", {"mode": "rotate", "horizon": "P1D"}, day=100),
        env(4, "/chorus", Act.NOTE, day=100),
    )
    # read before the rotate policy: permanent, nothing withheld
    _kept, rotated_early = split(log, tl, log.upto(2), offset=2)
    assert rotated_early == []
    # read after it: the same old envelope is now past the horizon
    _kept, rotated_late = split(log, tl, log.envelopes, offset=4)
    assert [e.id for e in rotated_late] == [1]


def test_unparseable_horizon_hides_nothing() -> None:
    """A duration this build cannot read is not licence to withhold
    history — the failure mode of a retention bug must be showing too
    much, never too little."""
    log, tl = build(
        policy_env(0, "/chorus", {"mode": "rotate", "horizon": "P1Y"}),
        env(1, "/chorus", Act.NOTE, day=0),
        env(2, "/chorus", Act.NOTE, day=10_000),
    )
    _kept, rotated = split(log, tl, log.envelopes, offset=2)
    assert rotated == []


def test_eval_ts_absent_means_nothing_rotates() -> None:
    log, tl = build(
        policy_env(0, "/chorus", {"mode": "rotate", "horizon": "P1D"}),
        env(1, "/chorus", Act.NOTE, day=0),
    )
    assert eval_ts_at(log, 999) is None
    assert not is_rotated(tl, log.get(1), 999, None)


def test_parse_horizon_rejects_what_v0_cannot_express() -> None:
    assert parse_horizon("P30D") == timedelta(days=30)
    with pytest.raises(ValueError):
        parse_horizon("PT12H")


# ------------------------------------------------------------------- API


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


def op_post(world: dict, body: dict) -> dict:
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "grade": "n/a",
        "refs": [], "ext": {}, **body,
    })
    assert r.status_code == 200, r.text
    return r.json()


@contextmanager
def clock_forward(monkeypatch: pytest.MonkeyPatch, days: int):
    """Run the board's clock forward for the envelopes posted inside.

    The store assigns ts at append with whole-second granularity, so a test
    writes its entire history inside one second and no horizon can bite.
    Backdating a stored record is not an option and should not be — the
    append-only trigger refuses UPDATE outright (§1.1.1), which is the
    invariant working. So the fixture moves forward instead of moving
    history back: timestamps stay monotonic and nothing is rewritten.
    """
    when = datetime.now(timezone.utc) + timedelta(days=days)
    monkeypatch.setattr(store_module, "datetime", SimpleNamespace(now=lambda _tz=None: when))
    try:
        yield
    finally:
        monkeypatch.undo()


def rotating_nest(world: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A nest declaring `rotate P30D`, holding history on both sides of its
    horizon: a NOTE and a STAMP (governance, exempt) written now, and then
    a live NOTE forty days later — at which offset the first two are past
    the horizon and the last one is the anchor."""
    op_post(world, {"ns": "/chorus", "type": "POLICY", "payload": {
        "acts": ["NOTE", "FINDING", "WARN", "JOB", "POLICY", "STAMP", "PIN"],
        "grades": False,
        "retention": {"mode": "rotate", "horizon": "P30D"},
        "view_floor": "n/a",
        "grants": [{"identity": "band:*", "band": "warner"}],
    }})
    old = op_post(world, {"ns": "/chorus", "type": "NOTE", "payload": "forty days back"})
    stamp = op_post(world, {"ns": "/chorus", "type": "STAMP", "payload": "in force",
                            "refs": [{"edge": "stamps", "id": old["id"]}]})
    with clock_forward(monkeypatch, 40):
        new = op_post(world, {"ns": "/chorus", "type": "NOTE", "payload": "now",
                              "refs": [{"edge": "replies", "id": old["id"]}]})
    return {"old": old["id"], "stamp": stamp["id"], "new": new["id"]}


def test_read_applies_the_horizon_and_counts_what_it_withheld(world: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = rotating_nest(world, monkeypatch)
    r = world["client"].get("/read", params={"ns": "/chorus"},
                            headers=auth(world["op_token"])).json()
    served = [e["id"] for e in r["envelopes"]]
    assert ids["old"] not in served          # past the horizon
    assert ids["stamp"] in served            # governance never rotates
    assert r["rotated_excluded"] >= 1        # §8.2 — never silent


def test_read_pierces_only_on_explicit_opt_in(world: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = rotating_nest(world, monkeypatch)
    pierced = world["client"].get(
        "/read", params={"ns": "/chorus", "horizon": "none"},
        headers=auth(world["op_token"])).json()
    assert ids["old"] in [e["id"] for e in pierced["envelopes"]]
    assert pierced["rotated_excluded"] == 0


def test_unrecognised_horizon_is_refused_not_ignored(world: dict) -> None:
    r = world["client"].get("/read", params={"ns": "/chorus", "horizon": "P7D"},
                            headers=auth(world["op_token"]))
    assert r.status_code == 400
    assert set(r.json()) >= {"code", "message"}


def test_views_are_canonical_and_never_pierce(world: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """§9.2 — a pierce parameter that looked accepted and did nothing would
    be an appearance-only control of our own making."""
    r = world["client"].get("/view/state",
                            params={"ns": "/chorus", "horizon": "none"},
                            headers=auth(world["op_token"]))
    assert r.status_code == 400


def test_direct_address_and_edge_following_survive_rotation(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Position 3 — rotation bounds discovery, not reference. A thread whose
    spine decayed out from under its replies would be the worse artifact."""
    ids = rotating_nest(world, monkeypatch)
    got = world["client"].get(f"/envelope/{ids['old']}",
                              headers=auth(world["op_token"]))
    assert got.status_code == 200
    assert got.json()["id"] == ids["old"]

    # the thread rooted at the rotated envelope still resolves, and still
    # carries the live reply hanging off it
    thread = world["client"].get("/view/thread", params={"id": ids["old"]},
                                 headers=auth(world["op_token"])).json()
    assert thread["output"]["root"] == ids["old"]
    assert str(ids["new"]) in str(thread["output"]["replies"])
    assert thread["rotated_excluded"] == 0  # thread is not a rotating view


def test_state_rotates_and_reports_while_onboard_does_not(world: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """onboard walks `requires` to build a reading list; a horizon there
    would silently shrink a fresh agent's canon as it aged."""
    rotating_nest(world, monkeypatch)
    state = world["client"].get("/view/state", params={"ns": "/chorus"},
                                headers=auth(world["op_token"])).json()
    assert state["rotated_excluded"] >= 1

    onboard = world["client"].get("/view/onboard",
                                  headers=auth(world["op_token"])).json()
    assert onboard["rotated_excluded"] == 0


def test_permanent_nests_report_zero(world: dict) -> None:
    r = world["client"].get("/read",
                            params={"ns": "/commons/rakes", "type": "WARN"},
                            headers=auth(world["op_token"])).json()
    assert r["rotated_excluded"] == 0
    assert len(r["envelopes"]) == 5


# ── §8.2's dimension, ruled NAMESPACE at #1099 (issue #802) ──────────────
#
# The instrument below is #468's own, and it is the reason these are tests
# rather than assertions about a diff: **two disjoint slices returning the
# same number means the count names something other than the slice.** Under
# the old board-scoped behaviour every one of these reads returned the same
# total, so a test that checked a single slice against a single number passed
# just as happily while the field was lying. The pair is what falsifies.


def two_rotating_nests(world: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Two rotating nests holding DIFFERENT amounts of rotated history.

    Deliberately asymmetric — two rotated NOTEs in `/chorus`, one in
    `/aviary`. Equal counts would make a board-scoped answer and a
    slice-scoped answer indistinguishable in `/chorus`, which is exactly the
    coincidence #468 warns a single-slice test can be built on.
    """
    for ns in ("/chorus", "/aviary"):
        op_post(world, {"ns": ns, "type": "POLICY", "payload": {
            "acts": ["NOTE", "FINDING", "WARN", "JOB", "POLICY", "STAMP", "PIN"],
            "grades": False,
            "retention": {"mode": "rotate", "horizon": "P30D"},
            "view_floor": "n/a",
            "grants": [{"identity": "band:*", "band": "warner"}],
        }})
    for i in range(2):
        op_post(world, {"ns": "/chorus", "type": "NOTE", "payload": f"chorus old {i}"})
    op_post(world, {"ns": "/aviary", "type": "NOTE", "payload": "aviary old"})
    # the anchor pair, forty days on: at this offset every NOTE above is past
    # its nest's horizon and these two are the live history.
    with clock_forward(monkeypatch, 40):
        for ns in ("/chorus", "/aviary"):
            op_post(world, {"ns": ns, "type": "NOTE", "payload": "now"})
    return {"/chorus": 2, "/aviary": 1, "board": 3}


def read_ns(world: dict, ns: str) -> dict:
    return world["client"].get("/read", params={"ns": ns},
                               headers=auth(world["op_token"])).json()


def test_read_retention_count_names_the_slice_not_the_board(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#802, ruled NAMESPACE at #1099. Before this, both reads returned 3."""
    expected = two_rotating_nests(world, monkeypatch)
    chorus = read_ns(world, "/chorus")
    aviary = read_ns(world, "/aviary")

    # the falsifying pair (#468): disjoint slices, and they must DISAGREE
    assert chorus["rotated_excluded"] != aviary["rotated_excluded"], (
        "two disjoint slices reported the same retention count — the field "
        "names something other than the slice it was served for"
    )
    assert chorus["rotated_excluded"] == expected["/chorus"]
    assert aviary["rotated_excluded"] == expected["/aviary"]
    # and neither is the board's total, which is what they both used to be
    assert chorus["rotated_excluded"] < expected["board"]
    assert aviary["rotated_excluded"] < expected["board"]


def test_read_without_ns_still_names_the_board_and_says_so(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ruling narrows a SLICE; it does not invent one. A caller who
    typed no `ns` asked about the board and is told so, rather than being
    handed a number that quietly means something else."""
    expected = two_rotating_nests(world, monkeypatch)
    whole = world["client"].get("/read", headers=auth(world["op_token"])).json()
    assert whole["rotated_excluded"] == expected["board"]
    assert whole["withheld_scope"] == "board"
    assert read_ns(world, "/chorus")["withheld_scope"] == "slice"


def test_wait_agrees_with_read_on_the_same_slice(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/wait is /read with a long poll in front. Two surfaces disagreeing
    about what a number names is the only unacceptable outcome — a caller
    watching one nest would difference the two and learn the rest."""
    expected = two_rotating_nests(world, monkeypatch)
    waited = world["client"].get(
        "/wait", params={"ns": "/chorus", "since": -1, "timeout": 0.1},
        headers=auth(world["op_token"])).json()
    assert waited["rotated_excluded"] == expected["/chorus"]
    assert waited["withheld_scope"] == "slice"
    assert waited["rotated_excluded"] == read_ns(world, "/chorus")["rotated_excluded"]


def test_view_was_already_right_and_is_unchanged(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1099 moved /read and /wait to match /view, not the other way round.
    This asserts the direction of the fix: the surface that was already
    namespace-scoped keeps its value exactly."""
    expected = two_rotating_nests(world, monkeypatch)
    state = world["client"].get("/view/state", params={"ns": "/chorus"},
                                headers=auth(world["op_token"])).json()
    assert state["rotated_excluded"] == expected["/chorus"]
    assert state["withheld_scope"] == "slice"


def test_feed_keeps_board_scope_and_declares_it(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/feed takes no `ns` and its served slice is "the lanes this identity
    receives" — not a namespace, and spanning nests by construction. There is
    no narrower honest scope to move to, and synthesising one from the lanes
    would make the count a function of the requester's own subscriptions,
    which is the requester-chosen predicate #665 forbids. So it stays board
    and now SAYS board, which is the half #802 was missing."""
    two_rotating_nests(world, monkeypatch)
    feed = world["client"].get("/feed", params={"since": -1, "timeout": 0.1},
                               headers=auth(world["op_token"])).json()
    assert feed["withheld_scope"] == "board"
    # NOT asserted equal to the board's rotated total, and the reason is the
    # finding this job turned up: the `rotated` pile every surface counts is
    # split out of what that surface already SELECTED, so feed's pile is
    # lane-derived and excludes the requester's own posts (R19c). Board scope
    # describes the ruler the count is measured with, never a promise that
    # the pile spans the board. Asserting 3 here is the mistake that taught
    # it — the assertion failed, and the failure was correct.
    assert isinstance(feed["rotated_excluded"], int)


def test_every_counter_on_a_response_shares_one_declared_scope(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of removing `rotated_scope`. A single `withheld_scope` is
    only honest if there is a single scope — a response whose three counts
    named two different things while carrying one label would be a worse
    artifact than the unlabelled inconsistency it replaced."""
    two_rotating_nests(world, monkeypatch)
    for params, expected_scope in (
        ({"ns": "/chorus"}, "slice"),
        ({}, "board"),
    ):
        page = world["client"].get("/read", params=params,
                                   headers=auth(world["op_token"])).json()
        assert page["withheld_scope"] == expected_scope
        # all three counters present and taken over that one scope
        assert {"sealed_excluded", "rotated_excluded",
                "participation_excluded"} <= set(page)
