"""fixture-09 — the docket (§10.12).

Two guarantees:
  1. every check in expected-09 matches this engine, including which
     inbox OPENs route to which project;
  2. the `must_not` list holds — and it is the load-bearing half here,
     because the union scoping is a rule about what MUST NOT be
     included, and a board that routes everything passes every positive
     check in this file.

The prefix case is the one worth naming. carol holds `/proj-tools/**`,
which is a string prefix of `/proj` and not a subtree of it. Swapping
`in_subtree` for `startswith` reddens **three** cases here — both
`/proj` checks and the `must_not` test — measured by making the swap
rather than reasoned about. (An earlier version of this docstring said
it would fail one `must_not` entry and pass every positive check. That
was a guess, and the fixture is stronger than the guess.)

It is not hypothetical: measuring this board's own inbox with a prefix
test reported 26/27 OPENs as `/korax` escalations against a true figure
of 14/27, and that wrong number reached a design note and a desk
endorsement before anyone re-derived it.
"""

from __future__ import annotations

import json

import pytest

from conftest import CONFORMANCE, load_jsonl
from korax.log import Log
from korax.models import Envelope
from korax.policy import PolicyTimeline
from korax.reductions import docket, project_bands

with open(CONFORMANCE / "expected-09.json", encoding="utf-8") as f:
    EXPECTED = json.load(f)


@pytest.fixture(scope="module")
def world() -> tuple[Log, PolicyTimeline]:
    log = Log([Envelope.model_validate(r) for r in load_jsonl("fixture-09.jsonl")])
    return log, PolicyTimeline(log)


@pytest.mark.parametrize(
    "check", EXPECTED["checks"], ids=lambda c: f"docket@{c['offset']}-{c['cite']}"
)
def test_expected(world: tuple[Log, PolicyTimeline], check: dict) -> None:
    log, tl = world
    args = check["args"]
    actual = docket(log, tl, check["offset"], args["ns"], args.get("identity"))
    expect, why = check["expect"], check["why"]

    assert actual["work"]["open"] == expect["work_open"], why
    assert [
        {"job": t["job"], "holder": t["holder"], "via": t["via"]}
        for t in actual["work"]["taken"]
    ] == expect["work_taken"], why
    assert [f["id"] for f in actual["filed"]] == expect["filed"], why
    assert [e["id"] for e in actual["escalated"]] == expect["escalated"], why
    assert actual["namespaces"] == expect["namespaces"], why
    assert actual["totals"] == expect["totals"], why

    for env_id, line in expect.get("first_line", {}).items():
        got = next(f for f in actual["filed"] if f["id"] == int(env_id))
        assert got["first_line"] == line, why


def test_a_stranger_and_a_prefix_neighbour_stay_out(
    world: tuple[Log, PolicyTimeline],
) -> None:
    """`must_not` entries 1-3: the union must not widen.

    #12 is a stranger's escalation; #13's author holds `/proj-tools/**`,
    a string prefix of `/proj` that is not a subtree of it; and every
    identity holds the `band:*` reader floor at `/**`, whose root is `/`.
    Any of the three routing into `/proj` means the membership predicate
    has stopped being subtree matching."""
    log, tl = world
    escalated = [e["id"] for e in docket(log, tl, 13, "/proj")["escalated"]]
    assert 12 not in escalated
    assert 13 not in escalated

    bands = project_bands(tl, "/proj", 13)
    assert bands == {"band:alice"}, (
        f"project bands for /proj should be alice alone; got {bands}. "
        "bob holds /other/**, carol holds /proj-tools/** (a prefix, not a "
        "subtree), and the band:* floor is rooted at / — none of them are "
        "project membership."
    )
    assert "band:*" not in bands, "the floor grant is not a member"


def test_a_closed_open_never_appears_filed(
    world: tuple[Log, PolicyTimeline],
) -> None:
    """`must_not` entry 4. #8 is closed by #9, so it is filed at offset 8
    and gone at 9 — and the decision belongs to §10.1, not to a second
    implementation living in the docket."""
    log, tl = world
    assert [f["id"] for f in docket(log, tl, 8, "/proj")["filed"]] == [7, 8]
    assert [f["id"] for f in docket(log, tl, 13, "/proj")["filed"]] == [7]


def test_totals_survive_narrowing(world: tuple[Log, PolicyTimeline]) -> None:
    """`must_not` entry 5, at every identity rather than the one the
    checks happen to name."""
    log, tl = world
    whole = docket(log, tl, 13, "/proj")["totals"]
    for who in ("band:alice", "band:bob", "band:carol", "band:nobody"):
        assert docket(log, tl, 13, "/proj", who)["totals"] == whole, who


def test_the_must_not_list_is_carried(world: tuple[Log, PolicyTimeline]) -> None:
    """A fixture whose `must_not` list nobody reads is prose (#111)."""
    assert len(EXPECTED["must_not"]) >= 6
    for entry in EXPECTED["must_not"]:
        assert entry["rule"] and entry["cite"]
