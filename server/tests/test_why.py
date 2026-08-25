"""`why` the reduction — the semantics, ported from the client suite.

JOB #3765. These assertions lived in `clients/{mcp,cli}/tests/test_why.py`
against the client-side composition (#2269). The composition is gone;
the semantics are not, so they move here rather than being deleted with
the code that used to host them. **A test that pins behaviour is not the
composition's property — it is the verb's**, and dropping twenty of them
because the file they lived in moved would be a coverage loss wearing
cleanup's clothes.

What is NEW rather than ported is `gated`'s narrowing (property 3) and
`not-applicable` for un-gateable subjects (property 4), each with its
own section below.
"""

from __future__ import annotations

from typing import Any

import pytest

from korax.board import Board
from korax.seed import seed_board
from korax.store import Store
from korax.why import why


class Scene:
    """A board with a desk, a worker and helpers — the shapes `why`
    reasons about, built as real envelopes rather than hand-written
    neighbourhood dicts. The client tests used dicts because they had no
    board; the reduction has one, so the fixtures are the real thing."""

    def __init__(self) -> None:
        self.store = Store(":memory:")
        self.operator, self.op_token = self.store.create_identity("operator")
        self.store.set_meta("genesis_identity", self.operator)
        self.board = Board(self.store)
        seed_board(self.board, self.operator)
        self.desk, _ = self.store.create_identity("a-desk")
        self.worker, _ = self.store.create_identity("a-worker")
        self.post(self.operator, ns="/", type="POLICY", payload={"grants": [
            {"identity": self.operator, "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": self.desk, "ns": "/p/**", "band": "desk"},
            {"identity": self.worker, "ns": "/p/**", "band": "claimant"},
        ]})

    def post(self, author: str, **kw: Any):
        body = {"proto": "korax/0.1", "author": author, "grade": "n/a",
                "refs": [], "ext": {}, **kw}
        return self.board.append(author, body)

    def why(self, env_id: int) -> dict[str, Any]:
        return why(self.board.log, self.board.head, env_id)

    def answers(self, env_id: int) -> dict[str, Any]:
        return self.why(env_id)["answers"]

    def route(self, env_id: int, name: str) -> dict[str, Any]:
        return next(r for r in self.why(env_id)["routes"] if r["route"] == name)

    def job(self, **kw: Any):
        return self.post(self.desk, ns="/p/jobs", type="JOB", grade="unverified",
                         payload="a job",
                         pointer={"uri": "git:b.md@a", "sha256": "b" * 64}, **kw)

    def delivery(self, job_id: int, marker: bool = True, **kw: Any):
        ext = {"korax": {"delivery": {"sha": "d" * 40, "branch": "w/x"}}} if marker else {}
        return self.post(self.worker, ns="/p/jobs", type="FINDING",
                         grade="unverified", payload="DELIVERED",
                         refs=[{"edge": "closes", "id": job_id}], ext=ext, **kw)


@pytest.fixture()
def s() -> Scene:
    return Scene()


# ── ported: every route reports, and the three statuses are distinct ──


def test_every_declared_route_reports_even_when_everything_is_empty(s: Scene) -> None:
    body = s.why(1)
    assert [r["route"] for r in body["routes"]] == body["routes_declared"]
    for r in body["routes"]:
        assert r["basis"], f"{r['route']} emitted no basis"
        assert "count" in r


def test_searched_and_not_applicable_are_different_facts(s: Scene) -> None:
    """An empty `found` means nothing until you read the status beside
    it — #2183 family A, the defect this verb was cut to remove."""
    note = s.post(s.worker, ns="/p/jobs", type="NOTE", grade="unverified", payload="hi")
    assert s.route(note.id, "inbound-edges")["status"] == "searched"
    # no outbound edges and no pointer: two routes CANNOT apply, and say so
    assert s.route(note.id, "closes-on-target")["status"] == "not-applicable"
    assert s.route(note.id, "sha-in-prose")["status"] == "not-applicable"


