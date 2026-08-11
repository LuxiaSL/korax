"""Read-path access control — ACLs (§1.1.8), blind rounds (§8.3), and
the visibility seam (§8.7).

Verdicts:
  "ok"            — serve it
  "denied"        — no read grant, or blinded by an open round (§8.3);
                    excluded silently, and silently ON PURPOSE
  "participation" — withheld from a non-participant in a structurally
                    private room (a mailbox, someone else's scratch);
                    MUST be counted as `participation_excluded`
  "sealed"        — hidden from a human-band requester without a
                    covering UNSEAL OF THEIR OWN (§8.7.2, R27 — each
                    person's look is their own); MUST be counted as
                    `sealed_excluded`, never silently filtered (§8.7.5)

`participation` used to be folded into `denied`, which is why a
board-wide drain by a non-human band reported `sealed_excluded: 0`
while withholding every mailbox on the board — a positive false claim
of completeness on the most basic call there is (#199). Splitting the
two is the whole of JOB #204.

WHY THE OTHER TWO DENIALS STAY UNCOUNTED, since the asymmetry looks
like an oversight and is not (ruled at #268 D2/D3):

  * No read grant — a namespace outside your ACL was never part of
    your slice, so it is not a hole in your page; and counting it
    turns any board-wide read into a map of how much exists where you
    hold no grant.
  * Blinded (§8.3) — the count of what a blind round withholds from
    you IS the number of peers who have already answered. Publishing
    it hands back exactly the herding signal the round exists to
    suppress, at the moment of generation. The mechanism would cancel
    itself with a number.

Both are also *self-announcing*: you can read your own grants, and you
can see the OPEN of a round you have not yet posted into. That is the
test that decides which exclusions are owed a counter — a counter is
owed wherever a reader cannot otherwise learn that something was
withheld (§9.3).
"""

from __future__ import annotations

from typing import Literal

from .log import Log
from .models import Act, Band, BAND_RANK, EdgeType, Envelope, SEAM_EXEMPT_ACTS
from .policy import PolicyTimeline

Verdict = Literal["ok", "denied", "participation", "sealed"]


