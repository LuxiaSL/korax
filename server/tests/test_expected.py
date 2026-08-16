"""expected-01.json — every reduction at every stated offset, compared
key-for-key (expected keys must match exactly; commentary keys ignored;
extra keys in our output are allowed so richer responses stay conforming)."""

from __future__ import annotations

import json

import pytest

from conftest import CONFORMANCE, truncated
from korax.log import Log
from korax.reductions import (
    descendants,
    fresh,
    jobs,
    of_record,
    provenance,
    state,
    taint,
    thread,
)

IGNORED_KEYS = {"why", "note", "_note"}

with open(CONFORMANCE / "expected-01.json", encoding="utf-8") as f:
    EXPECTED = json.load(f)

CHECKS = EXPECTED["checks"]


def run_view(log: Log, timeline, offset: int, view: str, args: dict):
    if view == "state":
        return state(log, timeline, offset, args["ns"])
    if view == "jobs":
        return jobs(log, timeline, offset, args["ns"])
    if view == "of-record":
        return of_record(log, offset, args["project"])
    if view == "provenance":
        return provenance(log, offset, args["id"])
    if view == "descendants":
        return descendants(log, offset, args["id"])
    if view == "taint":
        return taint(log, offset, args["id"])
    if view == "fresh":
        return fresh(log, timeline, offset, args["ns_set"], args["horizon"])
    if view == "thread":
        return thread(log, offset, args["id"])
    pytest.fail(f"unhandled view {view}")


def assert_subset(expected, actual, path=""):
    """Expected keys must be present and equal; commentary ignored."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected object, got {type(actual).__name__}"
        for key, value in expected.items():
            if key in IGNORED_KEYS:
                continue
            assert key in actual, f"{path}.{key}: missing from output"
            assert_subset(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list"
        assert len(expected) == len(actual), (
            f"{path}: expected {len(expected)} items, got {len(actual)}: {actual!r}"
        )
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            assert_subset(e, a, f"{path}[{i}]")
    else:
        assert expected == actual, f"{path}: expected {expected!r}, got {actual!r}"


def check_id(check: dict) -> str:
    return f"{check['view']}@{check['offset']}-{list(check['args'].values())[0]}"


@pytest.mark.parametrize("check", CHECKS, ids=[check_id(c) for c in CHECKS])
def test_expected_reduction(check: dict, full_log: Log) -> None:
    log, timeline = truncated(full_log, check["offset"])
    actual = run_view(log, timeline, check["offset"], check["view"], check["args"])
    assert_subset(check["expect"], actual, check["view"])


def test_reductions_are_deterministic(full_log: Log) -> None:
    """must_not #4 — re-running any check returns identical output."""
    for check in CHECKS:
        log, timeline = truncated(full_log, check["offset"])
        first = run_view(log, timeline, check["offset"], check["view"], check["args"])
        log2, timeline2 = truncated(full_log, check["offset"])
        second = run_view(log2, timeline2, check["offset"], check["view"], check["args"])
        assert json.dumps(first, default=str, sort_keys=True) == json.dumps(
            second, default=str, sort_keys=True
        ), f"non-deterministic: {check_id(check)}"


def test_must_not_offtopic_in_work_views(full_log: Log) -> None:
    """must_not #1 — envelope 27 appears in no /atlas or rakes reduction."""
    log, timeline = truncated(full_log, 32)
    board = state(log, timeline, 32, "/atlas/board")
    digest = fresh(log, timeline, 32, ["/commons/**", "/atlas/**"], "P7D")
    assert 27 not in board["findings"]
    assert 27 not in [entry["id"] for entry in digest]


def test_must_not_collapse(full_log: Log) -> None:
    """must_not #3 — no selection among proposals, no cluster collapse."""
    log, timeline = truncated(full_log, 27)
    board = state(log, timeline, 27, "/atlas/board")
    assert board["proposal_primary"] is None
    assert board["proposals"] == [25, 26]
    assert board["beside_primary"] is None
    assert [13, 17] in board["beside_clusters"]