def test_a_not_applicable_reason_names_the_subject_not_the_board(s: Scene) -> None:
    """Acceptance 4. `not-applicable` is a property OF THIS SUBJECT; a
    reason phrased about the board would read as 'nothing found'."""
    note = s.post(s.worker, ns="/p/jobs", type="NOTE", grade="unverified", payload="hi")
    for name in ("closes-on-target", "attested-on-target", "sha-in-prose"):
        basis = s.route(note.id, name)["basis"]
        assert "NOTE" in basis, f"{name}'s basis does not name the subject's act: {basis}"


# ── ported: what counts as an attestation ──


def test_n_a_is_not_an_attestation(s: Scene) -> None:
    """`n/a` is the ABSENCE of grading, assigned by the board for every
    ungraded nest — reading it as attestation would label a whole nest
    gated."""
    job = s.job()
    d = s.delivery(job.id)
    s.post(s.desk, ns="/p/jobs", type="FINDING", grade="n/a", payload="a note on it",
           refs=[{"edge": "replies", "id": d.id}])
    assert s.answers(d.id)["gated"]["answer"] is False


def test_unverified_is_not_an_attestation(s: Scene) -> None:
    job = s.job()
    d = s.delivery(job.id)
    s.post(s.desk, ns="/p/jobs", type="FINDING", grade="unverified", payload="looking",
           refs=[{"edge": "replies", "id": d.id}])
    assert s.answers(d.id)["gated"]["answer"] is False


def test_verified_is_an_attestation__control(s: Scene) -> None:
    """THE CONTROL for the two above — a `gated` that never fired would
    pass both of them while making the key useless."""
    job = s.job()
    d = s.delivery(job.id)
    gate = s.post(s.desk, ns="/p/jobs", type="FINDING", grade="verified",
                  payload="GATE", refs=[{"edge": "replies", "id": d.id}])
    ans = s.answers(d.id)["gated"]
    assert ans["answer"] is True and ans["ids"] == [gate.id]


def test_an_inbound_stamp_gates_the_subject(s: Scene) -> None:
    """`stamped` is an EFFECTIVE grade that never appears in the `grade`
    field, so it is caught on the EDGE. Testing the grade alone would
    answer 'nothing gated this' about a stamped envelope."""
    job = s.job()
    d = s.delivery(job.id)
    stamp = s.post(s.operator, ns="/p/jobs", type="STAMP", payload="ratified",
                   refs=[{"edge": "stamps", "id": d.id}])
    ans = s.answers(d.id)["gated"]
    assert ans["answer"] is True and stamp.id in ans["ids"]


def test_the_write_path_already_refuses_a_below_desk_verified(s: Scene) -> None:
    """Property 3 names desk rank, and the rank check in `gated` is
    DEFENCE IN DEPTH rather than a live filter — say so rather than
    shipping a test that cannot fail.

    `grade: verified` requires desk band and is *rejected, not
    downgraded* (§6.1, `validate.py`), and a STAMP requires a human band
    (§1.1.5). Both attesting roads are therefore closed to a claimant at
    the WRITE path, so no log can contain the envelope the rank check in
    `summarise` exists to skip. A test asserting "a below-desk verified
    FINDING does not gate" would be unbuildable through the normal road
    and, written against a hand-forged log, would pin a branch nothing
    can reach — a dead branch reading as coverage of the rank rule
    (`test_why_contract`'s own argument about `stamped`, one field over).

    So this pins the invariant the rank check leans on instead: the
    board refuses it first. If that ever stops being true, this reddens
    and the check in `gated` becomes load-bearing rather than redundant.
    """
    from korax.validate import PostError

    job = s.job()
    d = s.delivery(job.id)
    with pytest.raises(PostError, match="requires desk band"):
        s.post(s.worker, ns="/p/jobs", type="FINDING", grade="verified",
               payload="I say it is fine", refs=[{"edge": "replies", "id": d.id}])
    assert s.answers(d.id)["gated"]["answer"] is False


# ── NEW: property 3 — `gated` answers only what its name asks ──


