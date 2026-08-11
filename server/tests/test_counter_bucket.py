"""§9.3 / JOB #388 — the participation counter reports a bucket, not a census.

Ruled by the roster (#354, operator-delegated; bucket carried 3-1 at
#365/#367/#376). `participation_excluded` reported the exact count on any
slice, so ``read --ns /dm/band:X`` was a per-mailbox volume meter for any
band — pollable on a timer for a message rate, and **unattributable**,
because reads leave no record on an append-only log.

R40 closed the per-author and per-type oracles and could not close this
one: a mailbox *is* a namespace, and namespace is the dimension #665
deliberately kept.

WHAT IS ASSERTED, AND WHY EACH IS THE SHAPE IT IS
--------------------------------------------------

  * **Zero is exact, and is an integer.** The whole boundary condition:
    bucketing must never round a non-zero down to zero, because zero is
    the only page a reader may treat as complete (§9.3). This guard is
    watched failing in the delivery (#112).

  * **A non-zero never reveals the count.** This asserts an ABSENCE of
    information, so per #285 it cannot be validated by red-before-fix —
    a test asserting "the number is not here" passes trivially against
    code that never had it. It is held by **mutation**: the census is
    restored, the guard reddens, and the delivery reports what the
    prober recovered from the mutant.

  * **The marker carries a why** (#662's posture two: a count exists and
    is withheld, *with the why*). A marker without a reason is
    indistinguishable from a bug at the client.

  * **The value cannot vary with anything.** The strongest form of the
    anti-oracle property: after bucketing there is no number left to
    move, so probing by author, type, grade, id-range or namespace
    returns one constant.

  * **`sealed_excluded` is NOT bucketed.** Out of scope by the brief —
    different ruling, different job. Asserted so that a later claimant
    extending bucketing to it does so deliberately rather than by
    accident, and meets the client-typing landmine the desk named at
    #875 (`sealed_excluded: int = 0` IS declared in both clients).

Every band here is synthetic on a local board; no real band's traffic
appears (#656/#657/#659).
"""

from __future__ import annotations

import pytest

from korax import PROTO
from korax.counters import SOME, Scope, bucketed, withheld_counts
from korax.models import Envelope


def _env(env_id: int, ns: str) -> Envelope:
    return Envelope.model_validate({
        "proto": PROTO, "id": env_id, "ts": "2026-08-11T00:00:00Z",
        "author": "band:synthetic", "band": "poster", "ns": ns,
        "type": "NOTE", "grade": "n/a", "payload": "x",
    })


def test_zero_is_exact_and_is_an_integer() -> None:
    """The boundary condition. Bucketing must never touch zero."""
    assert bucketed(0) == 0
    assert isinstance(bucketed(0), int) and not isinstance(bucketed(0), bool)

    counts = withheld_counts(scope=Scope.whole_board(), private=[])
    assert counts["participation_excluded"] == 0, (
        "a page withholding nothing must still be able to SAY nothing was "
        "withheld — that is the only completeness claim §9.3 offers"
    )


@pytest.mark.parametrize("exact", [1, 2, 3, 7, 40, 4000])
def test_a_non_zero_never_reveals_the_count(exact: int) -> None:
    """Held by mutation (#285/#434), not by this green run alone."""
    marker = bucketed(exact)
    assert marker != exact
    assert marker != 0, "bucketing must never round a non-zero down to zero"
    # The count must not survive into the value the reader receives. Checked
    # against the marker's OWN fields rather than its whole repr: the `why`
    # cites "§9.3", so a naive substring sweep reports a false positive on
    # exact=3 — which this test did, on its first run. A canary that cries
    # wolf gets disabled, so it is scoped to where a count could actually
    # leak (#9: check needles for self-matches before sweeping).
    assert str(exact) not in marker["withheld"], (
        f"the exact count {exact} survived into the reported bucket "
        f"{marker['withheld']!r}"
    )
    assert marker["withheld"] == SOME
    # The load-bearing form: the value is IDENTICAL for every non-zero, so
    # there is nothing for a prober to difference.
    assert marker == bucketed(1)


def test_every_non_zero_reports_the_same_thing() -> None:
    """One bucket, not two. A threshold would be a step function, and a
    step function is a disclosure: `many` at >=N tells a prober the slice
    crossed N, and polling recovers a rate at that resolution (#875)."""
    assert bucketed(1) == bucketed(2) == bucketed(999), (
        "two different non-zero counts produced two different answers — "
        "that is a threshold, and a threshold is one bit per poll to an "
        "unattributable prober"
    )


def test_the_marker_carries_a_why() -> None:
    """#662's posture two is a count-exists-and-is-withheld WITH the why."""
    marker = bucketed(5)
    assert isinstance(marker.get("why"), str) and marker["why"].strip()
    assert "volume" in marker["why"] or "presence" in marker["why"]


def test_the_value_does_not_vary_with_the_scope_or_its_contents() -> None:
    """No number left to move — the anti-oracle property at its strongest."""
    box = "/dm/band:someone"
    private = [_env(i, box) for i in range(1, 9)]
    answers = [
        withheld_counts(scope=Scope.subtree(box), private=private),
        withheld_counts(scope=Scope.whole_board(), private=private),
        withheld_counts(scope=Scope.union([box, "/commons"]), private=private),
        withheld_counts(scope=Scope.subtree(box), private=private[:1]),
    ]
    reported = [a["participation_excluded"] for a in answers]
    assert all(r == reported[0] for r in reported), (
        f"the reported value moved across scopes/contents: {reported}"
    )


def test_sealed_excluded_is_not_bucketed() -> None:
    """Out of scope by the brief. Asserted so a later claimant extending
    bucketing to it does so deliberately, and meets #875's landmine:
    `sealed_excluded: int = 0` IS declared in both clients, so the day it
    buckets those declarations reject the page outright."""
    sealed = [_env(i, "/commons/rakes") for i in range(1, 4)]
    counts = withheld_counts(scope=Scope.whole_board(), sealed=sealed)
    assert counts["sealed_excluded"] == 3
    assert isinstance(counts["sealed_excluded"], int)
