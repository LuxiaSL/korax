"""fixture-06 — the exclusion counters, for every reader (§9.3, R28).

Two guarantees:
  1. every check in expected-06 matches the partition this engine
     applies, for the stated requester and namespace;
  2. the `must_not` list holds — a blind round and a missing grant are
     withheld without ever being counted, the two counters never
     double-count an envelope, and no page names what it withheld.

The `must_not` list is the half that matters. Every positive check
above it could be satisfied by a board that simply counts every denial,
and such a board would report a blind round's fill level to the peer
being blinded — arithmetic satisfied, §8.3 destroyed. No positive check
can express "and nothing else was counted", so the invariants do.
"""

from __future__ import annotations

import json

import pytest

from conftest import CONFORMANCE, load_jsonl
from korax.access import filter_log, verdict
from korax.counters import bucketed
from korax.log import Log
from korax.models import Envelope
from korax.nsglob import in_subtree
from korax.policy import PolicyTimeline

with open(CONFORMANCE / "expected-06.json", encoding="utf-8") as f:
    EXPECTED = json.load(f)


def load_fixture06() -> list[Envelope]:
    return [Envelope.model_validate(r) for r in load_jsonl("fixture-06.jsonl")]


@pytest.fixture(scope="module")
def world() -> tuple[Log, PolicyTimeline]:
    log = Log(load_fixture06())
    return log, PolicyTimeline(log)


def partition(world, requester: str, ns: str, offset: int):
    """What a conforming board serves for this slice, and what it must
    report having withheld — the shape §9.3 requires of /read."""
    log, tl = world
    visible, sealed, private = filter_log(log, tl, requester, offset)
    keep = lambda envs: [e.id for e in envs if in_subtree(ns, e.ns) and e.id <= offset]
    return (
        keep(visible.envelopes),
        len(keep(sealed)),
        # REPORTED, not partitioned. expected-06's own conventions say these
        # are "the counts it MUST report", and since #388 the participation
        # counter reports presence rather than cardinality. Running the
        # partition through the same function the API uses is what keeps the
        # conformance file describing the wire — checking the raw partition
        # here would let the file document a contract no board implements.
        bucketed(len(keep(private))),
    )