def test_gated_is_not_fed_by_attestations_on_the_subjects_targets(s: Scene) -> None:
    """JOB #3765's defect, pinned. A `verified` FINDING on the JOB this
    delivery closes is an attestation about the JOB, not about this
    envelope — it belongs under `attested_on_targets` and nowhere else.

    The historical cost is measured and disclosed (#4020): 24 of 100
    verified deliveries on the live board are gated this way and read
    `false` here. That cohort is closed — every gate since the cutover
    carries an edge to the delivery, binding since #3895 (#4021).
    """
    job = s.job()
    d = s.delivery(job.id)
    gate = s.post(s.desk, ns="/p/jobs", type="FINDING", grade="verified",
                  payload="verified", refs=[{"edge": "closes", "id": job.id}])
    ans = s.answers(d.id)
    assert ans["gated"]["answer"] != True, (  # noqa: E712 — `indirect` is truthy
        "a target attestation must not read as an attestation on THIS envelope"
    )
    assert ans["gated"]["answer"] == "indirect", "it is reported as what it is (#4022)"
    assert gate.id in ans["attested_on_targets"]["ids"], "and is not LOST either"


def test_attested_on_targets_carries_what_gated_used_to(s: Scene) -> None:
    """Acceptance 2's second half — relabelled, never dropped."""
    job = s.job()
    d = s.delivery(job.id)
    gate = s.post(s.desk, ns="/p/jobs", type="FINDING", grade="verified",
                  payload="GATE", refs=[{"edge": "closes", "id": job.id},
                                        {"edge": "replies", "id": d.id}])
    ans = s.answers(d.id)
    assert ans["gated"]["ids"] == [gate.id]
    assert ans["attested_on_targets"]["ids"] == [gate.id]


# ── NEW: property 4 — a subject that cannot be gated says so ──


def test_an_open_reports_gated_not_applicable(s: Scene) -> None:
    """Acceptance 1, the live categorical instance (#3700): an OPEN is
    not a delivery, so `false` would assert a gate was looked for."""
    opn = s.post(s.worker, ns="/p/jobs", type="OPEN", grade="unverified", payload="a loop")
    g = s.answers(opn.id)["gated"]
    assert g["answer"] == "not-applicable"
    assert "OPEN" in g["reason"]


def test_an_ungated_delivery_reports_false_not_not_applicable(s: Scene) -> None:
    """Acceptance 3 — the distinction that makes `not-applicable` mean
    something. A marker-carrying delivery with no gate WAS looked for."""
    job = s.job()
    d = s.delivery(job.id)
    assert s.answers(d.id)["gated"]["answer"] is False


def test_a_delivery_closing_a_job_is_gateable_without_the_marker(s: Scene) -> None:
    """The pre-#2073 road onto the lane: no marker, but it closes a JOB."""
    job = s.job()
    d = s.delivery(job.id, marker=False)
    assert s.answers(d.id)["gated"]["answer"] is False  # gateable, and ungated


# ── ported: the subject is never its own answer ──


def test_the_subject_is_never_reported_as_its_own_answer(s: Scene) -> None:
    job = s.job()
    d = s.delivery(job.id)
    body = s.why(d.id)
    for r in body["routes"]:
        assert all(c.get("id") != d.id for c in r["found"]), (
            f"{r['route']} returned the subject as its own answer"
        )


# ── ported: separate questions answer separately ──


def test_supersedes_and_closes_answer_separately(s: Scene) -> None:
    job = s.job()
    d = s.delivery(job.id)
    # `closes` may not target a FINDING (§5), so the two questions are
    # asked of the two subjects that can actually carry them — which is
    # itself the light-track asymmetry #3879 §3 measured.
    sup = s.post(s.worker, ns="/p/jobs", type="FINDING", grade="unverified",
                 payload="v2", refs=[{"edge": "supersedes", "id": d.id}])
    ans_delivery = s.answers(d.id)
    assert ans_delivery["superseded"]["ids"] == [sup.id]
    assert ans_delivery["disposed"]["ids"] == [], "a supersede is not a disposal"

    ans_job = s.answers(job.id)
    assert d.id in ans_job["disposed"]["ids"], "the delivery closes the JOB"
    assert ans_job["superseded"]["ids"] == [], "and nothing supersedes the JOB"


def test_inbound_edges_carry_the_2205_split_as_a_label(s: Scene) -> None:
    """State-changing vs conversational, as a LABEL and never a refusal."""
    job = s.job()
    d = s.delivery(job.id)
    s.post(s.worker, ns="/p/jobs", type="FINDING", grade="unverified", payload="v2",
           refs=[{"edge": "supersedes", "id": d.id}])
    s.post(s.desk, ns="/p/jobs", type="FINDING", grade="unverified", payload="re",
           refs=[{"edge": "replies", "id": d.id}])
    cards = {c["id"]: c for c in s.route(d.id, "inbound-edges")["found"]}
    assert any("supersedes" in c["asserting_edges"] for c in cards.values())
    assert any("replies" in c["conversational_edges"] for c in cards.values())


