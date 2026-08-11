"""The retry curve — one implementation, two callers (JOB #1362, D5).

**Lifted from `cmd_watch`, not copied.** The read path had spent three
loops of work getting this right (#22, #914/#917, #691) and the write
path had none of it (#1205); a second hand-rolled curve beside the first
is how the two rot apart, so `cmd_watch` now calls this module and so
does the write path's retry helper.

Two waits live here because the board asks for waiting in two different
voices, and they are not the same wait:

* `escalating_delay` — the board did not answer. Nobody told us anything,
  so the curve grows with consecutive failures and stops at a ceiling.
* `notice_delay` — the board DID tell us, politely, in a goodbye page
  carrying `retry_after_s` (§11). That is advice with a number on it.

**Both jitter, and the goodbye path is the one that needed it most.**
`cmd_watch` carried this comment against its `retry_after_s` sleep:

    Back off AT LEAST this long, never exactly: a restart that runs long
    would otherwise turn every parked watch into a thundering re-arm at
    one instant.

The comment was right and the line beneath it slept exactly `delay` —
`grep -rn "random\\|jitter"` across both clients returned nothing, so
this board has never had the property its own source claimed. Filed as
#1370 (WARN #1369) rather than fixed in place, because changing
`cmd_watch`'s live behaviour is not JOB #1362's authorization; what this
module does is refuse to LIFT a curve whose contract its code did not
meet. The jitter here is new code meeting the old comment's promise.

The herd is real and it is measurable: seven watches were parked on this
board when #1369 was written, and one goodbye page hands all of them the
same `retry_after_s` in the same instant, by construction.
"""

from __future__ import annotations

import random

#: Seconds added per consecutive failure. `cmd_watch`'s own default,
#: preserved on the lift so the read path's behaviour is unchanged.
DEFAULT_BASE = 5.0
#: Ceiling on the escalating wait. Also `cmd_watch`'s.
DEFAULT_MAX = 60.0
#: §11 — what to wait when a goodbye page carries no usable number.
DEFAULT_NOTICE_WAIT = 30.0
#: Jitter is added ON TOP of the wait, never subtracted from it: the
#: goodbye page's number is a floor the board asked us to respect, so
#: spreading the herd must never mean answering EARLIER than advised.
JITTER_FRACTION = 0.5


def jittered(delay: float, *, fraction: float = JITTER_FRACTION,
             rng: random.Random | None = None) -> float:
    """`delay` plus a random slice of it, never less than `delay`.

    Additive on purpose. A symmetric jitter (±) would let a client
    re-poll before the interval the board asked for, which on the
    goodbye-page path means arriving while the restart it was warned
    about is still running.

    `rng` is injectable so a test can assert the curve rather than
    assert that a random number is between two other numbers.
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

    `min(base * failures, cap)`, jittered — the curve `cmd_watch` has
    always had, with the spread it always said it wanted. The ceiling is
    applied BEFORE the jitter, so the jitter is what carries a saturated
    curve past `cap`: at the ceiling every client is otherwise waiting
    exactly `cap` and re-synchronizes on it, which is the same herd by a
    slower route (#1370's second half).
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

    Takes `object` rather than `float` deliberately: the caller reads
    this straight out of a `system_notice` dict that arrived over the
    wire, and a board that sends `null`, a string, or nothing at all
    must produce a wait rather than a `TypeError` on the one code path
    whose whole job is surviving a board that is misbehaving.
    """
    delay = retry_after_s if isinstance(retry_after_s, (int, float)) else default
    if isinstance(delay, bool):  # bool is an int; a `True` here is not 1 second
        delay = default
    return jittered(float(delay), fraction=fraction, rng=rng)


#: `fraction=NO_JITTER` is the read path's setting, and it is a placeholder
#: for a ruling rather than a preference.
#:
#: JOB #1362 authorizes client retry on the WRITE path. `cmd_watch` calls
#: this module because D5 says lift rather than imitate — but lifting must
#: not smuggle in a behaviour change to the mechanism every band's session
#: depends on, so the read path keeps the exact sleeps it has always had
#: and the write path gets the spread. That leaves this board's herd
#: (#1369/#1370) unfixed ON PURPOSE and reduces the fix, once ruled, to
#: deleting the two `fraction=NO_JITTER` arguments at the `cmd_watch` call
#: sites. The wrong shape here would be a curve that behaves differently
#: depending on who calls it and does not say why.
NO_JITTER = 0.0
