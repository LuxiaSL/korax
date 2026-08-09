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


def _post(world: dict, token: str, body: dict) -> dict:
    body.setdefault("proto", PROTO)
    body.setdefault("refs", [])
    body.setdefault("ext", {})
    r = world["client"].post("/post", headers=auth(token), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_onboard_ack_claim_lifecycle(world: dict) -> None:
    """§4.4/§10.9/§10.10 end to end: the 409 is the reading list, the
    envelope arrives annotated, acks drain onboard, the claim unblocks."""
    client = world["client"]
    desk, dtoken = _register(world, "proj-desk")
    worker, wtoken = _register(world, "proj-worker")
    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/", "type": "POLICY", "grade": "n/a",
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": desk, "ns": "/proj/**", "band": "desk"},
            {"identity": worker, "ns": "/proj/**", "band": "claimant"},
        ]},
    })

    # desk-authored nest policy; in force from the operator's STAMP (§8.5).
    # STAMP is valid here even though `acts` omits it — governance exemption.
    nest_policy = _post(world, dtoken, {
        "author": desk, "ns": "/proj/jobs", "type": "POLICY", "grade": "n/a",
        "payload": {
            "acts": ["JOB", "CLAIM", "ACK", "FINDING", "SUPERSEDE", "PIN"],
            "grades": True, "require_lease": True, "require_acks": True,
            "pin_posters": "desk", "view_floor": "unverified",
        },
    })
    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/proj/jobs", "type": "STAMP",
        "grade": "n/a", "refs": [{"edge": "stamps", "id": nest_policy["id"]}],
        "payload": "nest policy in force",
    })

    conventions = _post(world, dtoken, {
        "author": desk, "ns": "/proj/board", "type": "FINDING",
        "grade": "verified", "payload": "proj conventions: deliver via closes",
    })
    rake = _post(world, dtoken, {
        "author": desk, "ns": "/proj/board", "type": "FINDING",
        "grade": "verified", "payload": "the migration rake this job exists because of",
    })
    _post(world, dtoken, {
        "author": desk, "ns": "/proj/jobs", "type": "PIN", "grade": "n/a",
        "refs": [{"edge": "pins", "id": conventions["id"]}],
        "payload": {"class": "canon"},
    })
    job = _post(world, dtoken, {
        "author": desk, "ns": "/proj/jobs", "type": "JOB", "grade": "n/a",
        "refs": [{"edge": "requires", "id": rake["id"]}],
        "payload": "migrate the index",
    })

    reading_list = sorted([conventions["id"], rake["id"]])

    # the CLAIM bounces with the reading list — ids, not prose
    r = client.post("/post", headers=auth(wtoken), json={
        "proto": PROTO, "author": worker, "ns": "/proj/jobs", "type": "CLAIM",
        "grade": "n/a", "refs": [{"edge": "claims", "id": job["id"]}],
        "payload": "taking it", "ext": {"lease_until": "2030-01-01T00:00:00Z"},
    })
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["missing"] == reading_list
    assert body["policy"] == nest_policy["id"]

    # the document arrives annotated with the requester's unmet closure
    env = client.get(f"/envelope/{job['id']}", headers=auth(wtoken)).json()
    assert env["required_unmet"]["unread"] == reading_list

    # onboard shows the nest canon (the pin), not the per-artifact requires
    ob = client.get("/view/onboard", headers=auth(wtoken)).json()["output"]
    assert conventions["id"] in ob["unread"]
    assert rake["id"] not in ob["unread"]
    # required(id) shows both
    req = client.get("/view/required", params={"id": job["id"]},
                     headers=auth(wtoken)).json()["output"]
    assert req["unread"] == reading_list

    # ack honestly, then the claim goes through
    _post(world, wtoken, {
        "author": worker, "ns": "/proj/jobs", "type": "ACK", "grade": "n/a",
        "refs": [{"edge": "acks", "id": conventions["id"]},
                 {"edge": "acks", "id": rake["id"]}],
        "payload": "read both",
    })
    r = client.post("/post", headers=auth(wtoken), json={
        "proto": PROTO, "author": worker, "ns": "/proj/jobs", "type": "CLAIM",
        "grade": "n/a", "refs": [{"edge": "claims", "id": job["id"]}],
        "payload": "taking it, covered now",
        "ext": {"lease_until": "2030-01-01T00:00:00Z"},
    })
    assert r.status_code == 200, r.text

    # amortization: the drained onboard stays drained
    ob = client.get("/view/onboard", headers=auth(wtoken)).json()["output"]
    assert conventions["id"] not in ob["unread"]

    # and the annotation disappears once covered
    env = client.get(f"/envelope/{job['id']}", headers=auth(wtoken)).json()
    assert "required_unmet" not in env


def test_inbox_open_close_lifecycle(world: dict) -> None:
    """§7.1/R17 — any identity reaches the operator without project
    grants; only human band closes; the seeded canon pin puts the
    channel in a fresh identity's first onboard."""
    client = world["client"]
    agent, token = _register(world, "escalator")

    # a fresh identity's onboard leads with the inbox canon
    ob = client.get("/view/onboard", headers=auth(token)).json()["output"]
    assert len(ob["unread"]) == 1
    inbox_doc = client.get(f"/envelope/{ob['unread'][0]}", headers=auth(token)).json()
    assert "/korax/inbox" in inbox_doc["payload"]

    # band:* poster floor — no grants were issued to this identity
    opened = _post(world, token, {
        "author": agent, "ns": "/korax/inbox", "type": "OPEN", "grade": "n/a",
        "payload": "need a ruling: may /proj tighten its own view floor?",
    })

    # the operator's pending queue is just state on the nest
    pending = client.get("/view/state", params={"ns": "/korax/inbox"},
                         headers=auth(world["op_token"])).json()["output"]
    assert opened["id"] in pending["opens"]

    # closers: human — the escalator cannot resolve their own escalation
    r = client.post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/korax/inbox",
        "type": "FINDING", "grade": "n/a",
        "refs": [{"edge": "closes", "id": opened["id"]}],
        "payload": "never mind", "ext": {},
    })
    assert r.status_code == 403, r.text

    # the human closes, and the queue drains
    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/korax/inbox", "type": "FINDING",
        "grade": "n/a", "refs": [{"edge": "closes", "id": opened["id"]}],
        "payload": "ruled: yes, tightening is a POLICY like any other",
    })
    pending = client.get("/view/state", params={"ns": "/korax/inbox"},
                         headers=auth(world["op_token"])).json()["output"]
    assert opened["id"] not in pending["opens"]


def test_amend_quorum_gates_content_not_governance(world: dict) -> None:
    """§8.6 — the seeded canon nest demands 3 endorsements, but
    superseding its POLICY is governance and follows §8.5; on a young
    board the quorum must not lock governance shut. Content supersedes
    stay gated. (Bitten live on the deployed board's first act.)"""
    client = world["client"]
    # governance: the operator updates the canon policy — no proposal needed
    updated = _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/korax/canon", "type": "POLICY",
        "grade": "n/a", "refs": [{"edge": "supersedes", "id": 1}],
        "payload": {
            "acts": ["FINDING", "PIN", "ACK", "PROPOSAL", "SUPERSEDE",
                     "BESIDE", "STAMP", "POLICY"],
            "grades": True, "pin_posters": "maintainer", "max_pins": 8,
            "amend": {"propose_in": "/korax/meta", "min_endorsements": 3,
                      "adjudicator": "maintainer", "stamp_required": True},
            "grants": [{"identity": "band:*", "band": "reader"}],
        },
    })
    assert updated["type"] == "POLICY"

    # content: superseding a canon doc without a proposal stays refused
    doc = _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/korax/canon", "type": "FINDING",
        "grade": "verified", "payload": "canon doc v1",
    })
    r = client.post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/korax/canon",
        "type": "FINDING", "grade": "verified",
        "refs": [{"edge": "supersedes", "id": doc["id"]}],
        "payload": "canon doc v2 by fiat", "ext": {},
    })
    assert r.status_code == 409, r.text
    assert "PROPOSAL" in r.json()["message"]


def test_perch_is_served_at_root(world: dict) -> None:
    """The operator's view ships with the board: one page, no auth for
    the shell (its data calls carry the bearer token like any client)."""
    r = world["client"].get("/")
    assert r.status_code == 200
    assert "perch" in r.text
    assert "/view/onboard" in r.text  # the page drains onboard like anyone


def test_identity_creation_is_open_with_attribution(world: dict) -> None:
    """R18 — any authenticated identity may mint; the creator is
    recorded. A fresh band holds only the band:* floor, so the
    privilege boundary stays at the grant."""
    client = world["client"]
    agent, token = _register(world, "minter")
    r = client.post("/identity", json={"display": "self-made"}, headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created_by"] == agent

    # the fresh band can reach the inbox (band:* poster) but not, say,
    # post a FINDING to a project nest it holds no grant on
    fresh_token = body["token"]
    ok = client.post("/post", headers=auth(fresh_token), json={
        "proto": PROTO, "author": body["id"], "ns": "/korax/inbox",
        "type": "OPEN", "grade": "n/a", "refs": [],
        "payload": "grant request", "ext": {},
    })
    assert ok.status_code == 200, ok.text
    denied = client.post("/post", headers=auth(fresh_token), json={
        "proto": PROTO, "author": body["id"], "ns": "/proj/board",
        "type": "FINDING", "grade": "unverified", "refs": [],
        "payload": "sneaking in", "ext": {},
    })
    assert denied.status_code == 403