def test_invalidates_is_absent_from_the_ruled_set(s: Scene) -> None:
    """Deliberately absent pending #2242 — a client that ran ahead of the
    ruling would put its opinion where a ruling belongs."""
    from korax.why import STATE_CHANGING
    assert "invalidates" not in STATE_CHANGING


# ── ported: the sha route ──


def test_the_sha_route_finds_a_quote_in_prose(s: Scene) -> None:
    """A branch sha travels in prose far more than it travels in edges —
    no walk reaches it."""
    job = s.job()
    quoting = s.post(s.desk, ns="/p/jobs", type="FINDING", grade="unverified",
                     payload=f"merged {'b' * 64} tonight")
    found = s.route(job.id, "sha-in-prose")["found"]
    assert [c["id"] for c in found] == [quoting.id]


def test_a_subject_with_no_pointer_says_the_route_cannot_apply(s: Scene) -> None:
    note = s.post(s.worker, ns="/p/jobs", type="NOTE", grade="unverified", payload="x")
    r = s.route(note.id, "sha-in-prose")
    assert r["status"] == "not-applicable" and r["count"] == 0


# ── ported: bounds ride up, per source ──


def test_bounds_are_reported_per_source_and_never_summed(s: Scene) -> None:
    """Acceptance 8. Summing across routes produces a number naming no
    scope at all (§9.3)."""
    job = s.job()
    bounds = s.why(job.id)["bounds"]
    sources = {row["source"] for row in bounds["sources"]}
    assert sources == set(s.why(job.id)["routes_declared"]), (
        "every route must account for what it could not see"
    )
    assert "total" not in bounds, "a summed total names no scope"
    for row in bounds["sources"]:
        assert "withheld_scope" in row and "status" in row


# ── NEW: `gated: indirect`, ruled at #4022 ──


def test_the_historical_gating_shape_reports_indirect(s: Scene) -> None:
    """Ruling #4022 amendment 1, direction one. #800's shape: the gate
    closes the JOB and carries NO edge to the delivery. The attestation
    exists and lives one hop away, so neither binary is true — `true`
    claims an edge that is not there, `false` tells the reader the verb
    was built for that its founding delivery was never gated."""
    job = s.job()
    d = s.delivery(job.id)
    gate = s.post(s.desk, ns="/p/jobs", type="FINDING", grade="verified",
                  payload="verified, merged", refs=[{"edge": "closes", "id": job.id}])
    g = s.answers(d.id)["gated"]
    assert g["answer"] == "indirect"
    assert g["ids"] == [gate.id]
    assert g["reason"], "`indirect` must say where the attestation actually sits"


def test_no_attestation_anywhere_stays_false__control(s: Scene) -> None:
    """Ruling #4022 amendment 1, direction two — THE CONTROL. An
    `indirect` that fired whenever `true` did not would make the key
    useless in the other direction."""
    job = s.job()
    d = s.delivery(job.id)
    s.post(s.desk, ns="/p/jobs", type="FINDING", grade="unverified",
           payload="just looking", refs=[{"edge": "closes", "id": job.id}])
    assert s.answers(d.id)["gated"]["answer"] is False


def test_a_direct_gate_outranks_an_indirect_one(s: Scene) -> None:
    """When both exist the answer is `true`, not `indirect` — the
    stronger fact wins and the weaker one is still in
    `attested_on_targets`."""
    job = s.job()
    d = s.delivery(job.id)
    gate = s.post(s.desk, ns="/p/jobs", type="FINDING", grade="verified",
                  payload="GATE", refs=[{"edge": "closes", "id": job.id},
                                        {"edge": "replies", "id": d.id}])
    ans = s.answers(d.id)
    assert ans["gated"]["answer"] is True and ans["gated"]["ids"] == [gate.id]
    assert ans["attested_on_targets"]["ids"] == [gate.id]
