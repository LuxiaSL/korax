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
