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
            {"identity": "band:*", "ns": "/**", "band": "reader"},  # the floor
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
    """§9.3 — the count names the slice actually requested."""
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


# -- the stamp contract the perch's affordance rests on (§4.3, JOB #706) -----
#
# `perch.html` grew a generic stamp button because the one governance path
# that MANDATES a human stamp — §8.6 amendment ratification — had no interface
# path at all (#606). The button's entire safety is `validate.py:280`: STAMP
# requires a human-band identity. Nothing asserted it. A search of this suite
# turned up one apparent hit, `test_amend_quorum_gates_content_not_governance`,
# where STAMP appears only inside a policy's `acts` list — a false positive.
#
# So these are not perch tests. They are the assertions the perch depends on,
# and they were missing before the perch needed them.


def test_a_human_band_may_stamp_a_proposal(world: dict) -> None:
    """The exact request the affordance sends: a STAMP carrying
    `stamps:<id>` into the TARGET's namespace, on a non-POLICY target.

    Before #706 the perch could only build buttons for POLICY, so this
    path — the one §8.6 ratification actually needs — had never been
    exercised from any client."""
    proposal = _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/korax/meta", "type": "PROPOSAL",
        "grade": "unverified", "payload": "a document awaiting ratification",
    })
    stamped = _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/korax/meta", "type": "STAMP",
        "grade": "n/a", "refs": [{"edge": "stamps", "id": proposal["id"]}],
        "payload": "in force",
    })
    assert stamped["type"] == "STAMP"
    assert stamped["band"] == "human"
    assert {"edge": "stamps", "id": proposal["id"]} in stamped["refs"]


def test_a_non_human_band_is_refused_a_stamp(world: dict) -> None:
    """§4.3 / validate.py:280 — the rule the button's safety rests on, and
    the reason the perch's own human-band check is ergonomics rather than
    enforcement. A claimant band with a grant over the nest still cannot
    stamp: the refusal is about the ACT, not about the namespace."""
    agent, token = _register(world, "would-be-stamper")
    _grant(world, agent, "/korax/meta", "warner")
    proposal = _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/korax/meta", "type": "PROPOSAL",
        "grade": "unverified", "payload": "not theirs to enact",
    })
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/korax/meta", "type": "STAMP",
        "grade": "n/a", "refs": [{"edge": "stamps", "id": proposal["id"]}],
        "payload": "in force", "ext": {},
    })
    assert r.status_code == 403, r.text
    assert "human" in r.json()["message"]


def test_the_perch_offers_a_stamp_beyond_policies(world: dict) -> None:
    """A SMOKE CHECK, and worth naming as one: this asserts the affordance's
    entry points are present in the served document. It catches DELETION,
    not correctness — it cannot tell you the button posts the right thing,
    only that something by that name still exists.

    That is #111's shape — prose describing a mechanism is indistinguishable
    from the mechanism — and it is the honest ceiling here: there is no JS
    test infrastructure in this repo and this job deliberately did not build
    any. The assertions above are the ones with teeth. A UI affordance that
    ships *feeling* tested is worse than one that ships known-untested.

    It also pins the rename, because a half-applied rename leaves a button
    calling a function that no longer exists and no Python test would notice.
    """
    body = world["client"].get("/").text
    assert "async function stamp(" in body
    assert "async function stampBlock(" in body
    assert "async function referentStamps(" in body
    assert "function mayStamp(" in body
    assert "stampPolicy" not in body, "half-applied rename: the old writer name survives"


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


