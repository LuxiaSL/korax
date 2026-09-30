"""The policy lookups memoise on the entries in force, not the offset.

`PolicyTimeline.policy_at` and `effective_band` are called on every
visibility check, at the board's head. They are memoised on (arguments,
number of entries in force), which is sound only if the answer depends on
the offset through that number alone and the memo is dropped whenever an
entry enters. These tests hold both halves: every memoised answer equals
the rule computed afresh, across every offset of the conformance log and
across appends that bring a policy into force.
"""

from __future__ import annotations

import pytest

from korax import PROTO
from korax.board import Board
from korax.log import Log
from korax.policy import PolicyTimeline
from korax.seed import seed_board
from korax.store import Store


def _namespaces(log: Log) -> list[str]:
    seen = sorted({e.ns for e in log.envelopes})
    return seen + ["/", "/nowhere/at/all"]


def _identities(log: Log) -> list[str]:
    return sorted({e.author for e in log.envelopes}) + ["band:*"]


def test_memoised_answers_equal_the_rule_at_every_offset(full_log: Log) -> None:
    tl = PolicyTimeline(full_log)
    namespaces = _namespaces(full_log)
    identities = _identities(full_log)
    for env in full_log.envelopes:
        off = env.id
        for ns in namespaces:
            try:
                want = tl._policy_at_uncached(ns, off)
            except LookupError:
                with pytest.raises(LookupError):
                    tl.policy_at(ns, off)
                continue
            assert tl.policy_at(ns, off) == want
            assert tl.policy_at(ns, off) == want  # the memo hit, too
            for ident in identities:
                band = tl._effective_band_uncached(ident, ns, off)
                assert tl.effective_band(ident, ns, off) == band
                assert tl.effective_band(ident, ns, off) == band


def test_the_memo_is_dropped_when_a_policy_enters_force() -> None:
    store = Store(":memory:")
    operator, _tok = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    worker, _t = store.create_identity("worker")

    before = board.timeline.effective_band(worker, "/proj/x", board.head)
    board.append(operator, {
        "proto": PROTO, "grade": "n/a", "refs": [], "ext": {}, "author": operator,
        "ns": "/", "type": "POLICY", "payload": {"grants": [
            {"identity": operator, "ns": "/**", "band": "human"},
            {"identity": worker, "ns": "/proj/**", "band": "desk"},
        ]},
    })
    after = board.timeline.effective_band(worker, "/proj/x", board.head)
    assert after != before
    assert after == board.timeline._effective_band_uncached(worker, "/proj/x", board.head)
