"""Read-side retention — korax-protocol.md §8.2.

`retention.mode: "rotate"` sets what a nest's *default* views show. It
never deletes: the log is append-only (§1.1.1), a rotated envelope keeps
its id, still anchors edges, and still resolves by direct address. What
rotation bounds is discovery, not access — which is exactly why the
horizon is governed by the policy in force at READ time, unlike the
visibility seam (§8.7), whose audience is fixed at each envelope's own
post offset. The seam fixes audience because disclosure is irreversible;
rotation carries no such promise, because direct address has already
conceded every rotated envelope to anyone who names its id.

The cutoff derives from log time, never wall clock: the ts of the
envelope at the evaluation offset, minus the horizon. Same log, same
offset, same output (§10) — and a fixture that passes today still passes
next month.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .log import Log
from .models import Act, Envelope
from .policy import PolicyTimeline

_DURATION = re.compile(r"^P(\d+)D$")

# §8.2 — an audit trail with a horizon is not an audit trail. Deliberately
# NOT SEAM_EXEMPT_ACTS (models.py), which is this set plus JOB: the two
# lists answer different questions. The seam list is "what stays lit for a
# human who cannot see the room"; this one is "what the record cannot
# afford to forget". JOB is the deliberate difference — a stale job offer
# in a rotating nest is exactly what should fall out of default view.
# Fusing them is how a knob goes unenforced: one list moves, both change.
ROTATION_EXEMPT_ACTS = frozenset({Act.POLICY, Act.STAMP, Act.UNSEAL, Act.PIN})

# The pierce token accepted by /read and /wait (§9). Views never pierce.
PIERCE = "none"


def parse_horizon(horizon: str) -> timedelta:
    m = _DURATION.match(horizon)
    if not m:
        raise ValueError(f"unsupported horizon {horizon!r} (v0 supports PnD)")
    return timedelta(days=int(m.group(1)))


def eval_ts_at(log: Log, offset: int) -> datetime | None:
    """Evaluation time for a read at `offset` — the ts of that envelope,
    never wall clock. None when the offset names no envelope (an empty
    board, or an anchor the requester cannot see), in which case nothing
    rotates: a horizon we cannot place in time is one we must not apply."""
    env = log.get(offset)
    return env.ts if env is not None else None


def is_rotated(
    timeline: PolicyTimeline,
    env: Envelope,
    offset: int,
    eval_ts: datetime | None,
) -> bool:
    """True when `env` falls outside its nest's horizon, judged against the
    retention policy in force at the read offset.

    The envelope at the evaluation offset can never rotate: its ts is
    eval_ts, so no non-negative horizon excludes it. Reductions may
    therefore rely on their anchor surviving this filter.
    """
    if eval_ts is None or env.type in ROTATION_EXEMPT_ACTS:
        return False
    try:
        _, pol = timeline.policy_at(env.ns, offset)  # §8.1 — read-time policy
    except LookupError:
        return False  # no policy governs it; nothing declared, nothing applied
    if pol.retention.mode != "rotate" or not pol.retention.horizon:
        return False
    try:
        window = parse_horizon(pol.retention.horizon)
    except ValueError:
        # A horizon this build cannot parse is not licence to hide history.
        return False
    return env.ts < eval_ts - window


def split(
    clock: Log,
    timeline: PolicyTimeline,
    envs: list[Envelope],
    offset: int,
) -> tuple[list[Envelope], list[Envelope]]:
    """Partition `envs` into (kept, rotated) at `offset`.

    `clock` supplies eval_ts and is the board's own log, not the
    requester's filtered view: the cutoff is a property of the board's
    timeline, so two identities reading the same nest at the same offset
    must get the same horizon even when one of them cannot see the
    envelope the offset names.

    Callers scope the rotated count to the slice they are serving, the
    same way §8.7.5 scopes `sealed_excluded` — a board-wide number names
    no nest.
    """
    eval_ts = eval_ts_at(clock, offset)
    kept: list[Envelope] = []
    rotated: list[Envelope] = []
    for env in envs:
        (rotated if is_rotated(timeline, env, offset, eval_ts) else kept).append(env)
    return kept, rotated


def project(
    clock: Log, timeline: PolicyTimeline, log: Log, offset: int
) -> tuple[Log, list[Envelope]]:
    """The rotate-filtered log a discovery reduction sees, and the
    envelopes the horizon withheld — returned whole, not counted, so the
    caller can scope the count to the slice it is serving. Edge-following
    and direct-address paths never call this: rotation bounds discovery,
    not reference.

    The envelope at `offset` survives by construction (see is_rotated), so
    a reduction anchoring on `log.get(offset)` keeps its anchor."""
    kept, rotated = split(clock, timeline, log.envelopes, offset)
    return Log(kept), rotated