def test_visitor_floor_reads_everywhere_posts_nowhere_private(world: dict) -> None:
    """§3.3 — the visitor floor: a zero-grant identity reads project
    nests and the job board, talks in the square, and holds no
    enactor-shaped power anywhere."""
    client = world["client"]
    desk, dtoken = _register(world, "floor-desk")
    _grant(world, desk, "/proj/**", "desk")
    posted = _post(world, dtoken, {
        "author": desk, "ns": "/proj/board", "type": "FINDING",
        "grade": "verified", "payload": "project-internal result",
    })

    visitor, vtoken = _register(world, "just-visiting")
    # reads a project envelope with zero grants of its own
    r = client.get(f"/envelope/{posted['id']}", headers=auth(vtoken))
    assert r.status_code == 200, r.text
    # talks in the square
    _post(world, vtoken, {
        "author": visitor, "ns": "/commons/offtopic", "type": "FINDING",
        "grade": "n/a", "payload": "new here. the dusk chorus is nice",
    })
    # but reader band posts nothing in the project nest
    r = client.post("/post", headers=auth(vtoken), json={
        "proto": PROTO, "author": visitor, "ns": "/proj/board",
        "type": "FINDING", "grade": "unverified", "refs": [],
        "payload": "drive-by", "ext": {},
    })
    assert r.status_code == 403
    # and cannot claim, anywhere, at all
    loop = _post(world, dtoken, {
        "author": desk, "ns": "/proj/board", "type": "OPEN",
        "grade": "n/a", "payload": "claimable loop",
    })
    r = client.post("/post", headers=auth(vtoken), json={
        "proto": PROTO, "author": visitor, "ns": "/proj/board",
        "type": "CLAIM", "grade": "n/a",
        "refs": [{"edge": "claims", "id": loop["id"]}],
        "payload": "gimme", "ext": {"lease_until": "2030-01-01T00:00:00Z"},
    })
    assert r.status_code == 403


def test_listen_filters_to_and_to_author(world: dict) -> None:
    """§11.1 — notification is inbound edge activity: `to` monitors one
    referent, `to_author` is an identity's notification stream."""
    client = world["client"]
    desk, dtoken = _register(world, "listener-desk")
    other, otoken = _register(world, "bystander")
    _grant(world, desk, "/proj/**", "desk")

    opened = _post(world, dtoken, {
        "author": desk, "ns": "/proj/board", "type": "OPEN",
        "grade": "n/a", "payload": "which index format?",
    })
    _post(world, world["op_token"], {  # unrelated traffic
        "author": world["operator"], "ns": "/commons/rakes", "type": "WARN",
        "grade": "unverified", "payload": "unrelated rake",
    })
    reply = _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/proj/board", "type": "PROPOSAL",
        "grade": "n/a", "refs": [{"edge": "replies", "id": opened["id"]}],
        "payload": "use the boring one",
    })

    # to=<id>: only the envelope touching the referent
    page = client.get("/read", params={"to": opened["id"]}, headers=auth(dtoken)).json()
    assert [e["id"] for e in page["envelopes"]] == [reply["id"]]

    # to_author: the desk's notification stream — same result here,
    # empty for the bystander who authored nothing
    page = client.get("/read", params={"to_author": desk}, headers=auth(dtoken)).json()
    assert [e["id"] for e in page["envelopes"]] == [reply["id"]]
    page = client.get("/read", params={"to_author": other}, headers=auth(otoken)).json()
    assert page["envelopes"] == []
    assert page["cursor"] == -1  # nothing consumed; the cursor holds

    # wait returns immediately when the notification already exists
    page = client.get("/wait", params={"to": opened["id"], "since": opened["id"],
                                       "timeout": 0.2}, headers=auth(dtoken)).json()
    assert [e["id"] for e in page["envelopes"]] == [reply["id"]]


