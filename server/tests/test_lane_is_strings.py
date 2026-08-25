"""`<lane>_is` strings — every reduction names what each lane cannot show.

JOB #3774 (v2 R1c), brief `briefs/lane-is-strings.md @ e6c6e70`. Family C
of the lineage audit (#2183); `eval_ts_is` (R114) is the precedent and was,
before this delivery, the only instance on the board.

WHY THE DENOMINATOR IS DERIVED AND NOT LISTED. The whole failure this JOB
closes is an instrument that did not say what it could not see — so a
coverage test that carries its own hand-written list of views would be the
same defect one level up: it would go green on the views it happened to
know about and silently skip the one nobody added to it. That is not
hypothetical here. The shared `ALL_VIEWS` registry in
`test_read_path_refuses` holds 12 entries against a board serving 13
(`mail` is absent), so every sweep built on it — including the `eval_ts_is`
sweep this test generalises — has been passing over one view since `mail`
shipped. This test therefore reads `korax.api.VIEWS`, the list the board
actually serves from, and reddens if its own parameter table does not
cover it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax.api import VIEWS, create_app
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
    return {"board": board, "client": client,
            "operator": operator, "op_token": op_token}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# One call's worth of arguments per served view. NOT a view registry — the
# registry is `korax.api.VIEWS`; this only says how to reach each one, and
# `test_the_parameter_table_covers_every_served_view` is what keeps the two
# in step when a view is added.
PARAMS: dict[str, dict] = {
    "state": {"ns": "/korax-dev"},
    "thread": {"id": "1"},
    "provenance": {"id": "1"},
    "descendants": {"id": "1"},
    "taint": {"id": "1"},
    "fresh": {"ns_set": "/korax-dev/**"},
    "jobs": {"ns": "/korax-dev"},
    "of-record": {"project": "/korax-dev"},
    "onboard": {},
    "required": {"id": "1"},
    "docket": {"ns": "/korax-dev"},
    "browse": {"ns": "/korax-dev"},
    "mail": {},
}


def _fetch(world: dict, name: str) -> dict:
    r = world["client"].get(f"/view/{name}", params=PARAMS[name],
                            headers=auth(world["op_token"]))
    assert r.status_code == 200, f"view `{name}`: {r.status_code} {r.text[:200]}"
    return r.json()


def _lanes(body: dict) -> list[str]:
    """The names this response must account for.

    A dict output accounts for each of its own top-level keys; a list
    output is one unnamed lane and accounts for itself as `output`. `_is`
    strings are not lanes — a twin needs no twin, and without this clause
    the rule has no fixed point.
    """
    out = body["output"]
    if isinstance(out, dict):
        return [k for k in out if not k.endswith("_is")]
    return ["output"]


def _twin_holder(body: dict) -> dict:
    """Where the twin for a lane must sit: beside the data it describes."""
    return body["output"] if isinstance(body["output"], dict) else body


# -- acceptance 1: the sweep, red at head ------------------------------------


def test_every_lane_of_every_served_view_says_what_it_is(world: dict) -> None:
    """Brief property 1 + acceptance 1, as ONE structural sweep.

    Attached to the class, not the case (#993/#1009, and the #1417 lesson
    the `eval_ts_is` sweep was rebuilt around): every view the board serves
    is called, every top-level lane of its output is enumerated from the
    response itself, and each must carry an `<name>_is` twin beside it.
    A section added later without its string reddens here, at the commit
    that adds it.
    """
    missing: list[str] = []
    checked = 0
    for name in VIEWS:
        body = _fetch(world, name)
        holder = _twin_holder(body)
        for lane in _lanes(body):
            checked += 1
            twin = holder.get(f"{lane}_is")
            if not isinstance(twin, str) or not twin.strip():
                missing.append(f"{name}.{lane}")

    assert not missing, (
        f"{len(missing)} of {checked} lanes serve data with no `_is` twin "
        f"beside them:\n  " + "\n  ".join(missing)
    )


def test_the_parameter_table_covers_every_served_view(world: dict) -> None:
    """The denominator guard, and the reason this file does not import
    `ALL_VIEWS`.

    A sweep is only as wide as its input list, and a list maintained by
    hand beside a list maintained by the server drifts silently and in the
    flattering direction — the sweep keeps passing. `mail` is the live
    instance: it has been served and unswept since it shipped. Here the
    served list is the denominator and the parameter table is what must
    keep up, so the next view added reddens this before it can be missed.
    """
    served, reachable = set(VIEWS), set(PARAMS)
    assert served == reachable, (
        f"served but unreachable by this sweep: {sorted(served - reachable)}; "
        f"in the table but not served: {sorted(reachable - served)}"
    )


def test_the_sweep_is_not_vacuous(world: dict) -> None:
    """A sweep that walks nothing passes forever.

    Two independent floors, because the two ways this goes quiet are
    different: a params table that stops reaching views (caught by the
    view count) and a response shape that stops exposing lanes (caught by
    the lane count). Numbers are floors read from head, not equalities —
    an equality here would red on every future view and teach its readers
    to edit the guard.
    """
    lanes = sum(len(_lanes(_fetch(world, name))) for name in VIEWS)
    assert len(VIEWS) >= 13, f"only {len(VIEWS)} views served"
    assert lanes >= 60, f"the sweep found only {lanes} lanes across {len(VIEWS)} views"


# -- acceptance 2: the mutation reddens exactly one (view, key) ---------------


def test_removing_one_string_reddens_exactly_that_lane(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brief acceptance 2. A sweep that goes red is worth nothing until you
    know it goes red for the RIGHT ROW — a guard that reports the whole
    board on any single fault is a guard nobody can act on, and one that
    over-reports gets edited out the first time it is inconvenient.

    Blanking one constant must produce exactly one name in the failure,
    and it must be that constant's own."""
    from korax import reductions

    monkeypatch.setattr(reductions, "DOCKET_UNGATED_IS", "")

    body = _fetch(world, "docket")
    holder = _twin_holder(body)
    blanked = [lane for lane in _lanes(body)
               if not str(holder.get(f"{lane}_is", "")).strip()]

    assert blanked == ["ungated"], (
        f"blanking `DOCKET_UNGATED_IS` should leave exactly `docket.ungated` "
        f"without a twin; the sweep reports {blanked}"
    )
    # And the other twelve views are untouched by it — the fault is local.
    for name in VIEWS:
        if name == "docket":
            continue
        other = _fetch(world, name)
        other_holder = _twin_holder(other)
        assert all(
            str(other_holder.get(f"{lane}_is", "")).strip()
            for lane in _lanes(other)
        ), f"blanking a docket constant reddened `{name}` too"


