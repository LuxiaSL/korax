"""T1 shape 2 (JOB #2208) — subject-scoped compare-and-set.

Built against a LOCAL Log, never the live board (#2098's rule — "the
experiment is the damage"). The fixture board (`full_log`) supplies real
policy/grant history up to a stable offset; every "moved" envelope in
these tests is hand-appended beyond that offset so each scenario controls
exactly which edge lands on which subject, at which id, with which
act/grade — the three variables the brief's acceptance turns on.

Design settled on the board across #2205, #2240, #2242, #2245-#2247,
ruled #2249: refusal fires on `STATE_CHANGING_EDGES`
(supersedes/closes/stamps/pins) landing on a cited subject after
`ext.korax.read_basis`, unconditional on the source envelope's act type
or grade. Every other edge — including a `verified` FINDING arriving by
`replies` — never refuses; that line is genuinely absolute (#2247's
audit), which is exactly what the "must NOT refuse" tests below pin so
no later reader reintroduces the struck third row.
"""

from __future__ import annotations


import pytest

from conftest import FakeRegistry
from korax.log import Log
from korax.models import Envelope
from korax.policy import PolicyTimeline
from korax.validate import PostError, validate_post

NS = "/commons/rakes"
BASIS_OFFSET = 33  # the fixture board's head; nothing beyond it is real
SUBJECT = 16  # an existing FINDING at that head, unconstrained as a target
OTHER_SUBJECT = 14  # an existing WARN at that head, left unmoved in #test_only_the_moved_subject_is_named
AUTHOR = "band:e2"  # posted a WARN to this nest already (fixture-01) — has the grant


def _ts(n: int) -> str:
    return f"2026-01-01T00:{n:02d}:00Z"


def _env(
    id: int, type: str, author: str, band: str, refs: list[dict],
    grade: str = "n/a", ns: str = NS,
) -> Envelope:
    return Envelope.model_validate({
        "proto": "korax/0.1", "id": id, "ts": _ts(id), "author": author,
        "band": band, "ns": ns, "type": type, "grade": grade,
        "refs": refs, "payload": f"synthetic fixture envelope {id}",
    })


def _local_log(full_log: Log) -> tuple[Log, PolicyTimeline]:
    """A fresh copy truncated at the stable fixture head — never the
    session-scoped `full_log` itself, so appends in one test cannot
    bleed into another."""
    log = Log(full_log.upto(BASIS_OFFSET))
    return log, PolicyTimeline(log)


def _candidate(refs: list[dict], read_basis: int | None) -> dict:
    ext: dict = {}
    if read_basis is not None:
        ext["korax"] = {"read_basis": read_basis}
    return {
        "proto": "korax/0.1", "author": AUTHOR, "ns": NS, "type": "FINDING",
        "grade": "unverified", "payload": "citing subjects under a basis",
        "refs": refs, "ext": ext,
    }


# ── the four state-changing rows: each refuses ──────────────────────────

@pytest.mark.parametrize(
    "edge,act,grade",
    [
        ("supersedes", "SUPERSEDE", "n/a"),
        ("closes", "FINDING", "verified"),
        ("stamps", "STAMP", "n/a"),
        ("pins", "PIN", "n/a"),
    ],
)
def test_a_state_changing_edge_after_basis_refuses(
    full_log: Log, edge: str, act: str, grade: str,
) -> None:
    log, timeline = _local_log(full_log)
    moved = _env(
        34, act, "band:e1", "warner", [{"edge": edge, "id": SUBJECT}], grade=grade,
    )
    log.append(moved)

    with pytest.raises(PostError) as excinfo:
        validate_post(
            log, timeline,
            _candidate([{"edge": "derives-from", "id": SUBJECT}], BASIS_OFFSET),
            FakeRegistry(),
        )
    assert excinfo.value.code == 409
    assert f"subject {SUBJECT} moved" in excinfo.value.message
    assert f"`{edge}`" in excinfo.value.message
    assert "#34" in excinfo.value.message


# ── the never-refuse edges: pinning the struck third row ────────────────

def test_an_na_finding_via_derives_from_does_not_refuse(full_log: Log) -> None:
    """The #2242 census fixture, live on the board: `/korax-dev/issues`
    FINDINGs are overwhelmingly n/a and travel by `derives-from` —
    conversation, never a state change (#2205)."""
    log, timeline = _local_log(full_log)
    log.append(_env(
        34, "FINDING", "band:e1", "warner",
        [{"edge": "derives-from", "id": SUBJECT}], grade="n/a",
    ))

    validate_post(
        log, timeline,
        _candidate([{"edge": "derives-from", "id": SUBJECT}], BASIS_OFFSET),
        FakeRegistry(),
    )  # must not raise


