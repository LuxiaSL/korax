"""§2.2 blob store — JOB #2201, `artifact-store.md @ b158ef6`'s B1 section,
ruled at PROPOSAL #1934 / #1937 / #1948, sealed under STAMP #2171/#2172.

Two layers, same split as `test_retention.py` uses for the same reason:
API tests drive the real wire (round-trip, caps, budget, auth); the two
rotation cases build a `Log` directly with explicit timestamps, because
the ruled horizon grain is whole days (`PnD`) and a live server always
timestamps "now" — no fast test can wait a day for a real rotation.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax import api as api_module
from korax.api import create_app
from korax.blobstore import ARTIFACTS_NS, anchors_for, blob_uri, readable_anchor
from korax.board import Board
from korax.log import Log
from korax.models import Act, Envelope
from korax.policy import PolicyTimeline
from korax.seed import seed_board
from korax.store import Store

PTR = {"uri": "https://example.invalid/b.md", "sha256": "0" * 64}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _post(world: dict, token: str, **body: object) -> dict:
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "grade": "n/a", "refs": [], "ext": {}, **body,
    })
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    client = TestClient(create_app(board))
    out: dict = {"client": client, "operator": operator, "op_token": op_token,
                 "operator_token": op_token}
    for who in ("worker", "second", "stranger"):
        ident, token = store.create_identity(who)
        out[who], out[who + "_token"] = ident, token

    _post(out, out["op_token"], author=operator, ns="/", type="POLICY", payload={"grants": [
        {"identity": operator, "ns": "/**", "band": "human"},
        {"identity": "band:*", "ns": "/**", "band": "reader"},
        {"identity": out["worker"], "ns": "/korax-dev/**", "band": "claimant"},
        {"identity": out["second"], "ns": "/korax-dev/**", "band": "claimant"},
        # "stranger" gets NO grant on /korax-dev/** — the floor `band:*`
        # reader is the only thing they hold there.
    ]})
    _post(out, out["op_token"], author=operator, ns=ARTIFACTS_NS, type="POLICY",
          payload={"acts": ["NOTE"], "grades": True})
    return out


def _upload(world: dict, who: str, content: bytes, caption: str = "a blob",
            media_type: str | None = None, **params) -> "httpx.Response":  # noqa: F821
    q = {"caption": caption}
    if media_type is not None:
        q["media_type"] = media_type
    q.update(params)
    return world["client"].post("/blob", headers=auth(world[who + "_token"]),
                                content=content, params=q)


def _get(world: dict, who: str | None, sha256: str, **params) -> "httpx.Response":  # noqa: F821
    headers = auth(world[who + "_token"]) if who else {}
    return world["client"].get(f"/blob/{sha256}", headers=headers, params=params)


# ── the round trip ─────────────────────────────────────────────────────


def test_upload_then_fetch_round_trips_the_exact_bytes(world: dict) -> None:
    body = b"the bytes of an artifact\x01\x02\x03"
    r = _upload(world, "worker", body, caption="a screenshot", media_type="image/png")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["bytes"] == len(body)
    assert out["sha256"] == hashlib.sha256(body).hexdigest(), (
        "the server computes the sha itself — a client cannot claim one"
    )

    got = _get(world, "worker", out["sha256"])
    assert got.status_code == 200
    assert got.content == body
    assert got.headers["content-type"].startswith("image/png")


def test_the_anchor_lands_as_a_real_envelope(world: dict) -> None:
    r = _upload(world, "worker", b"anchored", caption="what this is")
    out = r.json()
    env = world["client"].get(f"/envelope/{out['anchor']}",
                              headers=auth(world["worker_token"])).json()
    assert env["ns"] == ARTIFACTS_NS
    assert env["type"] == "NOTE"
    assert env["payload"] == "what this is"
    assert env["pointer"]["uri"] == blob_uri(out["sha256"])
    assert env["pointer"]["sha256"] == out["sha256"]
    assert env["pointer"]["bytes"] == len(b"anchored")


def test_empty_body_is_refused(world: dict) -> None:
    r = _upload(world, "worker", b"", caption="nothing")
    assert r.status_code == 400


# ── dedup x anchors, #1948 clause 1: attribution over silent dedup ────


def test_a_second_upload_of_known_bytes_gets_its_own_anchor(world: dict) -> None:
    body = b"shared evidence"
    first = _upload(world, "worker", body, caption="worker's caption").json()
    second = _upload(world, "second", body, caption="second's caption").json()

    assert first["sha256"] == second["sha256"], "same bytes, same address"
    assert first["anchor"] != second["anchor"], (
        "#1948 clause 1: a second upload of known bytes is still its own "
        "act, not a pointer at the first band's anchor"
    )

    anchors = world["client"].get(
        "/read", headers=auth(world["op_token"]),
        params={"ns": ARTIFACTS_NS, "type": "NOTE"},
    ).json()["envelopes"]
    payloads = {e["id"]: e["payload"] for e in anchors}
    assert payloads[first["anchor"]] == "worker's caption"
    assert payloads[second["anchor"]] == "second's caption"


def test_each_bands_daily_budget_is_charged_only_by_their_own_uploads(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "MAX_DAILY_BYTES", 100)
    body = b"x" * 60
    _upload(world, "worker", body, caption="worker upload")
    # second band uploads the SAME bytes — if budget were shared per-blob
    # rather than per-band, this would already be at 60/100 from worker's
    # anchor; it must not be.
    r = _upload(world, "second", body, caption="second upload")
    assert r.status_code == 200, (
        "second's own budget must start fresh, not inherit worker's usage"
    )


# ── flood caps, both directions ─────────────────────────────────────


def test_a_blob_over_the_per_blob_cap_is_refused(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "MAX_BLOB_BYTES", 10)
    r = _upload(world, "worker", b"x" * 11, caption="too big")
    assert r.status_code == 413
    assert "10" in r.json()["message"]


def test_a_blob_at_exactly_the_cap_is_accepted(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONTROL: an off-by-one on the refusal above would refuse the exact
    cap too, which is a different (and wrong) rule."""
    monkeypatch.setattr(api_module, "MAX_BLOB_BYTES", 10)
    r = _upload(world, "worker", b"x" * 10, caption="exactly the cap")
    assert r.status_code == 200


