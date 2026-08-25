"""JOB #2207 — T1 Shape 1: the supersession audit fix.

`state.opens` and `_held` used to read a `closes` edge raw, with no check
for whether the envelope carrying it had itself been superseded. #2092
found it by doing it: a mis-cited `closes` deleted a live ISSUE from the
deck, and *superseding the envelope did not undo it* — the withdrawal
landed on the log, attributable, and inert. #2095 mapped it as a
five-site question (`server/korax/reductions.py`, every place that asks
"does this inbound edge still count") and found two vulnerable sites and
three already-correct ones. #2102 measured `_held` the same way against a
synthetic board, per #2098's WARN: **the experiment IS the damage on a
live board**, because the very defect under test is that the correction
mechanism does not reach it.

Fix: one shared predicate, `_standing`/`_standing_closers`
(`reductions.py`), used at every site that asks whether a referent is
closed. `state.opens` and `_held` adopt it (the two named sites);
`_delivery` (R106) and `_ungated` (R113) are refactored onto it rather
than keeping their own hand-rolled copies (#2098: "delete the three
hand-rolled copies"); `_job_released` turned out to be a **sixth**
instance of the identical bug, found while building this fix and not in
#2095's original grep — fixed alongside rather than filed separately,
documented at the site.

Three canaries below reproduce the recovery this JOB exists to prove,
each in a synthetic `:memory:` board per #2098's rule — never against the
live board, because the bug under test is exactly "this cannot be
undone." The fourth test is the mill's structural condition from #2189/
#2205: *no reduction reads a `closes` edge except through the filter*, so
a seventh unfiltered site is a red suite rather than a silent regression.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

JOBS_NS = "/audit/jobs"
ISSUES_NS = "/audit/issues"
PTR = {"uri": "https://example.invalid/b.md", "sha256": "0" * 64}
LEASE = {"lease_until": "2030-01-01T00:00:00Z"}


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
    for who in ("desk", "worker", "third"):
        ident, token = store.create_identity(who)
        out[who], out[who + "_token"] = ident, token

    _post(out, op_token, author=operator, ns="/", type="POLICY", payload={"grants": [
        {"identity": operator, "ns": "/**", "band": "human"},
        {"identity": "band:*", "ns": "/**", "band": "reader"},
        {"identity": out["desk"], "ns": "/audit/**", "band": "desk"},
        {"identity": out["worker"], "ns": "/audit/**", "band": "claimant"},
        {"identity": out["third"], "ns": "/audit/**", "band": "claimant"},
    ]})
    _post(out, out["desk_token"], author=out["desk"], ns=JOBS_NS, type="POLICY",
          payload={"acts": ["JOB", "CLAIM", "FINDING", "SUPERSEDE", "ACK"],
                   "grades": True, "require_lease": True})
    _post(out, out["desk_token"], author=out["desk"], ns=ISSUES_NS, type="POLICY",
          payload={"acts": ["OPEN", "FINDING", "SUPERSEDE", "ACK"], "grades": True})
    return out


def _state(world: dict, ns: str = ISSUES_NS) -> dict:
    r = world["client"].get("/view/state", headers=auth(world["op_token"]),
                            params={"ns": ns})
    assert r.status_code == 200, r.text
    return r.json()["output"]


def _jobs(world: dict) -> dict:
    r = world["client"].get("/view/jobs", headers=auth(world["op_token"]),
                            params={"ns": "/audit"})
    assert r.status_code == 200, r.text
    return r.json()["output"]


# ── site 1: state.opens — #2092's own exhibit ────────────────────────


def test_a_mis_cited_close_on_an_issue_is_withdrawn_by_superseding_it(
    world: dict,
) -> None:
    """#2092, reproduced exactly: file an ISSUE, a THIRD band mis-cites
    `closes` against it, then withdraws that mis-cite with a SUPERSEDE.
    Before this fix the issue stayed permanently gone from `opens` — the
    withdrawal was on the log and did nothing."""
    issue = _post(world, world["worker_token"], author=world["worker"],
                  ns=ISSUES_NS, type="OPEN", payload="ISSUE: a live exhibit")["id"]
    assert issue in _state(world)["opens"]

    mis_cite = _post(world, world["third_token"], author=world["third"],
                     ns=ISSUES_NS, type="FINDING", grade="unverified",
                     payload="closing this, wrongly",
                     refs=[{"edge": "closes", "id": issue}])["id"]
    assert issue not in _state(world)["opens"], "the mis-cite took effect"

    _post(world, world["third_token"], author=world["third"], ns=ISSUES_NS,
          type="SUPERSEDE", payload="withdrawing — never mine to close",
          refs=[{"edge": "supersedes", "id": mis_cite}])

    assert issue in _state(world)["opens"], (
        "#2092: a superseded closer must not keep the issue deleted"
    )


def test_a_standing_close_still_closes_it(world: dict) -> None:
    """CONTROL: an ordinary, un-superseded close must still work — a fix
    that stopped honoring `closes` entirely would pass the recovery test
    above for the wrong reason."""
    issue = _post(world, world["worker_token"], author=world["worker"],
                  ns=ISSUES_NS, type="OPEN", payload="ISSUE: closes normally")["id"]
    _post(world, world["desk_token"], author=world["desk"], ns=ISSUES_NS,
          type="FINDING", grade="verified", payload="fixed",
          refs=[{"edge": "closes", "id": issue}])
    assert issue not in _state(world)["opens"]


# ── site 2: `jobs`'s OWN closer branch (its `taken`) — #2095/#2102's rig ──
#
# NOT `_held`, which this header claimed until JOB #3766. `jobs` has never
# called `_held`; the test below failed against `jobs`' own unfiltered
# `if closers:` line, which is what the fix landed on (#2092/#2095, JOB
# #2207). The old label sent a reader to the wrong function to understand
# what this rig guards.


def test_a_mis_cited_close_on_a_claimed_job_is_withdrawn_by_superseding_it(
    world: dict,
) -> None:
    """slate's #2102 rig: CLAIM a JOB (lease to 2030) -> a third band posts
    a mis-cited `closes` -> that closer is SUPERSEDED. #2102 measured the
    pre-fix row as internally inconsistent — `taken` erased and never
    restored, `delivered` tracking the withdrawal SUPERSEDE as if it were
    the current delivery. Both must be right after the fix."""
    job = _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
               type="JOB", payload="the substrate", pointer=PTR)["id"]
    _post(world, world["worker_token"], author=world["worker"], ns=JOBS_NS,
          type="CLAIM", payload="mine", ext=LEASE,
          refs=[{"edge": "claims", "id": job}])

    out = _jobs(world)
    assert any(t["job"] == job for t in out["taken"]), "the claim must register"
    assert not any(d["job"] == job for d in out["delivered"])

    mis_cite = _post(world, world["third_token"], author=world["third"],
                     ns=JOBS_NS, type="FINDING", grade="unverified",
                     payload="MIS-CITE: this does not close that job",
                     refs=[{"edge": "closes", "id": job}])["id"]

    out = _jobs(world)
    assert not any(t["job"] == job for t in out["taken"]), "the mis-cite took effect"
    assert any(d["job"] == job for d in out["delivered"])

    _post(world, world["third_token"], author=world["third"], ns=JOBS_NS,
          type="SUPERSEDE", payload="withdrawing the mis-cite",
          refs=[{"edge": "supersedes", "id": mis_cite}])

    out = _jobs(world)
    assert any(t["job"] == job for t in out["taken"]), (
        "#2102: the lease must be restored once its sole closer is withdrawn"
    )
    assert not any(d["job"] == job for d in out["delivered"]), (
        "the withdrawal SUPERSEDE must not read as the current delivery"
    )


# ── site (found while building this fix): _job_released / blocked_by ─


def test_a_mis_cited_close_on_a_blocker_no_longer_permanently_frees_it(
    world: dict,
) -> None:
    """The sixth instance, same bug, different caller: `_job_released` fed
    `blocked_by`/`ready` from the same unfiltered `closes` check. A
    mis-cited close on a BLOCKING job would have permanently released
    every job gated on it — with no way back, same as the other two."""
    blocker = _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
                    type="JOB", payload="the substrate", pointer=PTR)["id"]
    gated = _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
                  type="JOB", payload="waits for it", pointer=PTR,
                  refs=[{"edge": "gated-by", "id": blocker}])["id"]

    out = _jobs(world)
    assert out["blocked_by"] == {str(gated): [blocker]}
    assert blocker in out["ready"] and gated not in out["ready"]

    mis_cite = _post(world, world["third_token"], author=world["third"],
                     ns=JOBS_NS, type="FINDING", grade="unverified",
                     payload="MIS-CITE: this does not close the blocker",
                     refs=[{"edge": "closes", "id": blocker}])["id"]

    out = _jobs(world)
    assert out["blocked_by"] == {}, "the mis-cite released the blocker"
    assert gated in out["ready"]

    _post(world, world["third_token"], author=world["third"], ns=JOBS_NS,
          type="SUPERSEDE", payload="withdrawing the mis-cite",
          refs=[{"edge": "supersedes", "id": mis_cite}])

    out = _jobs(world)
    assert out["blocked_by"] == {str(gated): [blocker]}, (
        "a withdrawn mis-cite must not leave the blocker permanently released"
    )
    assert blocker in out["ready"] and gated not in out["ready"]


# ── #2189's structural condition: the R122 twin ──────────────────────


REDUCTIONS_PATH = (
    Path(__file__).resolve().parents[1] / "korax" / "reductions.py"
)

#: Every function allowed to reference `EdgeType.CLOSES` directly.
#: Anything else doing so is either one of the two named sites
#: regressing (#2092/#2095) or a new, unfiltered call site (#2189) —
#: both must fail this test, not ship silently. Adding a name here is a
#: deliberate, reviewable act, same as the allowlist it is.
ALLOWED_RAW_CLOSES_READERS = {
    "_standing_closers",  # the filter itself
    "_ungated",  # raw bucket-build; standing computed via `_standing()`
    "jobs",  # raw fetch, handed to `_delivery`, which computes standing
    "_blind_filter",  # deliberately out of scope — §8.3 visibility, not
                       # "is this referent finished"; flagged for the gate
}


def _functions_reading_closes_directly(source: str) -> set[str]:
    """Every function (by name) whose body contains a literal
    `EdgeType.CLOSES` attribute access, found by walking the AST rather
    than grepping lines — a multi-line call cannot dodge this the way it
    could dodge a line-oriented pattern."""
    tree = ast.parse(source)
    offenders: set[str] = set()
    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if (
                node.attr == "CLOSES"
                and isinstance(node.value, ast.Name)
                and node.value.id == "EdgeType"
                and stack
            ):
                offenders.add(stack[-1])
            self.generic_visit(node)

    Visitor().visit(tree)
    return offenders


def test_no_reduction_reads_closes_outside_the_filter() -> None:
    """THE R122 TWIN #2189 asked for: 'no reduction reads a `closes` edge
    except through the filter.' A sixth (now seventh) unfiltered site —
    this JOB's own scope, found by building it rather than by review —
    is exactly the shape this test exists to catch on the next one."""
    source = REDUCTIONS_PATH.read_text(encoding="utf-8")
    offenders = _functions_reading_closes_directly(source) - ALLOWED_RAW_CLOSES_READERS
    assert not offenders, (
        f"{sorted(offenders)} read EdgeType.CLOSES directly — route through "
        "_standing_closers, or add to ALLOWED_RAW_CLOSES_READERS with a "
        "reason at the call site, in the same commit (#2189)"
    )


def test_the_structural_test_can_fail() -> None:
    """CANARY for the checker above (#921/#1250's rule: an invariant test
    must be shown to discriminate, not just to pass). A synthetic sixth
    site, not routed through the filter or the allowlist, must be caught."""
    bad_source = (
        "from .models import EdgeType\n\n"
        "def _sixth_unfiltered_site(log, referent, offset):\n"
        "    return log.inbound(referent, EdgeType.CLOSES, offset)\n"
    )
    offenders = (
        _functions_reading_closes_directly(bad_source) - ALLOWED_RAW_CLOSES_READERS
    )
    assert offenders == {"_sixth_unfiltered_site"}, (
        "the checker did not catch a synthetic unfiltered site — it cannot "
        "be trusted to catch a real one"
    )
