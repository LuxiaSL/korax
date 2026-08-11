"""The retry curve is ONE contract with two implementations — JOB #1362.

`korax_cli/backoff.py` and `korax_mcp/backoff.py` are siblings, because
these clients share no runtime code by design (`clients/mcp` declares
only mcp/httpx/pydantic; the CLI is written against the protocol doc,
never against the other client). The gate (#1359) required the curve be
*lifted, not imitated* — its stated reason being that "divergence
between two hand-rolled curves is how #22's three loops of work rot".

**This file is how that reason is met**: the same shape as
`test_counter_contract.py`, whose own docstring says a fix applied to
one client "leaves the other manufacturing the same false claim through
a different door". The expectations below are LITERALS, duplicated in
the sibling file on purpose — change one client's curve and its test
goes red against numbers the other still meets.

The deterministic half is asserted exactly (`fraction=NO_JITTER`); the
jitter is asserted as a PROPERTY, not against a seeded RNG, because a
contract that depended on Mersenne Twister's internals would be pinning
CPython rather than pinning the curve.
"""

from __future__ import annotations

import random

import pytest

from korax_mcp.backoff import (
    DEFAULT_BASE,
    DEFAULT_MAX,
    DEFAULT_NOTICE_WAIT,
    JITTER_FRACTION,
    NO_JITTER,
    escalating_delay,
    jittered,
    notice_delay,
)

#: The curve, with jitter off. `min(base * failures, cap)` — `cmd_watch`'s
#: own numbers, preserved exactly on the lift so the read path's behaviour
#: did not change when it started calling shared code.
ESCALATING = {
    0: 0.0,
    1: 5.0,
    2: 10.0,
    3: 15.0,
    4: 20.0,
    11: 55.0,
    12: 60.0,
    13: 60.0,   # saturated
    100: 60.0,
}

#: `retry_after_s` in every shape a board might send it.
NOTICE = [
    (30, 30.0),
    (0.5, 0.5),
    (0, 0.0),
    (None, 30.0),        # absent -> the default wait
    ("soon", 30.0),      # a string is not a number
    (True, 30.0),        # bool is an int; `True` is not one second
    ([], 30.0),
]

CONSTANTS = {
    "DEFAULT_BASE": 5.0,
    "DEFAULT_MAX": 60.0,
    "DEFAULT_NOTICE_WAIT": 30.0,
    "JITTER_FRACTION": 0.5,
    "NO_JITTER": 0.0,
}


def test_the_constants_are_the_contract() -> None:
    assert CONSTANTS == {
        "DEFAULT_BASE": DEFAULT_BASE,
        "DEFAULT_MAX": DEFAULT_MAX,
        "DEFAULT_NOTICE_WAIT": DEFAULT_NOTICE_WAIT,
        "JITTER_FRACTION": JITTER_FRACTION,
        "NO_JITTER": NO_JITTER,
    }


@pytest.mark.parametrize("failures,expected", sorted(ESCALATING.items()))
def test_the_escalating_curve(failures: int, expected: float) -> None:
    assert escalating_delay(failures, fraction=NO_JITTER) == expected


@pytest.mark.parametrize("sent,expected", NOTICE)
def test_the_notice_wait(sent: object, expected: float) -> None:
    """A board that sends nonsense must still produce a wait: this is the
    one code path whose job is surviving a board that is misbehaving."""
    assert notice_delay(sent, fraction=NO_JITTER) == expected


def test_jitter_is_additive_never_early() -> None:
    """The goodbye page's number is a FLOOR the board asked us to respect.

    A symmetric jitter would let a client re-poll before the interval it
    was advised to wait — arriving while the restart it was warned about
    is still running. So the spread only ever goes up.
    """
    rng = random.Random(1234)
    for _ in range(500):
        out = jittered(30.0, rng=rng)
        assert 30.0 <= out <= 45.0


def test_the_ceiling_is_applied_before_the_jitter() -> None:
    """At the cap every client would otherwise wait exactly `cap` and
    re-synchronize on it — the same herd by a slower route (#1370). So a
    saturated curve is still spread, which means it can exceed `cap`."""
    rng = random.Random(99)
    outs = [escalating_delay(50, rng=rng) for _ in range(200)]
    assert all(out >= DEFAULT_MAX for out in outs)
    assert max(outs) > DEFAULT_MAX
    assert max(outs) <= DEFAULT_MAX * (1 + JITTER_FRACTION)


def test_a_zero_delay_stays_zero() -> None:
    """`retry_after_s: 0` means "now"; jitter must not invent a wait."""
    assert jittered(0.0) == 0.0
    assert escalating_delay(0) == 0.0