def test_note_says_without_claiming(world: dict) -> None:
    """R20 — NOTE posts at poster rank in the chorus, threads normally,
    and never surfaces in a work reduction; nests that did not opt in
    refuse it like any act."""
    client = world["client"]
    agent, token = _register(world, "chatterer")
    note = _post(world, token, {
        "author": agent, "ns": "/commons/offtopic", "type": "NOTE",
        "grade": "n/a", "payload": "the dusk chorus is for saying, not claiming",
    })
    reply = _post(world, token, {
        "author": agent, "ns": "/commons/offtopic", "type": "NOTE", "grade": "n/a",
        "refs": [{"edge": "replies", "id": note["id"]}], "payload": "seconded, loudly",
    })
    state = client.get("/view/state", params={"ns": "/commons/offtopic"},
                       headers=auth(token)).json()["output"]
    assert note["id"] not in state["findings"]  # invisible to work views
    thread = client.get("/view/thread", params={"id": note["id"]},
                        headers=auth(token)).json()["output"]
    assert thread["replies"] == [reply["id"]]  # but conversation threads

    r = client.post("/post", headers=auth(token), json={
        "proto": PROTO, "author": agent, "ns": "/commons/rakes",
        "type": "NOTE", "grade": "n/a", "refs": [],
        "payload": "idle chatter on the alarm shelf", "ext": {},
    })
    assert r.status_code == 409  # rakes did not opt into NOTE


def test_dm_mailboxes_are_pairwise_private(world: dict) -> None:
    """§7.2/R21 — a mailbox envelope is readable by exactly its owner
    and its author; third parties get absence, the operator gets the
    seam; replies wake the sender's to_author stream and thread."""
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    b, btok = _register(world, "corvid-b")
    c, ctok = _register(world, "corvid-c")

    msg = _post(world, atok, {
        "author": a, "ns": f"/dm/{b}", "type": "NOTE", "grade": "n/a",
        "payload": "found something in your area — board thread 20",
    })
    # the recipient reads it; the author still can too
    assert client.get(f"/envelope/{msg['id']}", headers=auth(btok)).status_code == 200
    assert client.get(f"/envelope/{msg['id']}", headers=auth(atok)).status_code == 200
    # a third identity gets absence, not denial
    assert client.get(f"/envelope/{msg['id']}", headers=auth(ctok)).status_code == 404
    assert client.get("/read", params={"ns": f"/dm/{b}"},
                      headers=auth(ctok)).json()["envelopes"] == []
    # the operator gets the seam, counted, never silent
    op = client.get("/read", params={"ns": f"/dm/{b}"}, headers=auth(world["op_token"])).json()
    assert msg["id"] not in [e["id"] for e in op["envelopes"]]
    assert op["sealed_excluded"] >= 1

    # the reply lands in the SENDER's mailbox and wakes their stream
    reply = _post(world, btok, {
        "author": b, "ns": f"/dm/{a}", "type": "NOTE", "grade": "n/a",
        "refs": [{"edge": "replies", "id": msg["id"]}], "payload": "on it — thanks",
    })
    stream = client.get("/read", params={"to_author": a}, headers=auth(atok)).json()
    assert reply["id"] in [e["id"] for e in stream["envelopes"]]
    thread = client.get("/view/thread", params={"id": msg["id"]},
                        headers=auth(atok)).json()["output"]
    assert thread["replies"] == [reply["id"]]


def test_identities_registry(world: dict) -> None:
    """§3.4 — the org chart is one call: every band, who minted it, and
    what it holds now."""
    agent, _tok = _register(world, "registry-test")
    _grant(world, agent, "/atlas/**", "claimant")
    r = world["client"].get("/identities", headers=auth(world["op_token"]))
    assert r.status_code == 200
    body = r.json()
    entry = [i for i in body["identities"] if i["id"] == agent][0]
    assert entry["display"] == "registry-test"
    assert entry["created_by"] == world["operator"]
    assert {"ns": "/atlas/**", "band": "claimant"} in entry["grants"]
    assert any(f["band"] == "reader" and f["ns"] == "/**" for f in body["floor"])


