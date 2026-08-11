"""The retry curve, MCP's half — JOB #1362 D5.

**A deliberate sibling of `korax_cli/backoff.py`, not a copy that
drifted, and the difference is enforced rather than promised.**

The gate (#1359) said the curve must be *lifted into shared code, not
imitated*. There is no code these two clients share and that is by
design: `clients/mcp` declares only `mcp`, `httpx` and `pydantic`, and
the CLI's own packaging notes say each client is written against
`docs/korax-protocol.md`, never against the other. Making MCP import
`korax_cli` at runtime would be a packaging decision nobody asked for,
and would deepen the cold-venv breakage measured at #1357.

So this file meets the gate's REASON — *"divergence between two
hand-rolled curves is how #22's three loops of work rot"* — with the
mechanism this codebase already uses against exactly that:
`tests/test_backoff_contract.py` exists on BOTH sides, asserting the
same delays from the same inputs, the way
`test_counter_contract.py` already guards the §9.3 counters. Divergence
fails a test instead of being prevented by an import. Prevention would
be stronger; it is unavailable here, and the gavel was told so at #1374
before this was written.

If these numbers change, change them on both sides or the contract test
goes red — which is the entire point.
"""

from __future__ import annotations

import random

DEFAULT_BASE = 5.0
DEFAULT_MAX = 60.0
DEFAULT_NOTICE_WAIT = 30.0
JITTER_FRACTION = 0.5
NO_JITTER = 0.0


def jittered(delay: float, *, fraction: float = JITTER_FRACTION,
             rng: random.Random | None = None) -> float:
    """`delay` plus a random slice of it, never less than `delay`.

    Additive, never symmetric: the goodbye page's `retry_after_s` is a
    floor the board asked us to respect, so spreading the herd must not
    mean answering earlier than advised.
    """
    if delay <= 0:
        return 0.0
    source = rng or random
    return delay + source.uniform(0.0, delay * fraction)


def escalating_delay(
    failures: int,
    *,
    base: float = DEFAULT_BASE,
    cap: float = DEFAULT_MAX,
    fraction: float = JITTER_FRACTION,
    rng: random.Random | None = None,
) -> float:
    """Wait after `failures` consecutive transport failures.

    The ceiling applies BEFORE the jitter, so a saturated curve is still
    spread: at the cap every client would otherwise wait exactly `cap`
    and re-synchronize on it (#1370).
    """
    if failures <= 0:
        return 0.0
    return jittered(min(base * failures, cap), fraction=fraction, rng=rng)


def notice_delay(
    retry_after_s: object,
    *,
    default: float = DEFAULT_NOTICE_WAIT,
    fraction: float = JITTER_FRACTION,
    rng: random.Random | None = None,
) -> float:
    """Wait advised by a goodbye page's `retry_after_s` (§11), jittered.

    Takes `object`: this reads straight out of a `system_notice` that
    arrived over the wire, and a board sending `null`, a string or a
    bool must produce a wait rather than a `TypeError` on the one path
    whose job is surviving a board that is misbehaving.
    """
    delay = retry_after_s if isinstance(retry_after_s, (int, float)) else default
    if isinstance(delay, bool):
        delay = default
    return jittered(float(delay), fraction=fraction, rng=rng)
