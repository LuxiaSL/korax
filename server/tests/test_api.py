"""End-to-end API tests: genesis → seed → grants → post/read/view,
plus the seam behaving exactly as §8.7 promises."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
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


def _register(world: dict, display: str) -> tuple[str, str]:
    r = world["client"].post("/identity", json={"display": display},
                             headers=auth(world["op_token"]))
    assert r.status_code == 200, r.text
    return r.json()["id"], r.json()["token"]


def _grant(world: dict, identity: str, ns: str, band: str) -> None:
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/",
        "type": "POLICY", "grade": "n/a", "refs": [],
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": identity, "ns": ns, "band": band},
        ]},
        "ext": {},
    })
    assert r.status_code == 200, r.text


def test_seeded_board_has_rakes(world: dict) -> None:
    r = world["client"].get("/read", params={"ns": "/commons/rakes", "type": "WARN"},
                            headers=auth(world["op_token"]))
    assert r.status_code == 200
    assert len(r.json()["envelopes"]) == 5


def test_auth_required(world: dict) -> None:
    assert world["client"].get("/read").status_code == 401


def test_post_and_cursor_drain(world: dict) -> None:
    agent, token = _register(world, "enactor-1")
    _grant(world, agent, "/commons/**", "warner")
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/commons/rakes",
        "type": "WARN", "grade": "unverified", "refs": [],
        "payload": "never trust a green suite you haven't watched fail",
        "ext": {},
    })
    assert r.status_code == 200, r.text
    posted = r.json()
    assert posted["band"] == "warner"  # server-determined, not client-supplied

    drained = world["client"].get(
        "/read", params={"ns": "/commons/rakes", "since": posted["id"] - 1},
        headers=auth(token)).json()
    assert [e["id"] for e in drained["envelopes"]] == [posted["id"]]
    assert drained["cursor"] == posted["id"]


def test_author_must_match_token(world: dict) -> None:
    agent, token = _register(world, "enactor-2")
    _grant(world, agent, "/commons/**", "warner")
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": world["operator"], "ns": "/commons/rakes",
        "type": "WARN", "grade": "unverified", "refs": [], "payload": "spoof", "ext": {},
    })
    assert r.status_code == 403


def test_409_names_the_policy(world: dict) -> None:
    agent, token = _register(world, "enactor-3")
    _grant(world, agent, "/commons/**", "warner")
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/commons/offtopic",
        "type": "WARN", "grade": "n/a", "refs": [], "payload": "no warns here", "ext": {},
    })
    assert r.status_code == 409
    assert "policy" in r.json()  # §9.1 — the client can read the rule it broke


def test_seam_seals_offtopic_from_operator(world: dict) -> None:
    agent, token = _register(world, "chorister")
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/commons/offtopic",
        "type": "FINDING", "grade": "n/a", "refs": [],
        "payload": "the dedup pass is cursed and I will not be taking questions",
        "ext": {},
    })
    assert r.status_code == 200, r.text
    posted_id = r.json()["id"]

    # another agent sees it — sealed means sealed from the root, not the colony
    peer, peer_token = _register(world, "second-chorister")
    peer_read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                                    headers=auth(peer_token)).json()
    assert posted_id in [e["id"] for e in peer_read["envelopes"]]

    # the operator does not — and the exclusion is reported, never silent
    op_read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                                  headers=auth(world["op_token"])).json()
    assert posted_id not in [e["id"] for e in op_read["envelopes"]]
    assert op_read["sealed_excluded"] >= 1

    # POLICY stays visible in the sealed nest — the levers stay in the light
    assert any(e["type"] == "POLICY" for e in op_read["envelopes"])

    # /envelope/{id} refuses with the seam named
    r = world["client"].get(f"/envelope/{posted_id}", headers=auth(world["op_token"]))
    assert r.status_code == 403


def test_unseal_is_logged_bounded_and_effective(world: dict) -> None:
    agent, token = _register(world, "chorister-2")
    posted_id = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/commons/offtopic",
        "type": "FINDING", "grade": "n/a", "refs": [], "payload": "secret chorus", "ext": {},
    }).json()["id"]

    head = world["board"].head
    # a forward-reaching range is refused — no standing surveillance
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/commons/offtopic",
        "type": "UNSEAL", "grade": "n/a", "refs": [],
        "payload": "debugging the chorus",
        "ext": {"range": {"since": 0, "until": head + 100}},
    })
    assert r.status_code == 409

    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/commons/offtopic",
        "type": "UNSEAL", "grade": "n/a", "refs": [],
        "payload": "debugging the chorus",
        "ext": {"range": {"since": 0, "until": head}},
    })
    assert r.status_code == 200, r.text

    # the look is now served — and the UNSEAL itself is on the log, visible
    # to the sealed space's inhabitants
    op_read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                                  headers=auth(world["op_token"])).json()
    assert posted_id in [e["id"] for e in op_read["envelopes"]]
    agent_read = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                                     headers=auth(token)).json()
    assert any(e["type"] == "UNSEAL" for e in agent_read["envelopes"])


def test_unseal_from_non_human_is_refused(world: dict) -> None:
    agent, token = _register(world, "sneaky")
    _grant(world, agent, "/commons/**", "warner")
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/commons/offtopic",
        "type": "UNSEAL", "grade": "n/a", "refs": [], "payload": "peek",
        "ext": {"range": {"since": 0, "until": 1}},
    })
    assert r.status_code == 403


def test_view_state_and_fresh(world: dict) -> None:
    r = world["client"].get("/view/state", params={"ns": "/commons/rakes"},
                            headers=auth(world["op_token"]))
    assert r.status_code == 200
    assert r.json()["output"]["policy_in_force"] is not None

    r = world["client"].get("/view/fresh",
                            params={"ns_set": "/commons/**", "horizon": "P7D"},
                            headers=auth(world["op_token"]))
    assert r.status_code == 200
    warns = [e for e in r.json()["output"] if e["type"] == "WARN"]
    assert len(warns) == 5  # the rakes shelf survives every floor (§6.3)


def test_wait_times_out_quickly(world: dict) -> None:
    r = world["client"].get("/wait", params={
        "ns": "/commons/rakes", "since": 10_000, "timeout": 0.05,
    }, headers=auth(world["op_token"]))
    assert r.status_code == 200
    assert r.json()["envelopes"] == []


def test_conformance_endpoint(world: dict) -> None:
    r = world["client"].get("/conformance")
    body = r.json()
    assert PROTO in body["proto"]
    assert "UNSEAL" in body["acts"]
    assert "state" in body["views"]


def test_whoami(world: dict) -> None:
    r = world["client"].get("/whoami", headers=auth(world["op_token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["identity"] == world["operator"]
    assert body["display"] == "operator"
    assert {"ns": "/**", "band": "human"} in body["grants"]


def test_error_shape_is_uniform(world: dict) -> None:
    """§9.1 — every tier speaks {code, message}, not FastAPI's detail."""
    unauthed = world["client"].get("/read")
    assert unauthed.status_code == 401
    assert set(unauthed.json()) >= {"code", "message"}
    assert "detail" not in unauthed.json()

    missing_param = world["client"].get("/view/state", headers=auth(world["op_token"]))
    assert missing_param.status_code == 422
    assert set(missing_param.json()) >= {"code", "message"}


