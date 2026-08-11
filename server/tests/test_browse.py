"""The browse ranking — JOB #1308; design PROPOSAL #1294, endorsed #1295.

Four properties, from the brief's acceptance section:

  * Orderings on a fixture with COMPUTED expectations — a known edge
    structure whose scores are hand-derived in this file from the spec's
    formula, never eyeballed against the implementation's own output.
  * Reproducibility (D3): the same `at` yields the same ordering across
    two calls separated by new envelopes past the offset — log time is
    the board's clock, so an offset's ordering is fixed forever.
  * The visibility property (D1): two requesters with different slices
    get different scores for the same envelope, each equal to the score
    of their OWN slice — the §9.3 seam holds through the score.
  * No per-band aggregate anywhere in the response (D5): the grouping is
    unstateable at the signature level, and this asserts the response
    side of that refusal.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.log import Log
from korax.models import Envelope
from korax.reductions import browse
from korax.seed import seed_board
from korax.store import Store

NS = "/n/board"
T0 = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def _at(hours: float) -> str:
    ts = T0.timestamp() + hours * 3600
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env(id: int, hours: float, author: str, refs: list[dict], ns: str = NS) -> Envelope:
    return Envelope.model_validate({
        "proto": PROTO, "id": id, "ts": _at(hours), "author": author,
        "band": "claimant", "ns": ns, "type": "FINDING", "grade": "n/a",
        "refs": refs, "payload": f"line one of #{id}\nrest", "ext": {},
    })


@pytest.fixture()
def fixture_log() -> Log:
    """A known edge structure where hot and top must ORDER DIFFERENTLY:
    #1 is cited three times, all old; #4 is cited twice, both recent.

        #1 @ 0h   <- replies #2 @ 1h; derives-from + corroborates #3 @ 2h
        #4 @ 40h  <- replies #5 @ 47h; derives-from #6 @ 48h (the anchor)
    """
    return Log([
        _env(1, 0, "band:a", []),
        _env(2, 1, "band:b", [{"edge": "replies", "id": 1}]),
        _env(3, 2, "band:c", [
            {"edge": "derives-from", "id": 1},
            {"edge": "corroborates", "id": 1},
        ]),
        _env(4, 40, "band:a", []),
        _env(5, 47, "band:b", [{"edge": "replies", "id": 4}]),
        _env(6, 48, "band:d", [{"edge": "derives-from", "id": 4}]),
    ])


# Hand-derived from the spec's formula (half-life P1D = 24h), never from
# the implementation: score = Σ 0.5 ** (Δ_hours / 24) over inbound edges,
# Δ against the ts of #6, the envelope at the offset.
HOT_1 = 0.5 ** (47 / 24) + 2 * (0.5 ** (46 / 24))   # cited at 1h and twice at 2h
HOT_4 = 0.5 ** (1 / 24) + 0.5 ** (0 / 24)           # cited at 47h and at 48h


def _scores(out: dict) -> dict[int, float]:
    return {e["id"]: e["score"] for e in out["entries"]}


def test_hot_ordering_matches_hand_derived_scores(fixture_log: Log) -> None:
    out = browse(fixture_log, 6, NS, sort="hot", half_life="P1D")
    assert [e["id"] for e in out["entries"]] == [4, 1, 6, 5, 3, 2]
    scores = _scores(out)
    assert scores[1] == pytest.approx(HOT_1, abs=1e-6)
    assert scores[4] == pytest.approx(HOT_4, abs=1e-6)
    # a citation AT the evaluation moment decays by nothing: #6's edge
    # contributes exactly 1.0 to #4
    assert scores[4] > 1.0
    # the uncited score to zero, newest first among the tied
    assert scores[6] == scores[5] == scores[3] == scores[2] == 0.0
    # D3's legibility rule: the parameter that shaped the ordering ships
    # in the response
    assert out["half_life"] == "P1D"
    assert out["eval_ts"] == _at(48)


def test_top_is_the_undecayed_sum_and_orders_differently(fixture_log: Log) -> None:
    out = browse(fixture_log, 6, NS, sort="top")
    scores = _scores(out)
    # D2: ALL inbound edge types count, and each edge counts — #3 cites
    # #1 twice (derives-from + corroborates), so #1 carries 3, not 2
    assert scores[1] == 3.0
    assert scores[4] == 2.0
    assert [e["id"] for e in out["entries"]][:2] == [1, 4]
    # one scoring function, two settings — and the settings disagree on
    # this fixture, which is what proves decay did the work in `hot`
    hot = browse(fixture_log, 6, NS, sort="hot", half_life="P1D")
    assert [e["id"] for e in hot["entries"]][:2] == [4, 1]
    assert out["half_life"] is None  # decay 1 has no half-life to report


def test_recent_is_id_descending_and_unscored(fixture_log: Log) -> None:
    out = browse(fixture_log, 6, NS, sort="recent")
    assert [e["id"] for e in out["entries"]] == [6, 5, 4, 3, 2, 1]
    assert all("score" not in e for e in out["entries"])
    assert out["half_life"] is None


def test_same_offset_same_ordering_as_the_log_grows(fixture_log: Log) -> None:
    """D3 — decay anchors to eval_ts AT THE OFFSET, never wall clock, so
    envelopes appended past the offset change nothing behind it."""
    before = browse(fixture_log, 6, NS, sort="hot", half_life="P1D")
    grown = Log(fixture_log.envelopes + [
        # a later burst of citations onto #1, which would flip the
        # ordering if anything leaked past the offset
        _env(7, 500, "band:e", [{"edge": "replies", "id": 1}]),
        _env(8, 501, "band:e", [{"edge": "corroborates", "id": 1}]),
    ])
    after = browse(grown, 6, NS, sort="hot", half_life="P1D")
    assert before == after
    # and at the new head the burst counts
    head = browse(grown, 8, NS, sort="top")
    assert _scores(head)[1] == 5.0


def test_the_bound_renders_as_a_bound(fixture_log: Log) -> None:
    out = browse(fixture_log, 6, NS, sort="recent", limit=2)
    assert len(out["entries"]) == 2
    assert out["total"] == 6  # what the limit dropped is on the page


def test_offset_without_an_anchor_scores_nothing(fixture_log: Log) -> None:
    """`fresh`'s doctrine (JOB #1092): a predicate that needs a clock is
    FALSE when there is no clock. `recent` needs no clock and survives."""
    holey = Log([e for e in fixture_log.envelopes if e.id != 6])
    assert browse(holey, 6, NS, sort="hot")["entries"] == []
    assert browse(holey, 6, NS, sort="hot")["eval_ts"] is None
    assert [e["id"] for e in browse(holey, 6, NS, sort="recent")["entries"]] == \
        [5, 4, 3, 2, 1]


def test_bad_arguments_raise_value_error(fixture_log: Log) -> None:
    with pytest.raises(ValueError):
        browse(fixture_log, 6, NS, sort="by-author")
    with pytest.raises(ValueError):
        browse(fixture_log, 6, NS, sort="hot", half_life="P0D")
    with pytest.raises(ValueError):
        browse(fixture_log, 6, NS, sort="hot", half_life="soon")


# -- the API surface ----------------------------------------------------


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _post(world: dict, token: str, **body: object) -> dict:
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "grade": "n/a", "refs": [], "ext": {}, **body,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _browse(world: dict, token: str, **params: object) -> dict:
    r = world["client"].get("/view/browse", headers=auth(token), params=params)
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
    out: dict = {
        "store": store, "board": board, "client": client,
        "operator": operator, "op_token": op_token,
    }
    for who in ("desk", "worker", "outsider"):
        ident, token = store.create_identity(who)
        out[who] = ident
        out[who + "_token"] = token
    _post(out, op_token, author=operator, ns="/", type="POLICY", payload={
        "grants": [
            {"identity": operator, "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": out["desk"], "ns": "/proj/**", "band": "desk"},
            {"identity": out["worker"], "ns": "/proj/**", "band": "claimant"},
            {"identity": out["outsider"], "ns": "/proj/**", "band": "claimant"},
        ]})
    _post(out, out["desk_token"], author=out["desk"], ns="/proj/board",
          type="POLICY", payload={
              "acts": ["FINDING", "NOTE", "OPEN", "SUPERSEDE", "ACK"],
              "grades": True})
    return out


def test_two_requesters_two_slices_two_scores(world: dict) -> None:
    """D1 — the score is computed AFTER access filtering, per requester.

    The finding is cited once publicly and once from a DM the desk
    cannot read. The DM's author and its owner each score 2; the desk
    scores 1 — each figure exactly the sum over that requester's OWN
    visible edges, which is all §9.3 lets a score be."""
    f = _post(world, world["desk_token"], author=world["desk"],
              ns="/proj/board", type="FINDING", payload="the target")
    _post(world, world["worker_token"], author=world["worker"], ns="/proj/board",
          type="NOTE", payload="public citation",
          refs=[{"edge": "derives-from", "id": f["id"]}])
    _post(world, world["worker_token"], author=world["worker"],
          ns=f"/dm/{world['outsider']}", type="NOTE",
          payload="private citation",
          refs=[{"edge": "derives-from", "id": f["id"]}])

    def score(token: str) -> float:
        out = _browse(world, token, ns="/proj", sort="top")["output"]
        return {e["id"]: e["score"] for e in out["entries"]}[f["id"]]

    assert score(world["worker_token"]) == 2.0   # author of the DM
    assert score(world["outsider_token"]) == 2.0  # owner of the mailbox
    assert score(world["desk_token"]) == 1.0      # the DM is not in its slice
    # the desk's page says its view was bounded, so a smaller number is
    # legible as a slice rather than as the whole (§9.3)
    r = world["client"].get("/view/browse", headers=auth(world["desk_token"]),
                            params={"ns": "/proj", "sort": "top"})
    assert r.json()["participation_excluded"] != 0


def _no_band_keyed_dict(node: object) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            assert not str(key).startswith("band:"), (
                f"response carries a per-band aggregate keyed {key!r} — D5"
            )
            _no_band_keyed_dict(value)
    elif isinstance(node, list):
        for item in node:
            _no_band_keyed_dict(item)


def test_no_per_band_aggregate_in_the_response(world: dict) -> None:
    """D5 — the response side of the structural refusal. An entry names
    its own author (envelope metadata); nothing in the response maps a
    band to a number, so a leaderboard is not assemblable from keys."""
    f = _post(world, world["desk_token"], author=world["desk"],
              ns="/proj/board", type="FINDING", payload="target")
    _post(world, world["worker_token"], author=world["worker"], ns="/proj/board",
          type="NOTE", payload="cite",
          refs=[{"edge": "derives-from", "id": f["id"]}])
    for sort in ("hot", "recent", "top"):
        _no_band_keyed_dict(_browse(world, world["worker_token"],
                                    ns="/proj", sort=sort))


def test_api_reproducibility_across_new_posts(world: dict) -> None:
    """The acceptance test as written in the brief: the same `at` yields
    the same ordering across two calls separated by new envelopes."""
    f = _post(world, world["desk_token"], author=world["desk"],
              ns="/proj/board", type="FINDING", payload="target")
    _post(world, world["worker_token"], author=world["worker"], ns="/proj/board",
          type="NOTE", payload="cite",
          refs=[{"edge": "derives-from", "id": f["id"]}])
    at = world["board"].head
    before = _browse(world, world["worker_token"], ns="/proj", sort="hot", at=at)
    for i in range(3):
        _post(world, world["worker_token"], author=world["worker"],
              ns="/proj/board", type="NOTE", payload=f"later citation {i}",
              refs=[{"edge": "derives-from", "id": f["id"]}])
    after = _browse(world, world["worker_token"], ns="/proj", sort="hot", at=at)
    assert before["output"] == after["output"]


def test_browse_is_a_rotating_view() -> None:
    """§8.2 — rotation bounds discovery, not reference, and browse is
    discovery: a scroll over a nest must not resurface envelopes the
    nest's own horizon has rotated out. The gate lives in `/view`'s
    ROTATING_VIEWS membership, which is exactly one token — this pins it
    against the refactor that drops it silently."""
    from korax.api import ROTATING_VIEWS
    assert "browse" in ROTATING_VIEWS


def test_bad_arguments_are_422_never_500(world: dict) -> None:
    for params in ({"ns": "/proj", "sort": "by-author"},
                   {"ns": "/proj", "sort": "hot", "half_life": "soon"},
                   {"ns": "/proj", "sort": "hot", "half_life": "P0D"}):
        r = world["client"].get("/view/browse", headers=auth(world["worker_token"]),
                                params=params)
        assert r.status_code == 422, (params, r.status_code, r.text)
