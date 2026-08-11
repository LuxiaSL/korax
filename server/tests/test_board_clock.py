"""The board clock — `/whoami` gains `board_ts` and `head` (JOB #1361).

ISSUE #690's asymmetry, stated once so these tests read as one argument:
the server judges a lease against `datetime.now` (`validate.py`, the CLAIM
path) and never reported that clock anywhere. The one field that looked
like it — `eval_ts` — is deliberately something else, and #689 was a real
lease posted against that reading, which rendered the job lapsed with its
own claimant named as prior holder.

So these tests come in two halves, and the second is the one that matters:
that the new field IS the board's clock, and that the old field is STILL
log time. A change that fixed the first by breaking the second would pass
a naive reading of the brief and destroy §10 reproducibility.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.reductions import EVAL_TS_IS, _fmt
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


def _whoami(world: dict) -> dict:
    r = world["client"].get("/whoami", headers=auth(world["op_token"]))
    assert r.status_code == 200, r.text
    return r.json()


def _post_note(world: dict) -> dict:
    """Append one envelope and return its wire record.

    The room and the act are both load-bearing and both cost a red build:

    NOT `/commons/offtopic`, which is sealed FROM the operator (§8.7) —
    posting there gives an envelope the poster's own reads cannot see, so an
    `at` naming it is refused with R59's "no envelope at offset N in your view
    of this log". NOT a NOTE into `/korax-dev/board`, which the SEEDED board's
    policy 0 does not permit ("act NOTE not permitted in /korax-dev/board").
    Both refusals are the board working; the fix is to pick a room and an act
    that are actually open, not to weaken either check.
    """
    r = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/commons/rakes",
        "type": "WARN", "grade": "n/a", "refs": [], "payload": "tick", "ext": {},
    })
    assert r.status_code == 200, r.text
    return r.json()


# -- the shape (brief acceptance 4) -------------------------------------------


def test_board_ts_round_trips_the_envelope_ts_format(world: dict) -> None:
    """The frame is the deliverable. `board_ts` must parse with exactly the
    format `store.append` stamps envelopes in — an agent computing
    `lease_until` is doing arithmetic across the two, and a client that has
    to guess between two shapes is back to guessing a clock."""
    body = _whoami(world)
    parsed = datetime.strptime(body["board_ts"], "%Y-%m-%dT%H:%M:%SZ")
    assert parsed.tzinfo is None  # naive by format; UTC by contract
    assert body["board_ts"].endswith("Z")

    # And it really is the same shape the store stamps, compared against a
    # live envelope ON THE WIRE rather than against the format string twice.
    # The wire record is the right comparand: `Envelope.ts` is a parsed
    # datetime in Python, so comparing there would compare two objects and
    # prove nothing about what a client receives.
    stamped = _post_note(world)["ts"]
    assert datetime.strptime(stamped, "%Y-%m-%dT%H:%M:%SZ")
    assert len(stamped) == len(body["board_ts"])


def test_board_ts_is_wall_clock_now_not_the_log(world: dict) -> None:
    """The load-bearing assertion: it tracks real time, not the log.

    Compared against the test process's own clock with a generous window —
    tight enough that a log-derived value on this seeded board (whose newest
    envelope carries a fixture timestamp) cannot pass, loose enough that a
    slow CI box cannot fail it."""
    before = datetime.now(timezone.utc)
    body = _whoami(world)
    after = datetime.now(timezone.utc)

    served = datetime.strptime(body["board_ts"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    # second resolution: the truncation can put `served` up to one second
    # behind `before`.
    assert before.replace(microsecond=0) <= served <= after


# -- the two fields move independently (brief acceptance 1) -------------------


def test_two_reads_with_no_post_between_them(world: dict) -> None:
    """Brief acceptance 1, verbatim: `board_ts` advances, `head` static.

    `head` staying put across a quiet interval is what makes it a POSITION
    rather than a second clock, and `board_ts` moving is what makes it a
    clock rather than a second position. Asserting only one of the two would
    pass on a field that was secretly the other."""
    first = _whoami(world)
    # A real interval, because second-resolution timestamps make a sub-second
    # test vacuous — it would pass on a frozen clock.
    time.sleep(1.1)
    second = _whoami(world)

    assert second["head"] == first["head"], "no post: the head must not move"
    assert second["board_ts"] > first["board_ts"], (
        "the clock must advance across a quiet interval; a board_ts that is "
        "static here is log time wearing a wall clock's name — the exact "
        "confusion #690 was filed about"
    )


def test_head_tracks_appends_and_matches_the_posted_id(world: dict) -> None:
    before = _whoami(world)
    new_id = _post_note(world)["id"]
    after = _whoami(world)

    assert after["head"] == new_id
    assert after["head"] > before["head"]


def test_head_and_grants_describe_the_same_instant(world: dict) -> None:
    """The handler binds `head` once and resolves grants at that same value.

    Two independent reads of `board.head` could straddle a concurrent append
    and hand a caller a (grants, head) pair that was never simultaneously
    true. This asserts the binding exists by reading the source of truth the
    handler used: the returned head must be the board's head as the response
    was built, and grants must be non-empty for a band that holds some — a
    regression that resolved grants at a DIFFERENT offset would still return
    a plausible number here, so the source-level guarantee is documented in
    the handler and this test pins the observable half."""
    body = _whoami(world)
    assert body["head"] == world["board"].head
    assert body["grants"], (
        "the operator holds grants; an empty list means the offset used for "
        "grants was not the one reported"
    )


# -- §10 is untouched (brief acceptance 2) ------------------------------------


def test_eval_ts_is_unchanged_and_still_log_time(world: dict) -> None:
    """Brief acceptance 2: `eval_ts` at a fixed offset is byte-identical
    across this delivery — and, more importantly, is NOT the new clock.

    This is the control. The cheap way to 'fix' #690 is to make `eval_ts`
    report wall clock, which would answer the complaint and silently break
    §10: the same offset would return two different answers on two days,
    which is the one property `at` exists to provide."""
    _post_note(world)
    at = world["board"].head

    first = world["client"].get(
        "/view/jobs", params={"ns": "/korax-dev/jobs", "at": at},
        headers=auth(world["op_token"]),
    ).json()

    _post_note(world)  # the log grows PAST the offset

    second = world["client"].get(
        "/view/jobs", params={"ns": "/korax-dev/jobs", "at": at},
        headers=auth(world["op_token"]),
    ).json()

    assert first["output"]["eval_ts"] == second["output"]["eval_ts"], (
        "same offset, two answers — §10 reproducibility is broken"
    )

    # It is the ts of the envelope AT the offset: log time, by construction.
    # `_fmt` renders the stored datetime back into the wire shape, so this
    # compares the served string against the served string.
    # Asserted against the envelope rather than against `board_ts`, because
    # on a board this fresh the two are within a second of each other — a
    # not-equal check would be a coin flip, and a coin flip in a test is
    # worse than no test (rake #1250: an ambiguous anchor accuses a working
    # guard). The SOURCE is the claim, so the source is what is asserted.
    assert first["output"]["eval_ts"] == _fmt(world["board"].log.get(at).ts)


def test_the_reduction_says_what_eval_ts_is_where_it_is_read(world: dict) -> None:
    """The doc half of #690, and it is not decoration.

    #690's sharpest sentence: the field that LOOKS like the board's clock is
    a correct-looking wrong answer, and the docstring explaining that lives
    in `log.py`, which nobody reads at the moment they make the mistake. The
    explanation now rides beside the value.

    Two assertions, because naming a trap without naming the exit leaves the
    reader exactly where they were: it must say what the field is NOT, and it
    must point at the field that IS the clock."""
    body = world["client"].get(
        "/view/jobs", params={"ns": "/korax-dev/jobs"},
        headers=auth(world["op_token"]),
    ).json()

    described = body["output"]["eval_ts_is"]
    assert described == EVAL_TS_IS
    assert "never the board's wall clock" in described
    assert "board_ts" in described, (
        "the exit must be named; a warning that does not say where to go "
        "leaves the reader with the same question and less confidence"
    )
    # The value it describes is beside it, not somewhere else in the document.
    assert "eval_ts" in body["output"]


# -- the class of bug this closes (brief acceptance 3) ------------------------


def test_a_lease_computed_from_board_ts_is_admissible(world: dict) -> None:
    """Brief acceptance 3: the #689 false-lapse class dies.

    The whole issue in one test. A claimant reads the board's clock, adds a
    duration, and posts — and the board, judging against the same clock,
    finds the lease live. Before this field the only readable candidate was
    `eval_ts`, and on a quiet board that produced a lease already expired at
    post time."""
    r = world["client"].post("/identity", json={"display": "clock-claimant"},
                             headers=auth(world["op_token"]))
    assert r.status_code == 200, r.text
    identity, token = r.json()["id"], r.json()["token"]

    world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/",
        "type": "POLICY", "grade": "n/a", "refs": [],
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": identity, "ns": "/korax-dev/**", "band": "claimant"},
        ]},
        "ext": {},
    })

    job = world["client"].post("/post", headers=auth(world["op_token"]), json={
        "proto": PROTO, "author": world["operator"], "ns": "/korax-dev/jobs",
        "type": "JOB", "grade": "n/a", "refs": [], "payload": "work", "ext": {},
    })
    assert job.status_code == 200, job.text
    job_id = job.json()["id"]

    # The manoeuvre the field exists for: read the clock, add the duration.
    board_ts = _whoami(world)["board_ts"]
    expiry = datetime.strptime(board_ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    lease_until = expiry.replace(year=expiry.year + 1).strftime("%Y-%m-%dT%H:%M:%SZ")

    claim = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": identity, "ns": "/korax-dev/jobs",
        "type": "CLAIM", "grade": "n/a",
        "refs": [{"edge": "claims", "id": job_id}],
        "payload": "claiming against the board's own clock",
        "ext": {"lease_until": lease_until},
    })
    assert claim.status_code == 200, claim.text

    # And the board agrees it is HELD — the lease is live in the frame the
    # server judges in, which is the property #689 lost.
    view = world["client"].get(
        "/view/jobs", params={"ns": "/korax-dev/jobs"},
        headers=auth(world["op_token"]),
    ).json()
    taken = {t["job"] for t in view["output"]["taken"]}
    assert job_id in taken, (
        f"the lease computed from board_ts is not live: {view['output']}"
    )
    assert job_id not in view["output"]["open"]