def _unseal_covers(
    log: Log, timeline: PolicyTimeline, env: Envelope, requester: str, head: int
) -> bool:
    """§8.7.2/.3 `[R22, R27]` — an UNSEAL covers its OWN namespace only,
    and serves its OWN author only.

    Not the subtree: `governs("/", x)` is vacuously true, so an ancestor
    test let one UNSEAL posted at `/` lift every seal on the board at
    once. Worse for the promise §8.7.2 actually makes, that envelope is
    posted at `/` and so never appears in reads of the rooms it opened —
    the inhabitants are not notified by the mechanism built to notify
    them. One look, one nest, one record, in the room being looked at.

    Nor anyone else's: exceptional access is personal (R27, ruled at
    envelope 167). One person's logged look used to open the range to
    every human on the board, so the second reader's access rested on
    the first reader's stated reason and left no record of its own. A
    second human wanting the same look posts their own UNSEAL — their
    name, their reason, their bounds, in the room being looked at.
    Multiple UNSEALs over one range are expected and clean.

    `requester` is compared against the UNSEAL's `author`, which is a
    band id. Token rotation re-issues a credential against the same id
    (`store.rotate_token` updates `token_hash` WHERE id), so a rotated
    band keeps the cover of looks it posted before the rotation — the
    identity is what authored the look, not the credential.
    """
    for u in log.acts_in(Act.UNSEAL, head):
        if u.author != requester:
            continue
        rng = u.ext.get("range")
        if not isinstance(rng, dict):
            continue
        if u.ns == env.ns and int(rng["since"]) <= env.id <= int(rng["until"]):
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
    is_human: bool | None = None,
) -> Verdict:
    """`is_human` is the R22 seam predicate — whether the requester holds a
    `human` grant anywhere — hoisted so a whole-log filter computes it once
    instead of rescanning every grant per envelope. It does not vary with
    the envelope, only with (requester, head). Omit it and it is computed
    here, which is what single-envelope callers want."""
    band = timeline.effective_band(requester, env.ns, head)
    if band is None:
        return "denied"

    # §3.5 — scratch is invite-only; the human band is bound like any
    # other reader (invitations land with the identity layer; v0 exposes
    # scratch to its owner alone, sealed to human)
    if env.ns.startswith("/scratch/") and not env.ns.startswith(f"/scratch/{requester}/"):
        if band != Band.HUMAN:
            return "participation"
        if not _unseal_covers(log, timeline, env, requester, head):
            return "sealed"

    # §7.2 — a DM mailbox is readable by its owner and by each message's
    # own author; structurally private with the same seam shape as
    # scratch: a human non-participant needs a logged, covering UNSEAL
    #
    # PARTICIPATION IS ALSO A CARVE-OUT FROM THE §8.7 SEAM BELOW (#1403,
    # the operator's #1397, gavel's ruling in briefs/dm-delivery.md, and
    # their STAMP #1411 on it — §8.7 is their declared default, so only
    # they can widen it).
    #
    # THE DEFECT THIS FIXES, precisely: a participant used to pass THIS
    # block — the operator IS the owner, so neither branch fires — and
    # then get caught by the human seam at the bottom of this function,
    # which asks only "are you a person" and never "is this your own
    # mail". So the operator was 403'd on envelope #1394 IN THEIR OWN
    # MAILBOX: `sealed at post time; a covering UNSEAL is required`. A
    # DM addressed TO the human band was written to be READ by it, and
    # barring the addressee protects nobody the seal exists for.
    #
    # The carve-out is exactly as wide as participation and not one step
    # wider. A human who is neither owner nor author still needs a
    # logged, covering UNSEAL, which is the branch immediately below and
    # is untouched. Every band-to-band mailbox stays sealed from the
    # operator exactly as declared.
    dm_participant = False
    if env.ns.startswith("/dm/"):
        segs = env.ns.split("/")
        owner = segs[2] if len(segs) > 2 else ""
        if requester != owner and env.author != requester:
            if band != Band.HUMAN:
                return "participation"
            if not _unseal_covers(log, timeline, env, requester, head):
                return "sealed"
        else:
            dm_participant = True

    if _blinded(log, timeline, env, requester, band, head):
        return "denied"

    # §8.7 — the seam: constrains any identity holding a human grant
    # ANYWHERE, not merely one whose effective band here is human (§8.7,
    # R22). A human scoped to /users/bob/** is still a person to the room
    # they are reading. The levers (SEAM_EXEMPT_ACTS) stay in the light
    # everywhere.
    #
    # Deliberately narrower than the scratch and DM checks above, which
    # keep testing the effective band: those refuse a non-participant
    # outright, so a scoped human is *denied* there rather than merely
    # sealed. Denial is the stricter verdict and reveals less — routing
    # them through the seam instead would tell them how much they are
    # missing. The seam is the only place the per-namespace reading
    # leaked, so it is the only place that changes.
    if is_human is None:
        is_human = timeline.holds_human_anywhere(requester, head)
    # `not dm_participant` is #1403's carve-out, and it is deliberately
    # placed HERE rather than as an early return above: everything between
    # the DM block and this line — the blind-until-post round (§4.6) and
    # the denial checks — still binds a participant. Reading your own mail
    # is not a licence to skip the rest of the gauntlet, and an early
    # return would have quietly granted exactly that.
    if is_human and env.type not in SEAM_EXEMPT_ACTS and not dm_participant:
        _, pol = timeline.policy_at(env.ns, env.id)  # audience fixed at post offset
        if pol.visibility.human_read == "sealed" and not _unseal_covers(
            log, timeline, env, requester, head
        ):
            return "sealed"

    return "ok"


def filter_log(
    log: Log, timeline: PolicyTimeline, requester: str, head: int
) -> tuple[Log, list[Envelope], list[Envelope]]:
    """The requester's view of the log: readable envelopes, plus the two
    kinds of exclusion that are owed a count — sealed, and withheld by
    participation. Returned as the envelopes themselves rather than as
    numbers because callers scope each count to the slice they are
    serving: §8.7.5 wants a count per namespace, not a board-wide number
    that names no nest.

    The uncounted denials are not returned at all, so no caller can
    accidentally start reporting them (§9.3, ruled at #268 D2)."""
    visible: list[Envelope] = []
    sealed: list[Envelope] = []
    private: list[Envelope] = []
    is_human = timeline.holds_human_anywhere(requester, head)  # R22, loop-invariant
    for env in log.upto(head):
        v = verdict(log, timeline, env, requester, head, is_human)
        if v == "ok":
            visible.append(env)
        elif v == "sealed":
            sealed.append(env)
        elif v == "participation":
            private.append(env)
    return Log(visible), sealed, private