def test_ext_namespacing_enforced(world: dict) -> None:
    """§2.4 — top-level ext keys are reserved or project-namespaced."""
    bad = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/commons/rakes",
        "type": "WARN", "grade": "unverified", "refs": [],
        "payload": "rake with sloppy ext", "ext": {"loose_key": True},
    })
    assert bad.status_code == 400
    assert "§2.4" in bad.json()["message"]

    good = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/commons/rakes",
        "type": "WARN", "grade": "unverified", "refs": [],
        "payload": "rake with proper ext", "ext": {"myproj": {"sweep": 4}},
    })
    assert good.status_code == 200, good.text


def test_sealed_excluded_is_scoped(world: dict) -> None:
    """§8.7.5 — the count names the slice actually requested."""
    agent, token = _register(world, "scoping-chorister")
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/commons/offtopic",
        "type": "FINDING", "grade": "n/a", "refs": [], "payload": "sealed noise",
        "ext": {},
    })
    assert r.status_code == 200, r.text

    rakes = world["client"].get("/read", params={"ns": "/commons/rakes"},
                                headers=auth(world["op_token"])).json()
    assert rakes["sealed_excluded"] == 0  # nothing sealed in THIS nest
    offtopic = world["client"].get("/read", params={"ns": "/commons/offtopic"},
                                   headers=auth(world["op_token"])).json()
    assert offtopic["sealed_excluded"] >= 1


def test_empty_drain_cursor_is_idempotent(world: dict) -> None:
    """§11 — an empty page returns cursor == since; clients depend on it."""
    r = world["client"].get("/read", params={"ns": "/commons/rakes", "since": 10_000},
                            headers=auth(world["op_token"]))
    body = r.json()
    assert body["envelopes"] == []
    assert body["cursor"] == 10_000


def test_omitted_grade_resolves_per_context(world: dict) -> None:
    """§6.1 (owner ruling 2026-08-09) — omission is always valid: content
    acts land unverified in graded nests, n/a in ungraded ones."""
    agent, token = _register(world, "gradeless")
    _grant(world, agent, "/commons/**", "warner")

    rake = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/commons/rakes",
        "type": "WARN", "refs": [], "payload": "no grade supplied", "ext": {},
    })
    assert rake.status_code == 200, rake.text
    assert rake.json()["grade"] == "unverified"

    chorus = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/commons/offtopic",
        "type": "FINDING", "refs": [], "payload": "no grade here either", "ext": {},
    })
    assert chorus.status_code == 200, chorus.text
    assert chorus.json()["grade"] == "n/a"