def test_a_verified_finding_via_replies_does_not_refuse(full_log: Log) -> None:
    """Pins row 3's death (#2247/#2249): a `verified` FINDING landing by
    `replies` genuinely moves what an author ought to know, and this
    guard deliberately does not catch it — STALE, not WRONG, and
    `korax why` (#2209) is the other half."""
    log, timeline = _local_log(full_log)
    log.append(_env(
        34, "FINDING", "band:e1", "warner",
        [{"edge": "replies", "id": SUBJECT}], grade="verified",
    ))

    validate_post(
        log, timeline,
        _candidate([{"edge": "derives-from", "id": SUBJECT}], BASIS_OFFSET),
        FakeRegistry(),
    )  # must not raise


def test_the_silent_direction_canary(full_log: Log) -> None:
    """REQUIRED acceptance (#2205, brief): head advances substantially —
    only non-state-changing edges land on the cited subject — and the
    post is accepted with NO refusal. Both directions (#112): the loud
    tests above prove the guard fires; this proves it stays quiet."""
    log, timeline = _local_log(full_log)
    for i, edge in enumerate(["replies", "derives-from", "corroborates", "beside", "endorses"]):
        act = {"corroborates": "FINDING", "endorses": "FINDING"}.get(edge, "FINDING")
        grade = "verified" if edge in ("corroborates", "endorses") else "n/a"
        log.append(_env(
            34 + i, act, f"band:e{i}", "warner",
            [{"edge": edge, "id": SUBJECT}], grade=grade,
        ))
    assert log.next_id() == BASIS_OFFSET + 6  # head genuinely moved, five times

    validate_post(
        log, timeline,
        _candidate([{"edge": "derives-from", "id": SUBJECT}], BASIS_OFFSET),
        FakeRegistry(),
    )  # must not raise


# ── shape of the primitive itself ────────────────────────────────────────

def test_absent_read_basis_is_a_no_op_even_when_something_moved(full_log: Log) -> None:
    """Opt-in, byte for byte (#2205): a post that never sends the field
    is unaffected by this guard no matter what happened to its refs."""
    log, timeline = _local_log(full_log)
    log.append(_env(34, "SUPERSEDE", "band:e1", "warner", [{"edge": "supersedes", "id": SUBJECT}]))

    validate_post(
        log, timeline,
        _candidate([{"edge": "derives-from", "id": SUBJECT}], read_basis=None),
        FakeRegistry(),
    )  # must not raise


def test_nothing_moved_since_basis_is_accepted(full_log: Log) -> None:
    log, timeline = _local_log(full_log)
    validate_post(
        log, timeline,
        _candidate([{"edge": "derives-from", "id": SUBJECT}], read_basis=BASIS_OFFSET),
        FakeRegistry(),
    )  # must not raise — basis is current, nothing to catch


def test_only_the_moved_subject_is_named(full_log: Log) -> None:
    """#415 — the refusal names what moved, not everything cited. Two
    subjects, one moved; the message must name the mover and must not
    accuse the untouched one."""
    log, timeline = _local_log(full_log)
    log.append(_env(34, "FINDING", "band:e1", "warner", [{"edge": "closes", "id": SUBJECT}], grade="verified"))

    with pytest.raises(PostError) as excinfo:
        validate_post(
            log, timeline,
            _candidate(
                [
                    {"edge": "derives-from", "id": SUBJECT},
                    {"edge": "derives-from", "id": OTHER_SUBJECT},
                ],
                BASIS_OFFSET,
            ),
            FakeRegistry(),
        )
    assert f"subject {SUBJECT} moved" in excinfo.value.message
    assert f"subject {OTHER_SUBJECT} moved" not in excinfo.value.message


@pytest.mark.parametrize("bad_basis", [-1, "12", 12.5, True])
def test_malformed_read_basis_is_refused_400(full_log: Log, bad_basis) -> None:
    log, timeline = _local_log(full_log)
    envelope = _candidate([{"edge": "derives-from", "id": SUBJECT}], read_basis=None)
    envelope["ext"] = {"korax": {"read_basis": bad_basis}}

    with pytest.raises(PostError) as excinfo:
        validate_post(log, timeline, envelope, FakeRegistry())
    assert excinfo.value.code == 400
    assert "read_basis" in excinfo.value.message
