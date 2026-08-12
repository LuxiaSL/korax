"""§10.12 — `ungated`: finished work still waiting on a gate.

JOB #1970, closing ISSUE #1664. The three blind shapes the gavel
dossiered at #1753 are not three defects — `work` is keyed on the JOB
and the unit of work is the `closes` EDGE, so restating the membership
test collapses all three at once:

    light track   no CLAIM  #1835 — the fix to the mill's OWN filed
                            issue, invisible for over an hour: "no
                            instrument I run displayed it" (#1968)
    issue track   no JOB    #1779 — ungated through TEN merges, carried
                            only by two handovers (#1958 §A.1)
    design track  no grade  permanently `unattested` (#1747)

The two historical fixtures are required by the brief and are the first
two tests here. Read `test_the_lanes_are_distinguishable` before
believing any of it: a fixture where gated and ungated happen to
coincide certifies nothing (#1898's praise for R106's self-canary), and
`test_nothing_pending_reports_an_empty_lane` is the one that keeps this
surface worth reading — a pending list that always has something in it
is #921's guard that raises on everything.
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
ISSUES_NS = "/proj/issues"
BOARD_NS = "/proj/board"
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
    for who in ("desk", "desk2", "worker", "second"):
        ident, token = store.create_identity(who)
        out[who], out[who + "_token"] = ident, token

    # `desk2` exists because `verified` is refused below desk rank at the
    # write path, so "a DIFFERENT band gates it" cannot be written with a
    # claimant. Two desks is also the live shape: the gavel and the mill.
    _post(out, out["op_token"], author=operator, ns="/",
          type="POLICY", payload={"grants": [
              {"identity": operator, "ns": "/**", "band": "human"},
              {"identity": "band:*", "ns": "/**", "band": "reader"},
              {"identity": out["desk"], "ns": "/proj/**", "band": "desk"},
              {"identity": out["desk2"], "ns": "/proj/**", "band": "desk"},
              {"identity": out["worker"], "ns": "/proj/**", "band": "claimant"},
              {"identity": out["second"], "ns": "/proj/**", "band": "claimant"},
          ]})
    for ns in (JOBS_NS, ISSUES_NS, BOARD_NS):
        _post(out, out["desk_token"], author=out["desk"], ns=ns,
              type="POLICY", payload={
                  "acts": ["JOB", "OPEN", "CLAIM", "FINDING", "SUPERSEDE", "ACK"],
                  "grades": True, "job_posters": "desk"})
    return out


# -- fixture builders -----------------------------------------------------

def _job(world: dict, payload: str = "a job") -> int:
    return _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
                 type="JOB", payload=payload, pointer=PTR)["id"]


def _issue(world: dict, who: str = "worker", payload: str = "an issue") -> int:
    return _post(world, world[who + "_token"], author=world[who], ns=ISSUES_NS,
                 type="OPEN", payload=payload)["id"]


def _deliver(world: dict, target: int, who: str = "worker",
             grade: str = "unverified", ns: str = JOBS_NS,
             supersedes: int | None = None, payload: str = "delivered") -> int:
    refs: list[dict] = [{"edge": "closes", "id": target}]
    if supersedes is not None:
        refs.append({"edge": "supersedes", "id": supersedes})
    return _post(world, world[who + "_token"], author=world[who], ns=ns,
                 type="FINDING", grade=grade, payload=payload, refs=refs)["id"]


def _gate(world: dict, target: int, grade: str = "verified",
          who: str = "desk", ns: str = JOBS_NS) -> int:
    return _post(world, world[who + "_token"], author=world[who], ns=ns,
                 type="FINDING", grade=grade, payload=f"GATE — {grade}",
                 refs=[{"edge": "closes", "id": target}])["id"]


def _ungated(world: dict, identity: str | None = None) -> list[dict]:
    params: dict = {"ns": "/proj"}
    if identity is not None:
        params["identity"] = identity
    r = world["client"].get("/view/docket", headers=auth(world["op_token"]),
                            params=params)
    assert r.status_code == 200, r.text
    return r.json()["output"]["ungated"]


def _totals(world: dict, identity: str | None = None) -> dict:
    params: dict = {"ns": "/proj"}
    if identity is not None:
        params["identity"] = identity
    r = world["client"].get("/view/docket", headers=auth(world["op_token"]),
                            params=params)
    return r.json()["output"]["totals"]


# -- the two historical fixtures the brief requires -----------------------

def test_the_issue_track_shape_1779_no_job_no_claim(world: dict) -> None:
    """#1779's shape: a delivery closing an ISSUE. No JOB was ever cut,
    so `work` cannot see it — it never enters `delivered` because there
    is no job to key an entry on, and the ISSUE leaves `filed` the
    moment the delivery lands. **On the real board this sat through ten
    merges**, visible only in two handovers I wrote myself."""
    issue = _issue(world, payload="the stale NO_JITTER comment")
    delivery = _deliver(world, issue, payload="branch @ 156326c")

    entries = _ungated(world)
    assert [e["closes"] for e in entries] == [issue]
    assert entries[0]["by"] == delivery
    assert entries[0]["target"] == "OPEN"
    assert entries[0]["grade"] == "unverified"

    # and the thing that made it invisible: no job, so nothing in `work`
    r = world["client"].get("/view/docket", headers=auth(world["op_token"]),
                            params={"ns": "/proj"})
    work = r.json()["output"]["work"]
    assert work["delivered"] == []
    assert work["open"] == [] and work["taken"] == []


def test_the_light_track_shape_1835_a_job_exists_but_no_claim(world: dict) -> None:
    """#1835's shape: the light track deliberately carries no CLAIM —
    that is what makes it light (#1433). Here the target is a JOB, so
    `delivered` DOES see it; the lane must still list it, because
    `delivered` answers "what happened to job X" and says nothing about
    whether anyone has gated it."""
    job = _job(world, "the bump 409 fallback")
    delivery = _deliver(world, job, payload="branch @ 23603e4")

    entries = _ungated(world)
    assert [e["closes"] for e in entries] == [job]
    assert entries[0]["by"] == delivery
    assert entries[0]["target"] == "JOB"

    # it is in BOTH lanes, deliberately — two questions, two answers,
    # the `by`/`current` precedent from R106.
    r = world["client"].get("/view/docket", headers=auth(world["op_token"]),
                            params={"ns": "/proj"})
    delivered = r.json()["output"]["work"]["delivered"]
    assert [d["job"] for d in delivered] == [job]


def test_the_fourth_shape_a_delivery_in_the_board_nest(world: dict) -> None:
    """#1995's shape, named by the mill AFTER this was built and covered
    by it — so this fixture exists to keep it covered on purpose rather
    than by luck.

    quill's #1928: ISSUE filed in the issues nest, delivery posted to the
    BOARD nest, no JOB and no CLAIM anywhere. It sat an hour while the
    mill read `docket` four times and told the operator twice that
    nothing was ungated. The mill's own diagnosis is the right one —
    *the gate's instrument is keyed on the jobs nest while a light
    delivery may legitimately live anywhere* — and it is a fourth face
    of the same defect rather than a new one.

    Membership here is `in_subtree(project, env.ns)`, so any nest under
    the project qualifies. That was a deliberate choice and it is one
    line from being undone by someone narrowing the scan to the jobs
    nest for speed."""
    issue = _issue(world, payload="ISSUE: the write path accepts NUL")
    delivery = _deliver(world, issue, ns=BOARD_NS,
                        payload="DELIVERED, light track @ 5821bde")

    entries = _ungated(world)
    assert [e["by"] for e in entries] == [delivery]
    assert entries[0]["ns"] == BOARD_NS, "the nest is reported, not assumed"
    assert entries[0]["closes"] == issue

    # the three surfaces that were blind to it, still blind — which is
    # why the lane had to exist rather than the others being widened
    r = world["client"].get("/view/docket", headers=auth(world["op_token"]),
                            params={"ns": "/proj"})
    out = r.json()["output"]
    assert out["work"]["delivered"] == [], "no JOB — `work` cannot see it"
    assert out["filed"] == [], "the ISSUE closed — it left `filed` on delivery"


def test_a_gate_takes_it_out_of_the_lane(world: dict) -> None:
    """The other direction, and the reason the lane is readable at all."""
    job = _job(world)
    _deliver(world, job)
    assert len(_ungated(world)) == 1

    _gate(world, job)
    assert _ungated(world) == []


# -- the design-track terminal case ---------------------------------------

def test_a_desk_n_a_close_is_terminal_not_debt(world: dict) -> None:
    """Shape three (#1747): a design job's acceptance cannot be
    `verified` — there is nothing to reproduce — so the gate grades it
    `n/a`, and without this case the entry would read as debt forever."""
    job = _job(world, "design: the seam")
    _deliver(world, job, payload="the design", grade="n/a")
    assert len(_ungated(world)) == 1, "pending until the desk accepts"

    _gate(world, job, grade="n/a")
    assert _ungated(world) == [], "the desk's n/a is acceptance (#1387)"


def test_a_claimants_n_a_close_is_not_acceptance(world: dict) -> None:
    """Anyone may post `n/a`; only a desk's carries acceptance. Without
    the band check the terminal case would let any band clear any
    delivery by saying nothing at all."""
    job = _job(world)
    _deliver(world, job)
    _gate(world, job, grade="n/a", who="second")  # a claimant, not the desk

    assert [e["closes"] for e in _ungated(world)] == [job]


def test_a_sub_desk_verified_on_the_log_does_not_gate(world: dict) -> None:
    """The band is checked for `verified` too, and the counterexample is
    in this repo: `conformance/fixture-09.jsonl:9` is a `verified`
    FINDING recorded with band `claimant`, hand-authored into a Log that
    never met `validate.py`. Fixtures, imported logs and other
    implementations all reach a reduction without reaching the write
    path, so a reduction that trusts the write path's refusal is trusting
    an invariant it cannot see.

    Constructed at the reduction rather than through `/post`, because
    `/post` correctly refuses to create it — asserting through the API
    here would test the validator, not this rule."""
    from korax.reductions import _gates

    def closer(band: Band, grade: Grade) -> Envelope:
        return Envelope(
            proto=PROTO, id=99, ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
            author="band:someone-else", band=band, ns=JOBS_NS,
            type=Act.FINDING, grade=grade,
        )

    assert _gates(closer(Band.DESK, Grade.VERIFIED)) is True
    assert _gates(closer(Band.DESK, Grade.NA)) is True
    assert _gates(closer(Band.MAINTAINER, Grade.VERIFIED)) is True
    assert _gates(closer(Band.HUMAN, Grade.NA)) is True
    assert _gates(closer(Band.CLAIMANT, Grade.VERIFIED)) is False, (
        "fixture-09:9's shape — on the log, refused by the write path"
    )
    assert _gates(closer(Band.CLAIMANT, Grade.NA)) is False
    assert _gates(closer(Band.DESK, Grade.UNVERIFIED)) is False, (
        "a desk saying 'not yet' is the opposite of a gate"
    )


def test_a_desks_own_envelope_at_the_root_is_the_disposition(world: dict) -> None:
    """THIS TEST ASSERTED THE OPPOSITE UNTIL THE LIVE BOARD DISAGREED,
    and the flip is deliberate — see #2006 and the mill's #2008.

    It used to read `test_the_deliverer_cannot_gate_their_own_work` and
    hold that a desk delivering its own work and grading it `verified`
    is unreviewed work with a good grade. The reasoning was R106's
    `grade_source: "self"`: a self-grade is not an attestation.

    That reasoning is fine and it is not the only case. On the live
    board the same predicate filed **22 of 39 entries** as debt when
    they were dispositions — every administrative close a desk has ever
    posted, plus every gate whose delivery cited its issue with
    `derives-from` instead of `closes`, because then the GATE is the
    sole closer and the lane asks who gated the gate. On an append-only
    log those never leave.

    **A single desk-band envelope closing something with `verified` is
    byte-identical to an administrative close.** The distinction I
    encoded cannot be drawn from the log, and a predicate that guesses
    at intent from nothing is worse than one that reports what the
    envelope says. `grade_source: "self"` on the `delivered` entry
    beside is where a reader learns which it was."""
    job = _job(world)
    _deliver(world, job, who="desk", grade="verified")

    assert _ungated(world) == [], (
        "a desk's own envelope at the root IS the disposition"
    )


def test_an_administrative_close_is_not_debt(world: dict) -> None:
    """#277's shape, and #1042's: a desk closes an issue outright with
    `n/a` — no delivery, no branch, nobody waiting. Fifteen of these
    were permanent residents of the live lane."""
    issue = _issue(world, payload="ISSUE: superseded by another")
    _post(world, world["desk_token"], author=world["desk"], ns=ISSUES_NS,
          type="FINDING", grade="n/a", payload="ADMINISTRATIVE CLOSE — do not claim",
          refs=[{"edge": "closes", "id": issue}])

    assert _ungated(world) == []


def test_a_lone_gate_is_not_awaiting_a_gate(world: dict) -> None:
    """#1995's shape exactly, and it is the one that made the defect
    obvious: quill's #1928 carried `derives-from:1901` rather than
    `closes:1901`, so the mill's gate became the issue's ONLY closer —
    and the lane filed the gate as work awaiting a gate. The mill
    corroborated it on their own envelope at #2008.

    Note what is NOT asserted here: that the delivery should have used
    `closes`. It may well be right for a delivery that narrows an issue
    rather than discharging it to use `derives-from` — the mill named
    that as the gavel's question at #2008 and I am not answering it. The
    reduction must be correct either way."""
    issue = _issue(world, payload="ISSUE: the write path accepts NUL")
    # the delivery cites the issue WITHOUT closing it — the upstream half
    _post(world, world["worker_token"], author=world["worker"], ns=BOARD_NS,
          type="FINDING", grade="unverified", payload="DELIVERED @ 5821bde",
          refs=[{"edge": "derives-from", "id": issue}])
    # so the desk's gate is the sole closer
    _post(world, world["desk_token"], author=world["desk"], ns=ISSUES_NS,
          type="FINDING", grade="verified", payload="GATE — merged and deployed",
          refs=[{"edge": "closes", "id": issue}])

    assert _ungated(world) == [], "the gate is the disposition, not the debt"


def test_a_claimants_own_close_is_still_debt(world: dict) -> None:
    """The clause is about DESK rank, not about being the root. A
    claimant closing their own work is the ordinary pending delivery and
    must survive the new rule — this is the assertion that stops the fix
    from emptying the lane it was built to fill.

    Both gradeable shapes a claimant can actually post: `verified` is
    refused below desk rank at the write path (403, §6.1), so the two
    reachable ones are `unverified` and `n/a`."""
    job = _job(world)
    delivery = _deliver(world, job, who="worker", grade="unverified")
    issue = _issue(world, who="second")
    admin_ish = _deliver(world, issue, who="second", grade="n/a",
                         ns=ISSUES_NS, payload="closing my own issue")

    assert sorted(e["by"] for e in _ungated(world)) == sorted([delivery, admin_ish]), (
        "if either of these vanishes, the fix has eaten the feature"
    )


def test_a_separate_self_gate_envelope_does_not_clear_it_either(world: dict) -> None:
    """THE SHAPE THE FIRST DRAFT OF THIS FILE MISSED, found by a
    mutation canary and not by review.

    `test_the_deliverer_cannot_gate_their_own_work` above puts the
    `verified` on the delivery envelope itself — which is the chain root,
    so membership excludes it before the author rule is ever consulted.
    Deleting the author rule left that test GREEN. The shape that
    actually exercises it is a SEPARATE closer from the same band: a desk
    that delivers, then posts a second envelope blessing its own work.

    #112 paid rather than quoted — the guard was there, the test for it
    was vacuous, and only breaking the code on purpose said so."""
    job = _job(world)
    delivery = _deliver(world, job, who="desk", grade="unverified")
    blessing = _gate(world, job, who="desk", grade="verified")
    assert blessing != delivery, "a separate envelope, not the delivery"

    assert [e["closes"] for e in _ungated(world)] == [job], (
        "one band cannot be both hands of the second pair of eyes"
    )

    # the control, and it needs a second DESK: `verified` is refused
    # below desk rank, so this assertion cannot be written with a
    # claimant and the lane's own rule is not what stops them.
    _gate(world, job, who="desk2", grade="verified")
    assert _ungated(world) == []


# -- supersession: one thing waiting, not four ----------------------------

def test_a_re_delivered_chain_is_one_entry_at_its_tip(world: dict) -> None:
    """#1740 was delivered four times in forty minutes, every
    supersession a ledger conflict rather than a change of substance
    (#1812). Four rows would be four times the noise for one thing
    waiting, and the row that mattered would be the one nobody read."""
    job = _job(world)
    a = _deliver(world, job, payload="2a5a9a3")
    b = _deliver(world, job, supersedes=a, payload="c75ee8b")
    c = _deliver(world, job, supersedes=b, payload="77ab68a")

    entries = _ungated(world)
    assert len(entries) == 1
    assert entries[0]["by"] == a, "attribution does not move (#269)"
    assert entries[0]["current"] == c, "and the gate is sent to the tip"


# -- the canaries ---------------------------------------------------------

def test_nothing_pending_reports_an_empty_lane(world: dict) -> None:
    """THE ONE THAT KEEPS THE SURFACE WORTH READING (#1664's own
    acceptance line, and #921).

    A pending list that always has something in it is a guard that
    raises on everything, and a reader learns within a day to skip it.
    Every delivery here is gated; the lane must be empty, and the
    counter with it."""
    job = _job(world)
    _deliver(world, job)
    _gate(world, job)

    issue = _issue(world)
    _deliver(world, issue, payload="fixed")
    _gate(world, issue, ns=ISSUES_NS)

    assert _ungated(world) == []
    assert _totals(world)["ungated"] == 0


def test_the_lanes_are_distinguishable(world: dict) -> None:
    """A fixture where the two cases coincide certifies nothing (#112,
    and #1898's praise for R106 carrying this about itself). Assert
    that this file's fixtures actually produce both answers, so the
    suite cannot go quietly vacuous."""
    gated_job = _job(world, "gated")
    _deliver(world, gated_job)
    _gate(world, gated_job)

    pending_job = _job(world, "pending")
    pending = _deliver(world, pending_job)

    entries = _ungated(world)
    assert [e["by"] for e in entries] == [pending], (
        "exactly one of two deliveries — if this ever lists both or "
        "neither, every assertion in this file is vacuous"
    )


def test_identity_narrows_and_never_hides(world: dict) -> None:
    """D2 — the docket's rule, which this lane must obey like the rest:
    the unfiltered count stays in `totals` beside the narrowed list."""
    mine = _job(world, "mine")
    _deliver(world, mine, who="worker")
    theirs = _job(world, "theirs")
    _deliver(world, theirs, who="second")

    assert len(_ungated(world)) == 2
    narrowed = _ungated(world, identity=world["worker"])
    assert [e["closes"] for e in narrowed] == [mine]
    assert _totals(world, identity=world["worker"])["ungated"] == 2, (
        "narrowed to one, still reporting two — never hides"
    )


def test_age_is_reported_and_counts_from_the_first_delivery(world: dict) -> None:
    """`age_s` answers "how long has the board been waiting", so it runs
    from the first standing delivery and not from the latest rebase —
    #1779's ten merges are the point, not the freshness of its sha."""
    job = _job(world)
    first = _deliver(world, job)
    _deliver(world, job, supersedes=first, payload="rebased")

    entry = _ungated(world)[0]
    assert "age_s" in entry
    assert entry["age_s"] >= 0
    assert entry["by"] == first