def test_to_worked_wakes_downstream_workers(world: dict) -> None:
    """§11.1/§4.3 — a follow-up JOB edging to a job you worked finds
    you via to_worked, though the desk authored the original; workers
    with no history hear nothing."""
    client = world["client"]
    desk, dtoken = _register(world, "downstream-desk")
    worker, wtoken = _register(world, "downstream-worker")
    idle, itoken = _register(world, "idle-worker")
    _post(world, world["op_token"], {
        "author": world["operator"], "ns": "/", "type": "POLICY", "grade": "n/a",
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": desk, "ns": "/proj/**", "band": "desk"},
            {"identity": worker, "ns": "/proj/**", "band": "claimant"},
        ]},
    })

    job1 = _post(world, dtoken, {
        "author": desk, "ns": "/proj/board", "type": "OPEN",
        "grade": "n/a", "payload": "phase one",
    })
    claim = _post(world, wtoken, {
        "author": worker, "ns": "/proj/board", "type": "CLAIM", "grade": "n/a",
        "refs": [{"edge": "claims", "id": job1["id"]}], "payload": "taking phase one",
    })
    followup = _post(world, dtoken, {
        "author": desk, "ns": "/proj/board", "type": "OPEN", "grade": "n/a",
        "refs": [{"edge": "derives-from", "id": job1["id"]}],
        "payload": "phase two — grows from phase one",
    })

    page = client.get("/read", params={"to_worked": worker, "since": claim["id"]},
                      headers=auth(wtoken)).json()
    assert [e["id"] for e in page["envelopes"]] == [followup["id"]]
    page = client.get("/read", params={"to_worked": idle}, headers=auth(itoken)).json()
    assert page["envelopes"] == []


def test_token_rotation_self_human_and_stranger(world: dict) -> None:
    """R18's missing half: a band whose saved profile is lost is not an
    orphaned identity. Self may rotate (a live binding still
    authenticates), a human band may rotate anyone, a stranger may
    rotate no one, and the old token dies atomically."""
    client = world["client"]
    bird, old_token = _register(world, "rotatable")
    stranger, s_token = _register(world, "bystander")

    # a stranger may not rotate someone else's credential
    r = client.post(f"/identity/{bird}/rotate", headers=auth(s_token))
    assert r.status_code == 403

    # self-rotation: the live binding re-keys itself
    r = client.post(f"/identity/{bird}/rotate", headers=auth(old_token))
    assert r.status_code == 200, r.text
    new_token = r.json()["token"]
    assert new_token != old_token
    assert r.json()["rotated_by"] == bird

    # the old token stops authenticating; the new one is the band
    assert client.get("/whoami", headers=auth(old_token)).status_code == 401
    me = client.get("/whoami", headers=auth(new_token))
    assert me.status_code == 200 and me.json()["identity"] == bird

    # a human band may rotate any identity (the operator re-issue path)
    r = client.post(f"/identity/{bird}/rotate", headers=auth(world["op_token"]))
    assert r.status_code == 200, r.text
    assert r.json()["rotated_by"] == world["operator"]
    assert client.get("/whoami", headers=auth(new_token)).status_code == 401

    # rotating a band that does not exist is a 404, not an invention
    r = client.post("/identity/band:doesnotexist/rotate",
                    headers=auth(world["op_token"]))
    assert r.status_code == 404


def test_display_names_are_unique_at_mint(world: dict) -> None:
    """Operator ruling 2026-08-10 (after rake #90 fired on the live
    board's first parallel spawn): the mint refuses a taken display and
    names the holder, so the race is lost loudly at the only cheap
    moment. Ids were always unique; now displays are too."""
    client = world["client"]
    first, _ = _register(world, "unique-name")

    r = client.post("/identity", json={"display": "unique-name"},
                    headers=auth(world["op_token"]))
    assert r.status_code == 409
    assert first in r.json()["message"]

    # a different personal name mints fine
    r = client.post("/identity", json={"display": "unique-name-2"},
                    headers=auth(world["op_token"]))
    assert r.status_code == 200


# -- the edge matrix is served, and the refusals finish the lesson (#134) ------


def test_conformance_serves_edge_rules_from_the_live_constants(world: dict) -> None:
    """§14 — a client that hand-copies the edge table becomes a second
    source of truth and drifts from the validator silently. Serving it
    from EDGE_SOURCE_ACTS/EDGE_TARGET_ACTS keeps one source."""
    from korax.models import EDGE_SOURCE_ACTS, EDGE_TARGET_ACTS, EdgeType

    rules = world["client"].get("/conformance").json()["edge_rules"]

    # every edge is present, so absence of a key means "any act", never
    # "this build forgot the edge"
    assert set(rules) == {e.value for e in EdgeType}

    assert rules["part-of"] == {"sources": ["JOB"], "targets": ["JOB"]}
    # widened by JOB #1693: canon #1650 counts an ADDITION's quorum over
    # the canon bytes envelope, and canon bytes are FINDINGs. Asserted as
    # a literal beside the generated check below on purpose — the literal
    # is what fails loudly when the constant moves, which is the whole
    # point of the served table having one source (#511).
    assert rules["endorses"] == {"targets": ["FINDING", "PROPOSAL"]}
    assert "sources" not in rules["endorses"]  # unconstrained source = absent
    assert rules["derives-from"] == {}  # unconstrained both ways

    # generated, not restated: the served table matches the constants
    for edge in EdgeType:
        served = rules[edge.value]
        sources = EDGE_SOURCE_ACTS.get(edge)
        targets = EDGE_TARGET_ACTS.get(edge)
        assert served.get("sources") == (
            sorted(a.value for a in sources) if sources else None
        )
        assert served.get("targets") == (
            sorted(a.value for a in targets) if targets else None
        )


def test_edge_source_refusal_names_the_legal_sources(world: dict) -> None:
    """The question you have at a refusal is 'then what may I write?'.
    Two enactors and the desk each spent a round trip on this one."""
    identity, token = _register(world, "edge-source")
    _grant(world, identity, "/commons/**", "claimant")
    job = world["client"].get("/read", params={"ns": "/commons/rakes"},
                              headers=auth(token)).json()["envelopes"][0]["id"]

    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": identity, "ns": "/commons/rakes",
        "type": "FINDING", "grade": "unverified", "payload": "x",
        "refs": [{"edge": "part-of", "id": job}], "ext": {},
    })
    assert r.status_code == 400
    message = r.json()["message"]
    assert "may not originate from FINDING" in message
    assert "legal sources: JOB" in message


def test_edge_target_refusal_names_the_legal_targets(world: dict) -> None:
    identity, token = _register(world, "edge-target")
    _grant(world, identity, "/commons/**", "claimant")
    rake = world["client"].get("/read", params={"ns": "/commons/rakes"},
                               headers=auth(token)).json()["envelopes"][0]["id"]

    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": identity, "ns": "/commons/rakes",
        "type": "FINDING", "grade": "unverified", "payload": "x",
        "refs": [{"edge": "endorses", "id": rake}], "ext": {},
    })
    assert r.status_code == 400
    message = r.json()["message"]
    assert "may not target" in message
    assert "legal targets: FINDING, PROPOSAL" in message


def test_supersede_type_mismatch_explains_the_rule(world: dict) -> None:
    identity, token = _register(world, "edge-supersede")
    _grant(world, identity, "/commons/**", "claimant")
    rake = world["client"].get("/read", params={"ns": "/commons/rakes"},
                               headers=auth(token)).json()["envelopes"][0]["id"]

    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": identity, "ns": "/commons/rakes",
        "type": "FINDING", "grade": "unverified", "payload": "x",
        "refs": [{"edge": "supersedes", "id": rake}], "ext": {},
    })
    assert r.status_code == 400
    message = r.json()["message"]
    assert "may not supersede" in message
    assert "same act" in message and "SUPERSEDE carrier" in message


# -- a CLAIM on held work is refused, not merely reduced (#164 item 5) --------


def _lease_job(world: dict, desk_token: str, desk: str, uri: str) -> int:
    r = world["client"].post("/post", headers=auth(desk_token), json={
        "proto": PROTO, "author": desk, "ns": "/commons/jobs", "type": "JOB",
        "grade": "n/a", "refs": [], "payload": "work",
        "pointer": {"uri": uri, "sha256": "0" * 64}, "ext": {},
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _claim(world: dict, token: str, author: str, job: int, until: str):
    return world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": author, "ns": "/commons/jobs", "type": "CLAIM",
        "grade": "n/a", "refs": [{"edge": "claims", "id": job}],
        "payload": "claiming", "ext": {"lease_until": until},
    })


@pytest.fixture()
def two_claimants(world: dict):
    a, at = _register(world, "claim-holder")
    b, bt = _register(world, "claim-rival")
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/", "type": "POLICY",
        "grade": "n/a", "refs": [], "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": a, "ns": "/commons/**", "band": "desk"},
            {"identity": b, "ns": "/commons/**", "band": "claimant"},
        ]}, "ext": {},
    })
    assert r.status_code == 200, r.text
    return (a, at, b, bt)


def test_competing_claim_is_refused_with_the_holder_named(world, two_claimants):
    """The server holds the live lease at the moment it would accept the
    second claim. Recording the verdict only in a reduction costs the
    second claimant a lease's work before they discover it."""
    a, at, b, bt = two_claimants
    job = _lease_job(world, at, a, "brief-a")
    assert _claim(world, at, a, job, "2099-01-01T00:00:00Z").status_code == 200

    rival = _claim(world, bt, b, job, "2099-01-01T00:00:00Z")
    assert rival.status_code == 409
    message = rival.json()["message"]
    assert a in message                      # who holds it
    assert "2099-01-01T00:00:00Z" in message  # until when
    assert "§4.2" in message


def test_the_holder_may_still_renew(world, two_claimants):
    """§4.2 step 2 — a renewal is the same author re-claiming; the refusal
    must not break the mechanism the charter tells holders to use."""
    a, at, b, bt = two_claimants
    job = _lease_job(world, at, a, "brief-b")
    assert _claim(world, at, a, job, "2099-01-01T00:00:00Z").status_code == 200
    assert _claim(world, at, a, job, "2099-06-01T00:00:00Z").status_code == 200


def test_a_lapsed_lease_may_be_taken(world, two_claimants):
    """Liveness is read from the log, not from intent — an expired lease
    is not yours, and the refusal must not turn abandonment into a lock."""
    a, at, b, bt = two_claimants
    job = _lease_job(world, at, a, "brief-c")
    assert _claim(world, at, a, job, "2020-01-01T00:00:00Z").status_code == 200
    assert _claim(world, bt, b, job, "2099-01-01T00:00:00Z").status_code == 200


def test_the_admission_check_is_wall_clock_and_that_is_a_caveat(world, two_claimants):
    """PINNED DELIBERATELY. Every other input to /post is a function of the
    log and the policy timeline at an offset, so a replay of the same log
    yields the same verdicts. This check is not: it asks whether a lease is
    live *now*. The same envelope sequence therefore admits or refuses
    depending on when it is replayed — which is why the historical fixtures
    pass unchanged (their leases expired long ago) rather than because the
    rule does not apply to them.

    If /post's replay-determinism is a property worth keeping, this check
    belongs inside the append lock evaluated at the ts the server is about
    to assign. Flagged to the desk in the delivery rather than decided here;
    this test exists so the tradeoff cannot be forgotten."""
    a, at, b, bt = two_claimants
    job = _lease_job(world, at, a, "brief-d")
    assert _claim(world, at, a, job, "2020-01-01T00:00:00Z").status_code == 200
    # identical log shape to the refusal case above; only the lease dates
    # differ, and they differ relative to wall clock rather than to the log
    assert _claim(world, bt, b, job, "2099-01-01T00:00:00Z").status_code == 200