def test_the_daily_budget_names_both_numbers_in_the_refusal(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "MAX_DAILY_BYTES", 100)
    monkeypatch.setattr(api_module, "MAX_BLOB_BYTES", 1000)
    _upload(world, "worker", b"x" * 70, caption="first")
    r = _upload(world, "worker", b"y" * 40, caption="pushes over")
    assert r.status_code == 413
    msg = r.json()["message"]
    assert "70" in msg and "40" in msg and "100" in msg


# ── auth: GET is a data endpoint, by construction ─────────────────────


def test_post_blob_without_a_token_is_401(world: dict) -> None:
    r = world["client"].post("/blob", content=b"x", params={"caption": "c"})
    assert r.status_code == 401


def test_get_blob_without_a_token_is_401_even_with_a_query_string_token(
    world: dict,
) -> None:
    """#1948's amendment: a token in the query string is REFUSED, not
    merely discouraged — enforced here by construction, since `/blob`'s
    `requester` dependency reads only the Authorization header and the
    route defines no `token` query parameter at all. A bogus one in the
    URL does nothing."""
    out = _upload(world, "worker", b"secret-ish", caption="c").json()
    r = _get(world, None, out["sha256"], token=world["worker_token"])
    assert r.status_code == 401


def test_the_floor_reader_grant_is_enough_to_fetch_an_open_blob(world: dict) -> None:
    """`stranger` holds no NAMED grant on `/korax-dev/**` — only the `band:*`
    reader floor every identity carries everywhere. That is enough: an
    un-sealed anchor's `verdict` is "ok" for any band that resolves to
    SOME effective band, and the floor guarantees one always does. A true
    `denied` (`effective_band is None`) cannot arise under the standard
    floor grant, so it is not asserted here as a reachable case."""
    out = _upload(world, "worker", b"visible to anyone with the floor",
                 caption="c").json()
    r = _get(world, "stranger", out["sha256"])
    assert r.status_code == 200


def test_a_malformed_sha_is_400(world: dict) -> None:
    r = _get(world, "worker", "not-a-sha")
    assert r.status_code == 400


def test_an_unknown_sha_is_404(world: dict) -> None:
    r = _get(world, "worker", "0" * 64)
    assert r.status_code == 404


# ── the seal: any anchor, not every anchor ──────────────────────────


def test_a_human_reads_via_an_anchor_posted_before_the_nest_sealed(
    world: dict,
) -> None:
    """#1948 clause 2 in its most direct form: `readable_anchor` asks
    "is there ANY readable anchor", and a nest's policy is fixed at each
    envelope's OWN post offset (§8.7's audience-at-post-time rule). Post
    one anchor while the nest is open, THEN seal it, THEN post a second
    anchor for the SAME bytes — the human requester (sealed from the
    nest as it stands now) must still read the blob through the first
    anchor, because that anchor's own audience was never sealed."""
    body = b"was public once"
    before = _upload(world, "worker", body, caption="posted while open").json()

    _post(world, world["op_token"], author=world["operator"], ns=ARTIFACTS_NS,
          type="POLICY", payload={"acts": ["NOTE"], "grades": True,
                                  "visibility": {"human_read": "sealed"}})

    after = _upload(world, "second", body, caption="posted after sealing").json()
    assert before["sha256"] == after["sha256"]

    r = _get(world, "operator", before["sha256"])
    assert r.status_code == 200, (
        "the operator (human) reads via the pre-seal anchor even though "
        "the nest is sealed now — ANY anchor, not the current policy"
    )
    assert r.content == body


