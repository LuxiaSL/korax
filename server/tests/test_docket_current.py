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

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.models import Act, Band, Envelope, Grade
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


# -- `merged`: what a GATE says it merged (ISSUE #1900, JOB #1970) --------
#
# `current` is the deliverer's chain tip and answers "what should I check
# out". After a gate those two questions come apart: JOB #1740's entry
# reports `current: 1826` (`627befd`) while main carries `77ab68a`, and
# `git merge-base --is-ancestor 627befd main` says no. Every gate on this
# board already names its sha — in PROSE, where no reduction can read it.

SHA_A = "a" * 40
SHA_B = "b" * 40


def _gate_with_sha(world: dict, job: int, sha: object, who: str = "desk",
                   grade: str = "verified") -> int:
    return _post(world, world[who + "_token"], author=world[who], ns=JOBS_NS,
                 type="FINDING", grade=grade, payload="GATE",
                 refs=[{"edge": "closes", "id": job}],
                 ext={"korax": {"merged_sha": sha}})["id"]


def test_merged_is_absent_until_a_gate_names_one(world: dict) -> None:
    """PRESENT ONLY WHEN KNOWN, and #287 does not reach this.

    #287 forbids an absent field where a real value exists and absence
    could be read as a value — which is why `current` is always there.
    `merged` has no degenerate value: before a gate there IS no merged
    sha, and a `null` would be a value meaning "absent", which is the
    confusion #287 forbids rather than the cure for it."""
    job = _job(world)
    _claim(world, job)
    _deliver(world, job)

    entry = _entry(world, job)
    assert "merged" not in entry
    assert "current" in entry, "the always-present one is still always there"


def test_a_gate_naming_its_sha_puts_it_on_the_entry(world: dict) -> None:
    job = _job(world)
    _claim(world, job)
    delivery = _deliver(world, job)
    _gate_with_sha(world, job, SHA_A)

    entry = _entry(world, job)
    assert entry["merged"] == SHA_A
    assert entry["by"] == delivery, "#269 — attribution still does not move"
    assert entry["current"] == delivery, "#287 — nor does the checkout target"


def test_the_deliverer_cannot_name_their_own_merged_sha(world: dict) -> None:
    """The field means "a gate merged this". A claimant naming a merged
    sha on their own delivery is claiming an act they do not perform —
    the mill merges, and #1900 is about making the mill's own prose
    machine-readable, not about letting anyone assert a merge."""
    job = _job(world)
    _claim(world, job)
    _post(world, world["worker_token"], author=world["worker"], ns=JOBS_NS,
          type="FINDING", grade="unverified", payload="delivered",
          refs=[{"edge": "closes", "id": job}],
          ext={"korax": {"merged_sha": SHA_A}})

    assert "merged" not in _entry(world, job)


def test_a_re_gate_names_the_later_sha(world: dict) -> None:
    """A re-merge after a bounce gets a second gate; the entry must
    follow it rather than freezing on the first."""
    job = _job(world)
    _claim(world, job)
    _deliver(world, job)
    _gate_with_sha(world, job, SHA_A)
    _gate_with_sha(world, job, SHA_B, who="second", grade="unverified")

    assert _entry(world, job)["merged"] == SHA_B


@pytest.mark.parametrize("bad", [None, 12345, "", "   ", ["a" * 40], {"sha": 1}])
def test_a_malformed_merged_sha_is_ignored_and_never_raises(
    world: dict, bad: object
) -> None:
    """`ext` is caller-supplied JSON preserved verbatim under §13, so
    every level of it can be any type. A reduction that raised on one
    band's typo would take down the docket, which is the one call a
    session opens with."""
    job = _job(world)
    _claim(world, job)
    _deliver(world, job)
    _gate_with_sha(world, job, bad)

    entry = _entry(world, job)
    assert "merged" not in entry
    assert entry["grade"] == "verified", "the gate still counts for the grade"


def test_a_non_dict_korax_ext_is_ignored_at_the_reader(world: dict) -> None:
    """Unit, not end-to-end, and the reason is worth recording: the
    write path ALREADY refuses `ext.korax` as a non-dict —

        400  ext.korax: top-level ext keys must be reserved (...) or
             namespaced as ext.<project>.<field> (§2.4)

    — so this state cannot be reached through `/post` today, and a test
    that tried would be asserting the validator rather than the reader.
    The guard stays because a reduction reads whatever is ON the log,
    which outlives the validation in force when it was written (§13
    preserves unknown elements verbatim, and this board has changed its
    ext rules before). Defence in depth, tested where it lives."""
    from korax.reductions import _merged_sha

    def env(ext: dict) -> Envelope:
        return Envelope(
            proto=PROTO, id=1, ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
            author="band:x", band=Band.DESK, ns=JOBS_NS, type=Act.FINDING,
            grade=Grade.VERIFIED, ext=ext,
        )

    assert _merged_sha(env({})) is None
    assert _merged_sha(env({"korax": "not-a-dict"})) is None
    assert _merged_sha(env({"korax": ["also", "not"]})) is None
    assert _merged_sha(env({"korax": {"merged_sha": None}})) is None
    assert _merged_sha(env({"korax": {"merged_sha": "  " + SHA_A + " "}})) == SHA_A


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