# -- acceptance 3: the two named strings, and the one that must track code ---


def test_escalated_is_names_the_prose_ask_blind_spot() -> None:
    """Brief acceptance 3, first half. `escalated` read 0 while the floor
    was blocked on an operator question (#3748 §1) — the count was right
    and the reader's inference was wrong. The string has to name the act
    key AND the thing the key cannot see, because naming a trap without
    naming its shape leaves the reader where they were."""
    from korax.reductions import DOCKET_ESCALATED_IS

    assert "/korax/inbox" in DOCKET_ESCALATED_IS, "the key's namespace is unnamed"
    assert "OPEN" in DOCKET_ESCALATED_IS, "the act it keys on is unnamed"
    assert "PROSE" in DOCKET_ESCALATED_IS.upper(), (
        "the blind spot #3748 §1 measured — a question asked in prose is "
        "not an OPEN and is not here — must be named, not implied"
    )


def test_ungated_is_tracks_the_keys_its_own_code_actually_reads() -> None:
    """Brief acceptance 3, second half, as a SOURCE-COUPLED assertion
    rather than a promise.

    The brief says `ungated_is` names the `closes`-edge key today and the
    marker key once R1b (#3769) lands, and that this JOB's test makes
    forgetting the update a red. A test that only checked today's text
    could not do that — it would stay green through exactly the delivery
    it is meant to catch. So the assertion is against `_ungated`'s own
    source: whatever membership keys the function reads, the string must
    name. R1b adds `ext.korax.delivery` to that function and this test
    goes red until the string says so.

    This is property 2 made enforceable — the string cannot drift from
    the computation, because the computation is what it is checked
    against."""
    import inspect

    from korax import reductions
    from korax.reductions import DOCKET_UNGATED_IS

    src = inspect.getsource(reductions._ungated)

    assert "closes" in DOCKET_UNGATED_IS, (
        "`_ungated` keys membership on the `closes` edge and the string "
        "must say so"
    )

    reads_marker = "korax.delivery" in src or "DELIVERY_MARKER" in src
    names_marker = "ext.korax.delivery" in DOCKET_UNGATED_IS
    assert reads_marker == names_marker, (
        "`_ungated` "
        + ("now reads the delivery marker but `DOCKET_UNGATED_IS` does not "
           "name it — R1b (#3769) landed and its string was not updated"
           if reads_marker else
           "does not read the delivery marker, but `DOCKET_UNGATED_IS` "
           "claims it does — the string is ahead of the code")
    )