def assert_participation(actual, expected, why: str) -> None:
    """Compare the reported participation counter against the fixture.

    A bucketed marker is compared STRUCTURALLY: the fixture pins
    `withheld` and requires a non-empty `why`, but never the why's prose.
    #662 requires the marker to carry a reason; pinning the sentence would
    make every conforming board reproduce one implementation's wording,
    which is a conformance suite testing an accident.
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict), why
        assert actual.get("withheld") == expected["withheld"], why
        assert isinstance(actual.get("why"), str) and actual["why"].strip(), (
            "a suppressed marker must carry a non-empty `why` (#662): a count "
            "withheld without a reason is indistinguishable from a bug"
        )
    else:
        assert actual == expected, why

@pytest.mark.parametrize("check", EXPECTED["checks"],
                         ids=lambda c: f"{c['args']['requester']}@{c['args']['ns']}")
def test_expected_partition(world, check: dict) -> None:
    visible, sealed, private = partition(
        world, check["args"]["requester"], check["args"]["ns"], check["offset"]
    )
    assert visible == check["expect"]["visible"], check["why"]
    assert sealed == check["expect"]["sealed_excluded"], check["why"]
    assert_participation(private, check["expect"]["participation_excluded"], check["why"])


# ── must_not: the invariants no positive check can express ────────────


REQUESTERS = ["band:human", "band:alice", "band:bob", "band:carol"]


def test_a_blind_round_is_never_counted(world) -> None:
    """§8.3. Bob is blinded from alice's PROPOSAL (id 10) at every offset
    after it lands, and it must appear in no counter at any of them."""
    log, tl = world
    head = max(e.id for e in log.envelopes)
    blinded_seen = False
    for offset in range(10, head + 1):
        _, sealed, private = filter_log(log, tl, "band:bob", offset)
        assert 10 not in {e.id for e in sealed}, "a blind round counted as sealed"
        assert 10 not in {e.id for e in private}, (
            "a blind round reported its fill level to a peer who has not "
            "answered — §8.3 cancelled by its own honesty counter"
        )
        visible, _, _ = filter_log(log, tl, "band:bob", offset)
        if 10 not in {e.id for e in visible.envelopes}:
            blinded_seen = True
    assert blinded_seen, "nothing was ever blinded; the invariant proved nothing"


def test_a_missing_grant_is_never_counted(world) -> None:
    """§9.3. carol holds nothing at /vault: both envelopes there are
    withheld from her and neither may be counted."""
    log, tl = world
    head = max(e.id for e in log.envelopes)
    visible, sealed, private = filter_log(log, tl, "band:carol", head)
    vault = {e.id for e in log.envelopes if in_subtree("/vault", e.ns)}
    assert vault, "the fixture lost its ungranted nest"
    assert not (vault & {e.id for e in visible.envelopes})
    assert not (vault & {e.id for e in sealed})
    assert not (vault & {e.id for e in private}), (
        "an ACL denial was counted — a board-wide read now maps the "
        "namespaces the reader holds no grant for"
    )


@pytest.mark.parametrize("requester", REQUESTERS)
def test_the_counters_are_disjoint(world, requester: str) -> None:
    """No envelope is reported twice; the seam branch and the
    participation branch are mutually exclusive in the access path."""
    log, tl = world
    head = max(e.id for e in log.envelopes)
    visible, sealed, private = filter_log(log, tl, requester, head)
    ids = [{e.id for e in group} for group in
           (visible.envelopes, sealed, private)]
    assert not (ids[0] & ids[1]) and not (ids[0] & ids[2])
    assert not (ids[1] & ids[2]), "an envelope counted under two exclusions"


@pytest.mark.parametrize("requester", REQUESTERS)
def test_every_envelope_lands_in_exactly_one_bucket(world, requester: str) -> None:
    """Completeness of the partition itself: served, counted under one of
    the two counters, or silently withheld for one of the two reasons the
    spec names. A verdict that fell through would show up here as an
    envelope in no bucket at all."""
    log, tl = world
    head = max(e.id for e in log.envelopes)
    visible, sealed, private = filter_log(log, tl, requester, head)
    accounted = ({e.id for e in visible.envelopes} | {e.id for e in sealed}
                 | {e.id for e in private})
    for env in log.upto(head):
        if env.id in accounted:
            continue
        v = verdict(log, tl, env, requester, head)
        assert v == "denied", (
            f"envelope {env.id} is in no bucket and its verdict is {v!r} — "
            "a verdict was added without deciding whether it is counted"
        )


# ── §11.x / R34: search is a read surface, and the first with a content
#    filter — so it is the first that could become an oracle ───────────


def _search_partition(world, requester: str, ns: str, q: str, offset: int):
    """What a conforming board serves for a search, and what it must report
    having withheld. Mirrors `partition` above deliberately: the counts come
    from the SAME structural slice, and `q` touches only the visible side."""
    log, tl = world
    visible, sealed, private = filter_log(log, tl, requester, offset)
    in_slice = lambda e: in_subtree(ns, e.ns) and e.id <= offset
    hay = lambda e: e.payload if isinstance(e.payload, str) else json.dumps(e.payload)
    return (
        [e.id for e in visible.envelopes if in_slice(e) and q.lower() in hay(e).lower()],
        len([e for e in sealed if in_slice(e)]),
        # reported shape, as in `partition` above (#388)
        bucketed(len([e for e in private if in_slice(e)])),
    )


@pytest.mark.parametrize("check", EXPECTED["search_checks"],
                         ids=lambda c: f"{c['args']['requester']}@{c['args']['ns']}"
                                       f":{c['args']['q'][:12]}")
def test_expected_search_partition(world, check: dict) -> None:
    visible, sealed, private = _search_partition(
        world, check["args"]["requester"], check["args"]["ns"],
        check["args"]["q"], check["offset"],
    )
    assert visible == check["expect"]["visible"], check["why"]
    assert sealed == check["expect"]["sealed_excluded"], check["why"]
    assert_participation(private, check["expect"]["participation_excluded"], check["why"])


def test_no_search_count_varies_with_the_query(world) -> None:
    """The `must_not` invariant the sampled rows cannot exhaust (R34).

    Fix a requester and a slice; vary the query over strings that match
    withheld content exactly, match nothing, and match everything. The
    counts must be identical across all of them — otherwise each query is
    one bit of a decoder over a mailbox the requester holds no grant for.
    """
    queries = ["", "private", "private 1", "private 2", "zzz-no-such-string",
               "a", "the passphrase", "1"]
    # json-keyed because a bucketed marker is a dict and therefore unhashable
    counts = {
        q: json.dumps(_search_partition(world, "band:carol", "/dm/band:bob", q, 10)[1:],
                      sort_keys=True, default=str)
        for q in queries
    }
    assert len(set(counts.values())) == 1, (
        f"exclusion counts moved with the query: {counts} — the count is a "
        f"function of content the requester may not read"
    )
    # Since #388 the participation half cannot vary with anything, because it
    # is a constant marker rather than a count — so this invariant now holds
    # by construction on that field. It still guards `sealed_excluded`, which
    # is NOT bucketed and remains a number a query could move.
    sealed, participation = _search_partition(world, "band:carol", "/dm/band:bob", "", 10)[1:]
    assert sealed == 0
    assert participation == bucketed(3), "presence, and never the slice's total"
