"""fixture-05 — retention as a read-side default (§8.2, R22).

Two guarantees:
  1. every check in expected-05 matches the partition this engine
     applies, at the stated offset, for the stated namespace;
  2. the `must_not` list holds — governance survives every horizon, the
     anchor survives, rotated envelopes still resolve by id and through
     the edge-walking views, and a withheld envelope is always counted.

The fixture's timestamps span four months of log time and the cutoffs
come from the log, so this file does not rot: it asserts the same thing
next month as today. A board taking its cutoff from wall clock passes on
no day but one.
"""

from __future__ import annotations

import json

import pytest

from conftest import CONFORMANCE, load_jsonl
from korax.log import Log
from korax.models import Envelope
from korax.nsglob import in_subtree
from korax.policy import PolicyTimeline
from korax.reductions import descendants, provenance, taint, thread
from korax.retention import ROTATION_EXEMPT_ACTS, project, split

with open(CONFORMANCE / "expected-05.json", encoding="utf-8") as f:
    EXPECTED = json.load(f)


def load_fixture05() -> list[Envelope]:
    return [Envelope.model_validate(r) for r in load_jsonl("fixture-05.jsonl")]


@pytest.fixture(scope="module")
def world() -> tuple[Log, PolicyTimeline]:
    log = Log(load_fixture05())
    return log, PolicyTimeline(log)


def partition(world, offset: int, ns: str) -> tuple[list[int], list[int]]:
    log, timeline = world
    scoped = [e for e in log.upto(offset) if in_subtree(ns, e.ns)]
    kept, rotated = split(log, timeline, scoped, offset)
    return [e.id for e in kept], [e.id for e in rotated]


@pytest.mark.parametrize(
    "check", EXPECTED["checks"],
    ids=[f"{c['view']}@{c['offset']}:{c['args']['ns']}" for c in EXPECTED["checks"]],
)
def test_expected_partition(world, check: dict) -> None:
    assert check["view"] == "retention", "fixture-05 checks one projection only"
    kept, rotated = partition(world, check["offset"], check["args"]["ns"])
    assert kept == check["expect"]["kept"], check["why"]
    assert rotated == check["expect"]["rotated"], check["why"]


def test_governance_never_rotates_anywhere(world) -> None:
    log, timeline = world
    for offset in (8, 12, log.envelopes[-1].id):
        _kept, rotated = split(log, timeline, log.upto(offset), offset)
        assert not [e for e in rotated if e.type in ROTATION_EXEMPT_ACTS]


def test_the_anchor_never_rotates(world) -> None:
    log, timeline = world
    for offset in (e.id for e in log.envelopes):
        _kept, rotated = split(log, timeline, log.upto(offset), offset)
        assert offset not in [e.id for e in rotated]


def test_rotation_deletes_nothing_and_renumbers_nothing(world) -> None:
    """Rule 1 — a rotated envelope keeps its id and stays a valid referent."""
    log, timeline = world
    rot_log, rotated = project(log, timeline, log, offset=12)
    assert rotated, "fixture must actually rotate something at offset 12"
    for env in rotated:
        assert log.get(env.id) is env  # still on the log, same id
        assert rot_log.get(env.id) is None  # and out of the discovery view


def test_direct_address_and_edge_walks_resolve_rotated_envelopes(world) -> None:
    """Rule 4 — rotation bounds discovery, not reference. Id 7 replies to
    id 3, which is rotated at offset 12; the thread must still hold."""
    log, timeline = world
    _kept, rotated = split(log, timeline, log.upto(12), 12)
    assert 3 in [e.id for e in rotated]

    spine = thread(log, 12, 3)
    assert spine["root"] == 3
    assert "7" in str(spine["replies"])
    # the other edge-walking views resolve it too, and none of them filter
    for view in (provenance, descendants, taint):
        assert view(log, 12, 3) is not None


def test_a_withheld_envelope_is_always_counted(world) -> None:
    """Rule 6 — an enforcing board and a board ignoring retention must not
    look the same to a client that arrived after the horizon."""
    log, timeline = world
    for check in EXPECTED["checks"]:
        _kept, rotated = partition(world, check["offset"], check["args"]["ns"])
        assert len(rotated) == len(check["expect"]["rotated"])