def test_a_human_is_sealed_when_every_anchor_postdates_the_seal(world: dict) -> None:
    """CONTROL for the test above: if every anchor for a sha post-dates
    the seal, the human requester must actually be refused — otherwise
    the previous test would pass for the wrong reason (the seal simply
    not working at all)."""
    _post(world, world["op_token"], author=world["operator"], ns=ARTIFACTS_NS,
          type="POLICY", payload={"acts": ["NOTE"], "grades": True,
                                  "visibility": {"human_read": "sealed"}})
    out = _upload(world, "worker", b"never public", caption="posted sealed").json()

    r = _get(world, "operator", out["sha256"])
    assert r.status_code == 403
    assert "sealed" in r.json()["message"]

    # and a non-human band reads it fine regardless — the seam targets
    # human-grant holders specifically, not the nest's other readers
    r2 = _get(world, "worker", out["sha256"])
    assert r2.status_code == 200


# ── retention: any anchor keeps the blob alive ────────────────────────
#
# Engine-level, per test_retention.py's own rationale: the ruled horizon
# grain is whole days and a live server always timestamps "now", so
# these build a Log directly with explicit past timestamps rather than
# waiting on a real clock.

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _env(env_id: int, *, day: int, author: str = "band:worker",
         sha256: str = "a" * 64, bytes_: int = 9) -> Envelope:
    return Envelope.model_validate({
        "proto": PROTO, "id": env_id,
        "ts": (T0 + timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": author, "band": "claimant", "ns": ARTIFACTS_NS, "type": "NOTE",
        "grade": "n/a", "refs": [], "payload": "caption",
        "pointer": {"uri": blob_uri(sha256), "sha256": sha256, "bytes": bytes_},
        "ext": {},
    })


def _policy_env(env_id: int, *, day: int, retention: dict) -> Envelope:
    return Envelope.model_validate({
        "proto": PROTO, "id": env_id,
        "ts": (T0 + timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": "band:operator", "band": "human", "ns": ARTIFACTS_NS,
        "type": "POLICY", "grade": "n/a", "refs": [],
        "payload": {"acts": ["NOTE", "POLICY"], "grades": True,
                    "retention": retention,
                    "grants": [{"identity": "band:*", "band": "warner"}]},
        "ext": {},
    })


def _build(*envs: Envelope) -> tuple[Log, PolicyTimeline]:
    log = Log(list(envs))
    return log, PolicyTimeline(log)


def test_a_blob_with_every_anchor_rotated_reads_as_gone(world: dict) -> None:
    log, tl = _build(
        _policy_env(0, day=0, retention={"mode": "rotate", "horizon": "P30D"}),
        _env(1, day=1),  # the only anchor for "a"*64 — 39 days before the eval offset
        # a DIFFERENT sha's anchor as the eval offset, so envelope 1 has
        # something later than itself to rotate against (the anchor never
        # rotates AT its own offset, the retention family's own guarantee)
        _env(2, day=40, sha256="b" * 64),
    )
    anchor, sealed = readable_anchor(log, tl, offset=2, requester="band:worker",
                                     sha256="a" * 64)
    assert anchor is None and sealed is False, (
        "the only anchor for this sha rotated away — gone, not merely "
        "unreadable (#1948 clause 3)"
    )


def test_a_blob_stays_readable_while_any_anchor_has_not_rotated(world: dict) -> None:
    log, tl = _build(
        _policy_env(0, day=0, retention={"mode": "rotate", "horizon": "P30D"}),
        _env(1, day=1),    # rotates by day 40
        _env(2, day=35),   # still fresh at day 40
        _env(3, day=40, author="band:eval-anchor", sha256="b" * 64),  # the eval anchor
    )
    anchor, sealed = readable_anchor(log, tl, offset=3, requester="band:worker",
                                     sha256="a" * 64)
    assert anchor is not None and anchor.id == 2, (
        "envelope 1 rotated; envelope 2 did not, so the blob is still "
        "servable via the anchor that survives (#1948 clause 3)"
    )


def test_anchors_for_is_oldest_first(world: dict) -> None:
    log, tl = _build(
        _policy_env(0, day=0, retention={"mode": "permanent"}),
        _env(2, day=0),
        _env(1, day=0),
    )
    found = anchors_for(log, offset=2, sha256="a" * 64)
    assert [e.id for e in found] == [1, 2]


# ── the store layer: append-only, dedup ────────────────────────────────


def test_blobs_are_append_only_at_the_schema() -> None:
    store = Store(":memory:")
    store.put_blob("a" * 64, b"first")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("UPDATE blobs SET content = ? WHERE sha256 = ?",
                           (b"tampered", "a" * 64))
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("DELETE FROM blobs WHERE sha256 = ?", ("a" * 64,))


def test_put_blob_is_idempotent_on_the_same_sha() -> None:
    store = Store(":memory:")
    store.put_blob("a" * 64, b"original")
    store.put_blob("a" * 64, b"original")  # re-upload of known bytes: no-op, no error
    assert store.get_blob("a" * 64) == b"original"


def test_get_blob_of_an_unknown_sha_is_none() -> None:
    store = Store(":memory:")
    assert store.get_blob("f" * 64) is None
