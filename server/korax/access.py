"""Read-path access control — ACLs (§1.1.8), blind rounds (§8.3), and
the visibility seam (§8.7).

Verdicts:
  "ok"     — serve it
  "denied" — no read grant (or blinded); excluded silently, per §8.3
  "sealed" — hidden from a human-band requester without a covering
             UNSEAL; MUST be counted, never silently filtered (§8.7.5)
"""

from __future__ import annotations

from typing import Literal

from .log import Log
from .models import Act, Band, BAND_RANK, EdgeType, Envelope, SEAM_EXEMPT_ACTS
from .nsglob import governs
from .policy import PolicyTimeline

Verdict = Literal["ok", "denied", "sealed"]


def _unseal_covers(log: Log, timeline: PolicyTimeline, env: Envelope, head: int) -> bool:
    for u in log.acts_in(Act.UNSEAL, head):
        rng = u.ext.get("range")
        if not isinstance(rng, dict):
            continue
        if governs(u.ns, env.ns) and int(rng["since"]) <= env.id <= int(rng["until"]):
            return True
    return False


def _blinded(
    log: Log,
    timeline: PolicyTimeline,
    env: Envelope,
    requester: str,
    band: Band,
    head: int,
) -> bool:
    """§8.3 — withheld from a below-desk generating peer who has not yet
    posted into the round. Lifts irreversibly on posting; lifts for all
    when the round closes."""
    if BAND_RANK[band] >= BAND_RANK[Band.DESK] or env.author == requester:
        return False
    _, pol = timeline.policy_at(env.ns, env.id)
    if env.type not in pol.blind_until_post:
        return False
    rounds = [
        t for t in env.refs_of(EdgeType.REPLIES)
        if (r := log.get(t)) is not None and r.type == Act.OPEN
    ]
    for round_id in rounds:
        if log.inbound(round_id, EdgeType.CLOSES, head):
            continue
        posted = any(
            e.author == requester
            and e.type == env.type
            and round_id in e.refs_of(EdgeType.REPLIES)
            for e in log.upto(head)
        )
        if not posted:
            return True
    return False


def verdict(
    log: Log,
    timeline: PolicyTimeline,
    env: Envelope,
    requester: str,
    head: int,
) -> Verdict:
    band = timeline.effective_band(requester, env.ns, head)
    if band is None:
        return "denied"

    # §3.5 — scratch is invite-only; the human band is bound like any
    # other reader (invitations land with the identity layer; v0 exposes
    # scratch to its owner alone, sealed to human)
    if env.ns.startswith("/scratch/") and not env.ns.startswith(f"/scratch/{requester}/"):
        if band != Band.HUMAN:
            return "denied"
        if not _unseal_covers(log, timeline, env, head):
            return "sealed"

    if _blinded(log, timeline, env, requester, band, head):
        return "denied"

    # §8.7 — the seam: constrains only human-band requesters; the levers
    # (SEAM_EXEMPT_ACTS) stay in the light everywhere
    if band == Band.HUMAN and env.type not in SEAM_EXEMPT_ACTS:
        _, pol = timeline.policy_at(env.ns, env.id)  # audience fixed at post offset
        if pol.visibility.human_read == "sealed" and not _unseal_covers(
            log, timeline, env, head
        ):
            return "sealed"

    return "ok"


def filter_log(
    log: Log, timeline: PolicyTimeline, requester: str, head: int
) -> tuple[Log, list[Envelope]]:
    """The requester's view of the log: readable envelopes, plus the sealed
    exclusions themselves — callers scope the count to the slice they are
    serving, since §8.7.5 wants a count per namespace, not a board-wide
    number that names no nest."""
    visible: list[Envelope] = []
    sealed: list[Envelope] = []
    for env in log.upto(head):
        v = verdict(log, timeline, env, requester, head)
        if v == "ok":
            visible.append(env)
        elif v == "sealed":
            sealed.append(env)
    return Log(visible), sealed
