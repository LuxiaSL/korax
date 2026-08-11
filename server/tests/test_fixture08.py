"""fixture-08 — the unified feed (§11.2, R32).

Two guarantees:
  1. every check in expected-08 matches the union this engine computes,
     for the stated requester, cursor and offset — including the reasons,
     because a board that serves an envelope it cannot explain has not
     built a feed, it has built a louder /read;
  2. the `must_not` list holds — dedup, envelope bytes unchanged by the
     lane that found them, a closed subscription window staying closed,
     per-lane R19c, and an uncounted no-grant denial.

The `must_not` list is the half that matters, for the reason fixture-06
gives: every positive check above it is satisfied by a board that
concatenates lanes instead of unioning them. Such a board serves the
right SET and the wrong PAGE — three copies of the one envelope that
matched three lanes — and the wake saving that justifies the whole
endpoint evaporates while every membership assertion still passes.
"""

from __future__ import annotations

import json

import pytest

from conftest import CONFORMANCE, load_jsonl, FakeRegistry
from korax.access import filter_log
from korax.feed import (
    descended_targets,
    in_feed,
    live_subscriptions,
    reasons_for,
)
from korax.log import Log
from korax.models import Envelope, EdgeType
from korax.policy import PolicyTimeline

with open(CONFORMANCE / "expected-08.json", encoding="utf-8") as f:
    EXPECTED = json.load(f)


def load_fixture08() -> list[Envelope]:
    return [Envelope.model_validate(r) for r in load_jsonl("fixture-08.jsonl")]


@pytest.fixture(scope="module")
def world() -> tuple[Log, PolicyTimeline]:
    log = Log(load_fixture08())
    return log, PolicyTimeline(log)


def _authored(log: Log, identity: str) -> set[int]:
    return {e.id for e in log.envelopes if e.author == identity}


def _worked(log: Log, identity: str) -> set[int]:
    out: set[int] = set()
    for e in log.envelopes:
        if e.author != identity:
            continue
        for r in e.refs:
            if r.edge in (EdgeType.CLAIMS, EdgeType.CLOSES):
                out.add(r.id)
    return out


def feed(world, requester: str, since: int, offset: int) -> dict:
    """What a conforming board serves on /feed — the union, its reasons,
    and the union-scoped counters."""
    log, tl = world
    visible, sealed, private = filter_log(log, tl, requester, offset)
    authored = _authored(visible, requester)
    worked = _worked(visible, requester)
    descended = descended_targets(visible, requester, offset)
    subs = live_subscriptions(visible, requester, offset)

    def matched(envs) -> list[Envelope]:
        return [
            e for e in envs
            if e.id <= offset
            and in_feed(e, requester, since, authored, worked, descended, subs,
                        True)
        ]

    hits = matched(visible.envelopes)
    return {
        "envelopes": [e.id for e in hits],
        "reasons": {
            str(e.id): reasons_for(e, requester, authored, worked, descended,
                                   subs, True)
            for e in hits
        },
        "sealed_excluded": len(matched(sealed)),
        "participation_excluded": len(matched(private)),
    }


def _as_sets(reasons: dict) -> dict:
    """Lane order within one envelope is not specified (expected-08's own
    conventions), so reasons compare as sets of frozen items."""
    return {
        env_id: {tuple(sorted(r.items())) for r in rs}
        for env_id, rs in reasons.items()
    }


@pytest.mark.parametrize(
    "check", EXPECTED["checks"],
    ids=lambda c: f"{c['args']['requester']}@{c['args']['since']}"
)
def test_expected_feed(world, check: dict) -> None:
    got = feed(world, check["args"]["requester"], check["args"]["since"],
               check["offset"])
    want = check["expect"]
    assert got["envelopes"] == want["envelopes"], check["why"]
    assert _as_sets(got["reasons"]) == _as_sets(want["reasons"]), check["why"]
    assert got["sealed_excluded"] == want["sealed_excluded"], check["why"]
    assert got["participation_excluded"] == want["participation_excluded"], (
        check["why"]
    )


# ── must_not: the invariants no positive check can express ────────────


REQUESTERS = ["band:human", "band:alice", "band:bob", "band:carol"]

#: The bands this fixture's envelopes actually mention (JOB #1079).
#:
#: **Populated rather than permissive, and that is load-bearing here.** The
#: mention gauntlet now refuses an unknown band id BEFORE it asks whether
#: that band can read the nest — correctly, since you cannot ask what an
#: unknown band may read. So a registry that knew nothing would refuse these
#: fixtures at the existence check and the readability cases below would go
#: green while never reaching the guard they exist to test. That is the exact
#: shape of defect this job was opened to remove; reproducing it inside the
#: job's own suite would be the joke writing itself.
FIXTURE_REGISTRY = FakeRegistry({
    b: b.removeprefix("band:") for b in REQUESTERS + ["band:dave"]
})


def test_no_envelope_appears_twice(world) -> None:
    """§11.2.3 — dedup is by id at the point the lanes are unioned. 14
    matches three lanes for alice; a board concatenating lanes serves it
    three times and every membership check still passes."""
    page = feed(world, "band:alice", -1, 21)
    assert len(page["envelopes"]) == len(set(page["envelopes"]))
    assert 14 in page["envelopes"]
    assert len(page["reasons"]["14"]) == 3, (
        "the dedup case must actually be multi-lane, or this proves nothing"
    )


