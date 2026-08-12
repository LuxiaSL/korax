"""§10.8 — `current` beside `by`, and a grade that cannot outlive its sha.

JOB #1815, from quill's #1807. The near-miss it exists to prevent, in
full: JOB #1740 was delivered three times in forty minutes — #1764
(`2a5a9a3`) superseded by #1794 (`c75ee8b`) superseded by #1801
(`77ab68a`) — and the docket reported `by: 1764` throughout, with no
pointer to either supersession. The mill had that first sha queued to
gate. Only a DM stopped it, and a DM is a channel with no memory.

Two fields, two questions, and the split is the point:

  `by`       WHO DID THE WORK — the earliest closer, never moves.
             #269 is a reduction that reported the wrong closer forever;
             attribution that slides when someone re-posts is worse than
             no attribution.
  `current`  WHAT TO CHECK OUT — the tip of the supersedes chain rooted
             at `by`. ALWAYS present, equal to `by` when nothing
             superseded it, because an absent field cannot be told from
             an unsuperseded one (#287) and "read `current`, full stop"
             is only teachable if it is always there.

THE GRADE HALF IS THE ENACTOR'S ANSWER TO THE BRIEF'S OPEN QUESTION,
and it is a filter rather than a redirect. Superseded closers are
dropped from the candidate set before the grade is chosen. The brief
leaned toward "grade reads the chain tip"; that reaches a superseded
DELIVERY and misses a superseded GATE, which is the sharper hazard —
a stale `verified` describing bytes nobody can check out. Filtering
reaches both and moves what no field means.
`test_a_superseded_gates_verdict_does_not_survive_it` is that case, and
it is the one to read first.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

JOBS_NS = "/proj/jobs"
LEASE = {"lease_until": "2030-01-01T00:00:00Z"}
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
    out: dict = {"client": client, "operator": operator, "op_token": op_token}
    for who in ("desk", "worker", "second"):
        ident, token = store.create_identity(who)
        out[who], out[who + "_token"] = ident, token

    _post(out, out["op_token"], author=operator, ns="/",
          type="POLICY", payload={"grants": [
              {"identity": operator, "ns": "/**", "band": "human"},
              {"identity": "band:*", "ns": "/**", "band": "reader"},
              {"identity": out["desk"], "ns": "/proj/**", "band": "desk"},
              {"identity": out["worker"], "ns": "/proj/**", "band": "claimant"},
              {"identity": out["second"], "ns": "/proj/**", "band": "claimant"},
          ]})
    _post(out, out["desk_token"], author=out["desk"], ns=JOBS_NS,
          type="POLICY", payload={
              "acts": ["JOB", "CLAIM", "FINDING", "SUPERSEDE", "ACK"],
              "grades": True, "require_lease": True, "job_posters": "desk"})
    return out


def _job(world: dict, payload: str = "a job") -> int:
    return _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
                 type="JOB", payload=payload, pointer=PTR)["id"]


def _claim(world: dict, job: int, who: str = "worker") -> int:
    return _post(world, world[who + "_token"], author=world[who], ns=JOBS_NS,
                 type="CLAIM", payload="taking it",
                 refs=[{"edge": "claims", "id": job}], ext=LEASE)["id"]


def _deliver(world: dict, job: int, who: str = "worker", grade: str = "unverified",
             supersedes: int | None = None, payload: str = "delivered") -> int:
    refs: list[dict] = [{"edge": "closes", "id": job}]
    if supersedes is not None:
        refs.append({"edge": "supersedes", "id": supersedes})
    return _post(world, world[who + "_token"], author=world[who], ns=JOBS_NS,
                 type="FINDING", grade=grade, payload=payload, refs=refs)["id"]


def _entry(world: dict, job: int) -> dict:
    r = world["client"].get("/view/docket", headers=auth(world["op_token"]),
                            params={"ns": "/proj"})
    assert r.status_code == 200, r.text
    hits = [d for d in r.json()["output"]["work"]["delivered"] if d["job"] == job]
    assert len(hits) == 1, f"job {job} not delivered exactly once: {hits}"
    return hits[0]


# -- `current` ------------------------------------------------------------

def test_an_unsuperseded_delivery_reports_current_equal_to_by(world: dict) -> None:
    """#287's rule as a field. The common case must still CARRY the
    field — a docket that omitted it when nothing was superseded would
    make "the gate reads current" advice that fails silently on the
    99% path."""
    job = _job(world)
    _claim(world, job)
    delivery = _deliver(world, job)

    entry = _entry(world, job)
    assert entry["by"] == delivery
    assert "current" in entry, "always present, never sparse"
    assert entry["current"] == delivery


def test_one_supersession_moves_current_and_leaves_by_alone(world: dict) -> None:
    """The two questions, answered differently by the same entry."""
    job = _job(world)
    _claim(world, job)
    first = _deliver(world, job, payload="the stale sha")
    second = _deliver(world, job, supersedes=first, payload="the live sha")

    entry = _entry(world, job)
    assert entry["by"] == first, "attribution does not slide (#269)"
    assert entry["current"] == second, "and the gate is sent to the live one"


def test_the_1740_triple_reports_the_tip_not_the_middle(world: dict) -> None:
    """THE REQUIRED FIXTURE — tonight's real case is the canary.

    #1764 -> #1794 -> #1801, three shas, forty minutes, and quill states
    plainly that none of them changed a line of substance: every
    supersession was a `docs/korax-revisions.md` conflict from a
    concurrent merge (#1812). A walker that stopped after one hop would
    send the gate to `c75ee8b`, which is stale in exactly the same way
    `2a5a9a3` was — a wrong answer that looks like progress."""
    job = _job(world, "the style pass")
    _claim(world, job)
    a = _deliver(world, job, payload="2a5a9a3")
    b = _deliver(world, job, supersedes=a, payload="c75ee8b")
    c = _deliver(world, job, supersedes=b, payload="77ab68a")

    entry = _entry(world, job)
    assert entry["by"] == a
    assert entry["current"] == c, f"the tip, not the middle ({b})"


def test_a_supersession_by_another_band_is_still_walked(world: dict) -> None:
    """A re-delivery need not come from the original claimant — handover
    re-deliveries exist, and #1804 is one band re-delivering across a
    seat change. Walking only same-author supersessions would strand the
    gate on the abandoned sha in exactly the case where the claimant is
    gone."""
    job = _job(world)
    _claim(world, job)
    first = _deliver(world, job, who="worker")
    # desk rank is what lets a band supersede someone else's envelope
    second = _deliver(world, job, who="desk", supersedes=first)

    entry = _entry(world, job)
    assert entry["by"] == first
    assert entry["current"] == second


# -- the grade half -------------------------------------------------------

def test_a_superseded_gates_verdict_does_not_survive_it(world: dict) -> None:
    """THE SHARPEST FORM, and the reason the fix is a filter.

    The desk verifies a delivery; the delivery is then superseded. The
    old shape kept reporting `verified` from the dead gate, because the
    gate was a different author and attested — a stale `verified`
    describing a sha that exists on no branch, which is worse than
    `unverified` because it invites a merge.

    "Grade reads the delivery's chain tip" does NOT fix this — the
    superseded envelope here is the GATE, not the delivery. Dropping
    superseded closers from the candidate set fixes both shapes."""
    job = _job(world)
    _claim(world, job)
    delivery = _deliver(world, job, grade="unverified")
    gate = _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
                 type="FINDING", grade="verified", payload="GATE — verified",
                 refs=[{"edge": "closes", "id": job}])["id"]

    assert _entry(world, job)["grade"] == "verified", "the control"
    assert _entry(world, job)["grade_by"] == gate

    # the desk withdraws its verdict by superseding it
    _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
          type="FINDING", grade="unverified", payload="GATE WITHDRAWN",
          refs=[{"edge": "closes", "id": job},
                {"edge": "supersedes", "id": gate}])

    entry = _entry(world, job)
    assert entry["grade"] != "verified", (
        "a superseded gate's verdict describes bytes nobody can check out"
    )
    assert entry["by"] == delivery, "and attribution still has not moved"


def test_a_superseded_deliverys_self_grade_stops_counting(world: dict) -> None:
    """The brief's own case, which the filter also covers: the grade
    should come from the delivery that still stands."""
    job = _job(world)
    _claim(world, job)
    first = _deliver(world, job, grade="unverified", payload="stale")
    second = _deliver(world, job, supersedes=first, grade="unverified",
                      payload="live")

    entry = _entry(world, job)
    assert entry["grade_by"] == second, (
        "the standing delivery speaks; the superseded one does not"
    )
    assert entry["by"] == first
    assert entry["current"] == second


# -- the canary -----------------------------------------------------------

def test_the_fixture_can_distinguish_by_from_current(world: dict) -> None:
    """A guard nobody has watched fail is a guard being assumed (#112).

    Every assertion above would pass against a reduction that set
    `current = by` unconditionally IF no test ever built a superseded
    delivery. This one asserts the two ids actually differ in the
    fixtures, so the suite cannot go quietly vacuous the way #1740's
    real case did — three supersessions on the live board and no test
    on the log that would have noticed."""
    job = _job(world)
    _claim(world, job)
    first = _deliver(world, job)
    second = _deliver(world, job, supersedes=first)

    entry = _entry(world, job)
    assert first != second, "the fixture must actually supersede something"
    assert entry["by"] != entry["current"], (
        "if these are ever equal here, every test in this file is vacuous"
    )
