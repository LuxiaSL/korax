"""rejects-01.jsonl — every post case MUST fail with the stated code;
every read case MUST filter (or not) exactly as stated."""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import load_jsonl, truncated
from korax.log import Log
from korax.models import Envelope
from korax.reductions import fresh, state
from korax.validate import PostError, validate_post

CASES = load_jsonl("rejects-01.jsonl")
POST_CASES = [c for c in CASES if c["kind"] == "post"]
READ_CASES = [c for c in CASES if c["kind"] == "read"]


def _expand_payload(envelope: dict) -> dict:
    """Fill constants the fixture elides (proto, the size placeholder) —
    only fields no reject case is actually about."""
    out = dict(envelope)
    out.setdefault("proto", "korax/0.1")
    if out.get("payload") == "<<17 KiB of text>>":
        out["payload"] = "x" * (17 * 1024)
    return out


@pytest.mark.parametrize("case", POST_CASES, ids=[c["case"] for c in POST_CASES])
def test_post_rejected(case: dict, full_log: Log) -> None:
    log, timeline = truncated(full_log, case["after_offset"])
    envelope = _expand_payload(case["envelope"])
    with pytest.raises(PostError) as excinfo:
        validate_post(log, timeline, envelope)
    assert excinfo.value.code == case["expect"]["code"], (
        f"{case['case']}: expected {case['expect']['code']}, "
        f"got {excinfo.value.code}: {excinfo.value.message}"
    )


def _synthesize(log: Log, post: dict) -> Log:
    last = log.envelopes[-1]
    record = dict(
        post,
        proto="korax/0.1",
        id=log.next_id(),
        ts=(last.ts + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        band="claimant",
    )
    return Log(log.envelopes + [Envelope.model_validate(record)])


def _visible_ids(view_output) -> set[int]:
    if isinstance(view_output, list):  # fresh
        return {entry["id"] for entry in view_output}
    ids: set[int] = set()
    for key in ("opens", "proposals", "findings", "stamped", "invalidated"):
        ids.update(view_output.get(key, []))
    for cluster in view_output.get("beside_clusters", []):
        ids.update(cluster)
    return ids


@pytest.mark.parametrize("case", READ_CASES, ids=[c["case"] for c in READ_CASES])
def test_read_filtered(case: dict, full_log: Log) -> None:
    log, timeline = truncated(full_log, case["after_offset"])
    if "precondition" in case:
        log = _synthesize(log, case["precondition"]["post"])
        timeline = truncated(log, log.envelopes[-1].id)[1]
    offset = log.envelopes[-1].id
    request = case["request"]
    if request["view"] == "state":
        output = state(log, timeline, offset, request["ns"], requester=case["as"])
    elif request["view"] == "fresh":
        output = fresh(log, timeline, offset, request["ns_set"], request["horizon"])
    else:
        pytest.fail(f"unhandled view {request['view']}")
    ids = _visible_ids(output)
    for absent in case["expect"].get("absent", []):
        assert absent not in ids, f"{case['case']}: {absent} must be filtered"
    for present in case["expect"].get("present", []):
        assert present in ids, f"{case['case']}: {present} must be visible"
