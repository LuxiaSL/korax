"""fixture-04 — the civic layer: pins, required reading, acks, the
amendment loop, and the graduation ceremony.

Three guarantees:
  1. every envelope in the fixture replays clean through the full
     /post gauntlet (the accepted log is actually acceptable);
  2. every rejects-04 case fails with the stated code, and where the
     case states `missing`, the 409 lists exactly those ids;
  3. every expected-04 reduction matches key-for-key.
"""

from __future__ import annotations

import json

import pytest

from conftest import CONFORMANCE, load_jsonl, truncated, FakeRegistry
from korax.civic import onboard, required
from korax.log import Log
from korax.models import Envelope
from korax.policy import PolicyTimeline
from korax.reductions import jobs
from korax.validate import SERVER_ASSIGNED, PostError, validate_post

from test_expected import assert_subset


def load_fixture04() -> list[Envelope]:
    envelopes = []
    with open(CONFORMANCE / "fixture-04.jsonl", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if "_comment" in record:
                continue
            envelopes.append(Envelope.model_validate(record))
    return envelopes


@pytest.fixture(scope="module")
def log04() -> Log:
    return Log(load_fixture04())


@pytest.fixture(scope="module")
def timeline04(log04: Log) -> PolicyTimeline:
    return PolicyTimeline(log04)


REJECTS = [c for c in load_jsonl("rejects-04.jsonl") if c["kind"] == "post"]

with open(CONFORMANCE / "expected-04.json", encoding="utf-8") as f:
    CHECKS = json.load(f)["checks"]


# -- 1. the accepted log replays clean ----------------------------------


def test_fixture_parses(log04: Log) -> None:
    assert len(log04) == 31
    assert [e.id for e in log04.envelopes] == list(range(31))


def test_fixture_replays_through_gauntlet(log04: Log) -> None:
    """Every envelope after genesis, resubmitted against the log so far,
    passes validation — the fixture contains nothing the server would
    refuse. Genesis (offset 0) is the §8.4 bootstrap and is skipped."""
    for env in log04.envelopes[1:]:
        prior, timeline = truncated(log04, env.id - 1)
        raw = env.model_dump(mode="json", exclude_none=True)
        for field in (*SERVER_ASSIGNED, "sig"):
            raw.pop(field, None)
        try:
            validate_post(prior, timeline, raw, FakeRegistry())
        except PostError as exc:  # pragma: no cover - failure formatting
            pytest.fail(f"envelope {env.id} rejected: {exc.code} {exc.message}")


# -- 2. rejects ----------------------------------------------------------


@pytest.mark.parametrize("case", REJECTS, ids=[c["case"] for c in REJECTS])
def test_rejected(case: dict, log04: Log) -> None:
    log, timeline = truncated(log04, case["after_offset"])
    envelope = dict(case["envelope"])
    envelope.setdefault("proto", "korax/0.1")
    with pytest.raises(PostError) as excinfo:
        validate_post(log, timeline, envelope, FakeRegistry())
    assert excinfo.value.code == case["expect"]["code"], (
        f"{case['case']}: expected {case['expect']['code']}, "
        f"got {excinfo.value.code}: {excinfo.value.message}"
    )
    if "missing" in case["expect"]:
        assert excinfo.value.missing == case["expect"]["missing"], (
            f"{case['case']}: the error must be the reading list — "
            f"expected {case['expect']['missing']}, got {excinfo.value.missing}"
        )


# -- 3. expected reductions ----------------------------------------------


def run_view(log: Log, timeline: PolicyTimeline, offset: int, view: str, args: dict):
    if view == "onboard":
        return onboard(log, timeline, offset, args["identity"])
    if view == "required":
        return required(log, timeline, offset, args["id"], args["identity"])
    if view == "jobs":
        return jobs(log, timeline, offset, args["ns"])
    pytest.fail(f"unhandled view {view}")


def check_id(check: dict) -> str:
    return f"{check['view']}@{check['offset']}-{list(check['args'].values())[-1]}"


@pytest.mark.parametrize("check", CHECKS, ids=[check_id(c) for c in CHECKS])
def test_expected_reduction(check: dict, log04: Log) -> None:
    log, timeline = truncated(log04, check["offset"])
    actual = run_view(log, timeline, check["offset"], check["view"], check["args"])
    assert_subset(check["expect"], actual, check["view"])
