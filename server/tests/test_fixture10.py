"""fixture-10 — job ordering (§10.8/§12.7). JOB #387.

The positive checks pin the RELEASE transitions; the `must_not` list
pins the distinction the job exists for. A board that reads `part-of`
as blocked-by passes a membership test, produces a plausible-looking
DAG, and fails the very first check here — because the campaign at #4
is open and its children must still be claimable.
"""

from __future__ import annotations

import json

import pytest

from conftest import CONFORMANCE, load_jsonl
from korax.log import Log
from korax.models import Envelope
from korax.policy import PolicyTimeline
from korax.reductions import jobs

with open(CONFORMANCE / "expected-10.json", encoding="utf-8") as f:
    EXPECTED = json.load(f)


@pytest.fixture(scope="module")
def world() -> tuple[Log, PolicyTimeline]:
    log = Log([Envelope.model_validate(r) for r in load_jsonl("fixture-10.jsonl")])
    return log, PolicyTimeline(log)


@pytest.mark.parametrize("check", EXPECTED["checks"],
                         ids=lambda c: f"jobs@{c['offset']}-{c['cite']}")
def test_expected(world: tuple[Log, PolicyTimeline], check: dict) -> None:
    log, tl = world
    actual = jobs(log, tl, check["offset"], check["args"]["ns"])
    expect, why = check["expect"], check["why"]
    assert actual["ready"] == expect["ready"], why
    assert actual["blocked_by"] == expect["blocked_by"], why
    assert actual["forest"] == expect["forest"], why
    assert [t["job"] for t in actual["taken"]] == expect["taken"], why


def test_campaign_children_are_never_blocked_by_their_parent(
    world: tuple[Log, PolicyTimeline],
) -> None:
    """`must_not` 1, at EVERY offset rather than the four the checks
    happen to name — the rule is not about a moment."""
    log, tl = world
    for offset in range(2, 15):
        out = jobs(log, tl, offset, "/proj")
        for parent, children in out["forest"].items():
            for child in children:
                assert int(parent) not in out["blocked_by"].get(str(child), []), (
                    f"at offset {offset}, child {child} is blocked by its own "
                    f"campaign {parent} — part-of is breakdown, not ordering"
                )


def test_a_job_with_no_edges_is_always_ready(
    world: tuple[Log, PolicyTimeline],
) -> None:
    """`must_not` 5. Absence of ordering is not ordering — defaulting
    unstated jobs to blocked would strand every job posted before this
    convention existed, which is all 28 of them on the board that
    motivated it."""
    log, tl = world
    for offset in range(2, 15):
        assert 2 in jobs(log, tl, offset, "/proj")["ready"], offset


def test_the_must_not_list_is_carried(world: tuple[Log, PolicyTimeline]) -> None:
    assert len(EXPECTED["must_not"]) >= 6
    for entry in EXPECTED["must_not"]:
        assert entry["rule"] and entry["cite"]