def test_the_bytes_do_not_depend_on_how_it_was_found(world) -> None:
    """§11.2.3 — an envelope must not gain fields from the lane that
    matched it, or replay and signature verification die together."""
    log, _ = world
    plain = log.get(14).model_dump(mode="json", exclude_none=True)
    page = feed(world, "band:alice", -1, 21)
    assert "14" in page["reasons"]
    # the served bytes are the log's bytes, and the reasons are elsewhere
    assert plain == log.get(14).model_dump(mode="json", exclude_none=True)
    for key in ("reasons", "lane", "via", "sub"):
        assert key not in plain, f"{key} leaked into the envelope"


def test_a_closed_window_stays_closed_on_every_replay(world) -> None:
    """§11.2.1 — a subscription is a window, not a flag. 17 is inside
    alice's /quiet window and 19 is past it, at every offset from the
    supersede onward."""
    for offset in range(18, 22):
        served = feed(world, "band:alice", -1, offset)["envelopes"]
        assert 17 in served, f"the window closed retroactively at {offset}"
        assert 19 not in served, f"a superseded lane re-opened at {offset}"


def test_19_reaches_nobody_on_any_lane(world) -> None:
    for requester in REQUESTERS:
        for offset in range(19, 22):
            assert 19 not in feed(world, requester, -1, offset)["envelopes"], (
                f"{requester} was served 19 at {offset}"
            )


def test_alices_own_delivery_never_reaches_her(world) -> None:
    """§11.2 — per-lane R19c. 15 edges both of alice's anchors, so it is
    the first envelope a board with weak self-exclusion serves."""
    for since in (-1, 5, 14):
        for offset in range(15, 22):
            page = feed(world, "band:alice", since, offset)
            assert 15 not in page["envelopes"], (
                f"alice was woken by her own delivery (since={since}, "
                f"offset={offset})"
            )
    # …and it is nobody else's problem: carol hears it through no lane,
    # while a board that dropped R19c globally would also hide it from
    # readers who should see it. Here nothing points at 15 at all.
    assert 15 not in feed(world, "band:carol", -1, 21)["envelopes"]


def test_a_no_grant_denial_is_never_counted(world) -> None:
    """§9.3 — carol holds nothing in /quiet. The absence comes from the
    access layer and must stay uncounted, or a feed becomes a map of how
    much exists where the reader holds no grant."""
    log, tl = world
    quiet = {e.id for e in log.envelopes if e.ns.startswith("/quiet")}
    assert quiet, "the fixture lost its ungranted nest"
    for offset in range(17, 22):
        page = feed(world, "band:carol", -1, offset)
        assert not (quiet & set(page["envelopes"]))
        assert page["sealed_excluded"] == 0
        assert page["participation_excluded"] == 0


def test_descent_via_names_the_requesters_own_envelope(world) -> None:
    """§11.2.3 — `via` answers "why am I hearing this?" in one read, and
    for descent the answer is alice's 9, not the shared referent 8."""
    reasons = feed(world, "band:alice", -1, 21)["reasons"]["21"]
    assert reasons == [{"lane": "descent", "via": 9, "sub": 20}]


def test_descent_is_not_a_default_lane(world) -> None:
    """Bob never declared descent. 21 reaches him through to_author only,
    and would reach him not at all if it did not edge his own 8."""
    reasons = feed(world, "band:bob", -1, 21)["reasons"]["21"]
    assert reasons == [{"lane": "to_author"}]


# ── the fixture replays clean, and its rejects are refused ────────────


def test_fixture_replays_through_gauntlet(world) -> None:
    """Every envelope after genesis, resubmitted against the log so far,
    passes validation — the fixture contains nothing the server would
    refuse. Without this, a fixture can encode a board that does not
    exist and every expectation above is a check on fiction."""
    from korax.validate import PostError, SERVER_ASSIGNED, validate_post

    log, _ = world
    for env in log.envelopes[1:]:
        prior = Log([e for e in log.envelopes if e.id < env.id])
        raw = env.model_dump(mode="json", exclude_none=True)
        for field in (*SERVER_ASSIGNED, "sig"):
            raw.pop(field, None)
        try:
            validate_post(prior, PolicyTimeline(prior), raw, FIXTURE_REGISTRY)
        except PostError as exc:  # pragma: no cover - failure formatting
            pytest.fail(f"envelope {env.id} rejected: {exc.code} {exc.message}")


REJECTS = [c for c in load_jsonl("rejects-08.jsonl") if c.get("kind") == "post"]


@pytest.mark.parametrize("case", REJECTS, ids=[c["case"] for c in REJECTS])
def test_rejected(case: dict, world) -> None:
    from korax.validate import PostError, validate_post

    log, _ = world
    prior = Log([e for e in log.envelopes if e.id <= case["after_offset"]])
    envelope = dict(case["envelope"])
    envelope.setdefault("proto", "korax/0.1")
    with pytest.raises(PostError) as excinfo:
        validate_post(prior, PolicyTimeline(prior), envelope, FIXTURE_REGISTRY)
    assert excinfo.value.code == case["expect"]["code"], (
        f"{case['case']}: expected {case['expect']['code']}, "
        f"got {excinfo.value.code}: {excinfo.value.message}"
    )
