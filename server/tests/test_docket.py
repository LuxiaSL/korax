"""§10.12 — the docket, and the two guards that outlive it.

JOB #714, design #756 endorsed at #769. The reduction itself is
composition and its tests are ordinary. Two of the cases below are not
ordinary, and they are why this file exists:

  test_the_counter_covers_the_inbox_section
      D3. The docket is the SECOND reduction whose served slice is not
      one namespace, and `/view`'s `scoped()` derives its slice from the
      query arguments. `in_subtree("/proj", "/korax/inbox")` is False, so
      without a declared slice the counter reports ZERO for a section it
      withheld from. Under-reporting is worse than #468's
      over-reporting: a page that says zero-withheld re-arms a reader's
      belief that zero means complete, which is the false-completeness
      class R28 was built to remove. Delete the `Scope.union(docket_namespaces(ns))` declaration in
      api.py and this test is the one that reddens. (It was a `served_ns`
      branch inside `scoped()` until #667 collapsed every counter onto
      one emission point; the declaration survived, its private branch
      did not.)

  test_a_withheld_open_is_counted_and_never_excerpted
      D4. `search.py:79` asserts in a DOCSTRING that an excerpt is
      "drawn only from an envelope the requester may read… must never be
      built for a withheld envelope." Nothing asserted it. #662,
      quoting slate's #639, predicted the surface that would break it:
      "a later excerpt built for a withheld envelope to make counts more
      useful would pass every guard now standing." `filed`'s first_line
      IS that later excerpt. #111 is canon: a documented invariant with
      nothing asserting it is not an invariant. This is the assertion.

The D1 cases are measurement made executable. `escalated` is scoped by
author-holds-grant-in-project OR edge-into-project, and the union exists
because edges alone are structurally blind to grant requests — they
carry no refs, because at the moment a band files one there is nothing
in the project to point at, and `charter.md:26` requires one per
parallel session forever. Measured over this board's 27 inbox OPENs:
edges 11, grants 18, union 21.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

PROJECT = "/proj"
JOBS_NS = "/proj/jobs"
ISSUES_NS = "/proj/issues"
INBOX = "/korax/inbox"
LEASE = {"lease_until": "2030-01-01T00:00:00Z"}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _post(world: dict, token: str, **body: object) -> dict:
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "grade": "n/a", "refs": [], "ext": {}, **body,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _docket(world: dict, token: str, **params: object) -> dict:
    r = world["client"].get("/view/docket", headers=auth(token), params=params)
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
    for who in ("desk", "worker", "outsider", "toolsmith"):
        ident, token = store.create_identity(who)
        out[who] = ident
        out[who + "_token"] = token
    return out


@pytest.fixture()
def program(world: dict) -> dict:
    """A project with work in every state, plus an inbox carrying one
    escalation of each routing shape."""
    _post(world, world["op_token"], author=world["operator"], ns="/",
          type="POLICY", payload={"grants": [
              {"identity": world["operator"], "ns": "/**", "band": "human"},
              # the floor every identity holds — its root is "/", so it
              # must make NOBODY a project band
              {"identity": "band:*", "ns": "/**", "band": "reader"},
              {"identity": world["desk"], "ns": "/proj/**", "band": "desk"},
              {"identity": world["worker"], "ns": "/proj/**", "band": "claimant"},
              {"identity": world["outsider"], "ns": "/other/**", "band": "claimant"},
              # the prefix trap: "/proj-tools/**".startswith("/proj") is
              # True and in_subtree("/proj", "/proj-tools") is False
              {"identity": world["toolsmith"], "ns": "/proj-tools/**",
               "band": "claimant"},
          ]})
    _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
          type="POLICY", payload={
              "acts": ["JOB", "CLAIM", "FINDING", "SUPERSEDE", "ACK"],
              "grades": True, "require_lease": True, "job_posters": "desk"})
    _post(world, world["desk_token"], author=world["desk"], ns=ISSUES_NS,
          type="POLICY", payload={
              "acts": ["OPEN", "FINDING", "WARN", "SUPERSEDE", "ACK", "NOTE"],
              "grades": True})

    ptr = {"uri": "https://example.invalid/b.md", "sha256": "0" * 64}
    open_job = _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
                     type="JOB", payload="open job", pointer=ptr)
    taken_job = _post(world, world["desk_token"], author=world["desk"], ns=JOBS_NS,
                      type="JOB", payload="taken job", pointer=ptr)
    _post(world, world["worker_token"], author=world["worker"], ns=JOBS_NS,
          type="CLAIM", payload="taking it",
          refs=[{"edge": "claims", "id": taken_job["id"]}], ext=LEASE)

    filed = _post(world, world["worker_token"], author=world["worker"],
                  ns=ISSUES_NS, type="OPEN",
                  payload="ISSUE: the first line is what a scanner reads.\nrest")
    closed = _post(world, world["worker_token"], author=world["worker"],
                   ns=ISSUES_NS, type="OPEN", payload="already handled")
    _post(world, world["worker_token"], author=world["worker"], ns=ISSUES_NS,
          type="FINDING", payload="fixed",
          refs=[{"edge": "closes", "id": closed["id"]}])

    # ── the inbox, one OPEN per routing shape ────────────────────────
    # A: a project band, NO refs at all — the grant-request shape, and
    # the whole reason D1 is a union rather than the brief's edges.
    grant_request = _post(world, world["worker_token"], author=world["worker"],
                          ns=INBOX, type="OPEN",
                          payload="grant request: worker seeks claimant on /proj/**")
    # B: NOT a project band, but carries an edge into the project.
    by_edge = _post(world, world["outsider_token"], author=world["outsider"],
                    ns=INBOX, type="OPEN", payload="ruling requested on a /proj issue",
                    refs=[{"edge": "derives-from", "id": filed["id"]}])
    # neither: a stranger's unrelated escalation.
    unrelated = _post(world, world["outsider_token"], author=world["outsider"],
                      ns=INBOX, type="OPEN", payload="about /other, not this project")
    # the toolsmith's prefix trap, no refs — must NOT route to /proj
    toolsmith = _post(world, world["toolsmith_token"], author=world["toolsmith"],
                      ns=INBOX, type="OPEN", payload="grant request: /proj-tools/**")

    world.update(open_job=open_job["id"], taken_job=taken_job["id"],
                 filed=filed["id"], closed=closed["id"],
                 grant_request=grant_request["id"], by_edge=by_edge["id"],
                 unrelated=unrelated["id"], toolsmith_open=toolsmith["id"])
    return world


def test_all_three_sections_render(program: dict) -> None:
    body = _docket(program, program["desk_token"], ns=PROJECT)
    assert body["view"] == "docket"
    out = body["output"]

    assert out["work"]["open"] == [program["open_job"]]
    assert [t["job"] for t in out["work"]["taken"]] == [program["taken_job"]]
    assert out["work"]["taken"][0]["holder"] == program["worker"]

    assert [f["id"] for f in out["filed"]] == [program["filed"]]
    assert out["filed"][0]["first_line"] == (
        "ISSUE: the first line is what a scanner reads."
    ), "first_line is the opening NON-EMPTY line, not payload[:n]"
    assert program["closed"] not in [f["id"] for f in out["filed"]], (
        "a closed OPEN is not filed — and `state` is what decided that, "
        "not a second implementation living here"
    )

    assert out["namespaces"] == [PROJECT, INBOX]
    assert out["issues_ns"] == ISSUES_NS


def test_the_grant_request_shape_routes_though_it_carries_no_edge(program: dict) -> None:
    """D1's core. This envelope has NO refs — there is nothing in the
    project to point at when you are asking to be let into it — so the
    brief's recommended edge-scoping is structurally blind to it. It is
    also the most time-critical thing an inbox holds: a band parked on
    the visitor floor with nobody looking."""
    out = _docket(program, program["desk_token"], ns=PROJECT)["output"]
    ids = [e["id"] for e in out["escalated"]]
    assert program["grant_request"] in ids, (
        "edge-scoping alone misses every grant request this board has "
        "ever received (#756's measurement: edges 11/27, union 21/27)"
    )
    assert program["by_edge"] in ids, "the edge half of the union still routes"


def test_neither_the_floor_grant_nor_a_prefix_neighbour_is_a_project_band(
    program: dict,
) -> None:
    """The two traps `project_bands` steps over.

    Every identity holds `reader:/**`, whose root is `/`; if that made
    them a project band, `escalated` would be the whole inbox. And
    `"/proj-tools/**".startswith("/proj")` is True while
    `in_subtree("/proj", "/proj-tools")` is False — measuring this with
    string prefixes reported 26/27 inbox OPENs as `/korax` escalations
    where the true figure is 14/27 (#783)."""
    out = _docket(program, program["desk_token"], ns=PROJECT)["output"]
    ids = [e["id"] for e in out["escalated"]]
    assert program["unrelated"] not in ids, (
        "the /** reader floor must not make every band a project band"
    )
    assert program["toolsmith_open"] not in ids, (
        "/proj-tools is not inside /proj; a prefix test would say it is"
    )


def test_an_empty_project_renders_four_empty_sections(program: dict) -> None:
    """Not hypothetical: this board's own `escalated` is empty right now
    (#719 — the operator queue is drained), so the empty case is the
    live one and an error here would be a session-opening error.

    `ungated` joined them at JOB #1970 and is held to the same rule —
    and for that lane the empty case is not merely the live one, it is
    the whole point: a pending list that always has something in it is
    #921's guard that raises on everything, and #1664's own acceptance
    line asked for this assertion by name. (No revision number here on
    purpose: the ledger allocates it at the merge, and a number written
    while three deliveries are in flight is a number that collides —
    #822/#1812, twice tonight already.)"""
    out = _docket(program, program["desk_token"], ns="/nothing-here")["output"]
    assert out["work"]["open"] == []
    assert out["work"]["taken"] == []
    assert out["filed"] == []
    assert out["escalated"] == []
    assert out["ungated"] == []
    assert out["totals"] == {
        "open": 0, "taken": 0, "filed": 0, "escalated": 0, "ungated": 0,
    }


def test_the_identity_filter_narrows_without_hiding(program: dict) -> None:
    """D2. Two reductions answering one question is X2 — `state` and
    `jobs` disagreed in production, five live claims against two. So one
    reduction with a filter, and the filter is only honest if the number
    you were narrowed away from is still on the page."""
    whole = _docket(program, program["desk_token"], ns=PROJECT)["output"]
    mine = _docket(program, program["desk_token"], ns=PROJECT,
                   identity=program["worker"])["output"]

    assert [t["job"] for t in mine["work"]["taken"]] == [program["taken_job"]]
    assert [f["id"] for f in mine["filed"]] == [program["filed"]]
    assert [e["id"] for e in mine["escalated"]] == [program["grant_request"]]

    assert mine["totals"] == whole["totals"], (
        "narrowing must not move the totals — a band that cannot see what "
        "it was narrowed away from will mistake its slice for the program"
    )
    assert mine["totals"]["escalated"] == 2

    outsider = _docket(program, program["desk_token"], ns=PROJECT,
                       identity=program["outsider"])["output"]
    assert [e["id"] for e in outsider["escalated"]] == [program["by_edge"]]
    assert outsider["work"]["taken"] == []


def test_open_jobs_are_not_narrowed_away(program: dict) -> None:
    """`identity` narrows what is HELD and what is AUTHORED. An open job
    belongs to nobody, so narrowing it would hide the only section a
    returning band is looking for work in."""
    mine = _docket(program, program["desk_token"], ns=PROJECT,
                   identity=program["worker"])["output"]
    assert mine["work"]["open"] == [program["open_job"]]


# ── the two that outlive the docket ──────────────────────────────────


@pytest.fixture()
def sealed_program(program: dict) -> dict:
    """Seal the project's issues nest from the human band, so a human
    requester has real withholding inside the docket's slice.

    The INBOX is deliberately not sealed here — it cannot be. See
    `test_the_escalated_nest_cannot_be_sealed_today`."""
    _post(program, program["op_token"], author=program["operator"],
          ns=ISSUES_NS, type="POLICY",
          payload={"visibility": {"human_read": "sealed"}})
    return program


def test_the_escalated_nest_cannot_be_sealed_today(program: dict) -> None:
    """WHY THE D3 COUNTER DEFECT IS CURRENTLY UNREACHABLE, ASSERTED
    RATHER THAN ASSUMED — and this is the canary if that ever changes.

    #756 argued, and #769 endorsed, that a docket counting only
    `in_subtree(ns, …)` reports ZERO for envelopes withheld from
    `/korax/inbox`. The arithmetic is right: `in_subtree("/proj",
    "/korax/inbox")` is False. What neither the proposal nor the
    endorsement checked is whether anything can EVER be withheld there:

      * `sealed` — refused outright. `validate.py:517-520`, §1.1.9/§8.7.4:
        a POLICY setting `human_read: sealed` anywhere under `/korax/` is
        a 403, asserted below.
      * `participation` — `access.py`'s `verdict` returns it only for
        `/scratch/…` and `/dm/…` prefixes. `/korax/inbox` is neither.
      * `denied` — never counted at all (#268 D2), by design.

    So the escalated section's counter is correct TODAY BY ACCIDENT of a
    rule written for a different reason, not by construction. The
    declared slice makes it correct by construction, which is the whole
    of why it still ships — and this test is what reddens if §1.1.9 is
    ever relaxed, pointing whoever relaxes it at the docket.

    #112: break the guard on purpose and watch it fail. This is the
    inverse — pin the rule the guard is currently redundant with, so the
    redundancy is a recorded decision rather than a coincidence nobody
    rechecks."""
    r = program["client"].post("/post", headers=auth(program["op_token"]), json={
        "proto": PROTO, "author": program["operator"], "ns": INBOX,
        "type": "POLICY", "grade": "n/a", "refs": [], "ext": {},
        "payload": {"visibility": {"human_read": "sealed"}},
    })
    assert r.status_code == 403, (
        "if this now succeeds, the docket's escalated counter has become "
        "reachable and the docket's `Scope.union` declaration in api.py is "
        "load-bearing rather than defensive — see test_the_declared_slice_is_what_the_counter_uses"
    )
    assert "cannot be sealed" in r.json()["message"]


def test_the_declared_slice_is_what_the_counter_uses(
    program: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE MECHANISM, exercised directly, because the end-to-end path is
    unreachable for the reason above.

    Point the escalated section at a nest that CAN be sealed and is
    outside the project, and the counter must include its withholding.
    Without the `Scope.union(docket_namespaces(ns))` declaration in api.py
    this returns the project's count alone and the assertion fails.

    Monkeypatching is honest here rather than convenient: `INBOX_NS` is a
    constant today, and per-nest inboxes are already contemplated in
    `seed.py` ("a per-user inbox sets its own closers"). The day the
    escalated nest becomes configurable, this is the case that was
    already covered."""
    from korax import api as api_module

    outside = "/elsewhere"
    _post(program, program["op_token"], author=program["operator"], ns=outside,
          type="POLICY", payload={
              "acts": ["OPEN", "NOTE", "POLICY"], "grades": True,
              "grants": [{"identity": "band:*", "band": "poster"}],
              "visibility": {"human_read": "sealed"}})
    for i in range(3):
        _post(program, program["worker_token"], author=program["worker"],
              ns=outside, type="OPEN", payload=f"withheld escalation {i}")

    baseline = _docket(program, program["op_token"], ns=PROJECT)
    assert baseline["sealed_excluded"] == 0, (
        "nothing inside /proj is sealed yet, and /elsewhere is not served"
    )

    monkeypatch.setattr(
        api_module, "docket_namespaces", lambda project: [project, outside]
    )
    widened = _docket(program, program["op_token"], ns=PROJECT)
    assert widened["sealed_excluded"] == 3, (
        f"the counter reported {widened['sealed_excluded']} for a slice "
        f"that served a nest withholding 3 — a page withholding while "
        f"reporting a number structurally unable to include it"
    )


def test_the_counter_still_names_the_slice_and_not_the_board(
    sealed_program: dict,
) -> None:
    """The other half of #468: a declared slice must not become an excuse
    to report the board. Envelopes withheld OUTSIDE every served
    namespace stay out of this count."""
    _post(sealed_program, sealed_program["op_token"],
          author=sealed_program["operator"], ns="/elsewhere", type="POLICY",
          payload={"acts": ["NOTE", "POLICY"], "grades": True,
                   "grants": [{"identity": "band:*", "band": "poster"}],
                   "visibility": {"human_read": "sealed"}})
    before = _docket(sealed_program, sealed_program["op_token"],
                     ns=PROJECT)["sealed_excluded"]
    for i in range(3):
        _post(sealed_program, sealed_program["worker_token"],
              author=sealed_program["worker"], ns="/elsewhere", type="NOTE",
              payload=f"not in any docket slice {i}")

    after = _docket(sealed_program, sealed_program["op_token"], ns=PROJECT)
    assert after["sealed_excluded"] == before, (
        "the docket's count absorbed a nest it never served"
    )
    assert "/elsewhere" not in after["output"]["namespaces"]


def test_a_withheld_open_is_counted_and_never_excerpted(
    sealed_program: dict,
) -> None:
    """D4 — the guard `search.py:79` describes in prose and nothing
    asserted, on the first surface built to break it (#662/#639).

    A withheld OPEN must contribute to the exclusion count and yield
    NOTHING: no id, no author, no first line. The payload's own words are
    searched for across the whole rendered document, because the failure
    mode is not "the excerpt field is populated" — it is "the text got
    out by any route at all"."""
    secret = "SEALED-CANARY-a7f3 the operator alone may read this"
    withheld = _post(sealed_program, sealed_program["worker_token"],
                     author=sealed_program["worker"], ns=ISSUES_NS,
                     type="OPEN", payload=secret)
    # THE WITHHELD ENVELOPE MUST NOT BE THE NEWEST ONE, and this line is
    # load-bearing rather than tidy. `/view` derives its offset from the
    # VISIBLE log's last id (api.py), so a sealed envelope that happens to
    # be newest sits past the offset and is excluded by arithmetic no
    # matter what the reduction does with it. Without this follow-up post
    # the test passes even when `docket` is handed the unfiltered log —
    # measured, not reasoned: mutation M2 stayed green until this landed.
    _post(sealed_program, sealed_program["desk_token"],
          author=sealed_program["desk"], ns=JOBS_NS, type="FINDING",
          payload="a later, readable envelope so the seal is not the head")

    body = _docket(sealed_program, sealed_program["op_token"], ns=PROJECT)
    out = body["output"]
    ids = [f["id"] for f in out["filed"]]

    assert withheld["id"] not in ids, (
        "a sealed OPEN reached the rendered section"
    )
    # The positive control rides in the same assertion (#10): the earlier
    # OPEN predates the sealing POLICY and stays visible, because §8.7
    # fixes an envelope's audience at ITS OWN post offset
    # (access.py — "audience fixed at post offset"). So this test cannot
    # pass by rendering nothing at all.
    assert sealed_program["filed"] in ids, (
        "if the whole section is empty the canary below proves nothing"
    )
    assert body["sealed_excluded"] > 0, (
        "withheld and uncounted is the false-completeness R28 removed"
    )

    import json as _json
    rendered = _json.dumps(body)
    assert "SEALED-CANARY-a7f3" not in rendered, (
        "an excerpt was built for a withheld envelope — the exact thing "
        "search.py's docstring forbids and nothing asserted"
    )


def test_the_excerpt_is_present_when_the_envelope_is_readable(
    program: dict,
) -> None:
    """The canary for the canary (#10): the previous test passes trivially
    if `first_line` is never populated for anyone. It is."""
    out = _docket(program, program["desk_token"], ns=PROJECT)["output"]
    assert out["filed"][0]["first_line"], (
        "if this is empty, the withheld-excerpt test above proves nothing"
    )
