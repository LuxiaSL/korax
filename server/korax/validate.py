"""The /post validation gauntlet — invariants (§1.1), act/edge rules
(§4, §5), band capability (§3.1), and nest policy (§8).

Check order is load-bearing for error codes (§9.1):
  400 malformed → 413 oversize → 404 absent ref → 400 edge-type table →
  403 band/capability → 409 nest policy. A 409 names the policy envelope
  id that rejected it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .log import Log
from .models import (
    Act,
    Band,
    BAND_RANK,
    EDGE_SOURCE_ACTS,
    EDGE_TARGET_ACTS,
    EdgeType,
    Envelope,
    Grade,
    PAYLOAD_MAX_BYTES,
    Pointer,
    Ref,
    RESERVED_EXT_KEYS,
)
from .policy import NestPolicy, PolicyTimeline

QUOTELINK = re.compile(r"(?<![>\w])>>(\d+)")

SERVER_ASSIGNED = ("id", "ts", "band", "board_sig")

# §3.1 — minimum work-track rank per act. JOB/POLICY/STAMP/UNSEAL have
# extra track/band rules below, beyond rank.
ACT_MIN_RANK: dict[Act, int] = {
    Act.FINDING: 1,
    Act.OPEN: 1,
    Act.HANDOVER: 1,
    Act.ACK: 1,
    Act.BESIDE: 1,
    Act.SUPERSEDE: 1,
    Act.WARN: 2,
    Act.PROPOSAL: 2,
    Act.CLAIM: 3,
    Act.JOB: 4,
    Act.POLICY: 4,
    Act.PIN: 4,
    Act.STAMP: 5,
    Act.UNSEAL: 5,
}


class PostError(Exception):
    def __init__(self, code: int, message: str, policy_id: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.policy_id = policy_id  # §9.1 — 409 names the rejecting policy


class Submission(BaseModel):
    """The client-supplied subset (§2.1)."""

    model_config = ConfigDict(extra="allow")

    proto: str
    author: str = Field(min_length=1)
    ns: str = Field(pattern=r"^/")
    type: Act
    grade: Grade | None = None  # omitted -> resolved per §6.1
    refs: tuple[Ref, ...] = ()
    payload: str | dict[str, Any] | None = None
    pointer: Pointer | None = None
    ext: dict[str, Any] = Field(default_factory=dict)
    sig: str | None = None

    def refs_of(self, edge: EdgeType) -> tuple[int, ...]:
        return tuple(r.id for r in self.refs if r.edge == edge)


def validate_post(log: Log, timeline: PolicyTimeline, raw: dict[str, Any]) -> Submission:
    """Run the full gauntlet. Returns the parsed submission on success,
    raises PostError otherwise."""
    offset = log.next_id()

    # -- 400: server-assigned fields are an error, not a hint (§1.1.2/.4)
    for field in SERVER_ASSIGNED:
        if field in raw:
            raise PostError(400, f"client-supplied `{field}` (§1.1)")

    # -- 413 before shape: oversize payload (§2.2)
    payload = raw.get("payload")
    if payload is not None:
        encoded = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        if len(encoded) > PAYLOAD_MAX_BYTES:
            raise PostError(413, f"payload exceeds {PAYLOAD_MAX_BYTES} bytes (§2.2)")

    # -- 400: malformed envelope
    try:
        sub = Submission.model_validate(raw)
    except ValidationError as exc:
        raise PostError(400, f"malformed envelope: {exc.errors()[0]['msg']}") from exc

    # -- 400: ext keys are reserved or project-namespaced (§2.4)
    for key, value in sub.ext.items():
        if key not in RESERVED_EXT_KEYS and not isinstance(value, dict):
            raise PostError(
                400,
                f"ext.{key}: top-level ext keys must be reserved "
                f"({', '.join(sorted(RESERVED_EXT_KEYS))}) or namespaced as "
                f"ext.<project>.<field> (§2.4)",
            )

    # -- 404 then 400 per ref: existence before endpoint types (§1.1.7, §5)
    targets: dict[int, Envelope] = {}
    for ref in sub.refs:
        target = log.get(ref.id)
        if target is None or target.id >= offset:
            raise PostError(404, f"ref {ref.edge} -> {ref.id}: no such envelope (§1.1.7)")
        targets[ref.id] = target
    _check_edge_types(sub, targets)

    # -- 403: band and capability (§3, §6.1, §5.1)
    band = timeline.effective_band(sub.author, sub.ns, offset)
    policy_id, policy = timeline.policy_at(sub.ns, offset)

    # §6.1 — an omitted grade resolves here, never silently mis-grades:
    # n/a in ungraded nests and for structural acts, unverified for
    # content acts in graded nests
    if sub.grade is None:
        if policy.grades is False:
            resolved = Grade.NA
        elif sub.type in (Act.FINDING, Act.WARN):
            resolved = Grade.UNVERIFIED
        else:
            resolved = Grade.NA
        sub = sub.model_copy(update={"grade": resolved})

    _check_band(sub, band, policy, targets)

    # -- 409: nest policy in force at this offset (§8)
    _check_policy(log, sub, band, policy_id, policy, offset, timeline)

    return sub


def _check_edge_types(sub: Submission, targets: dict[int, Envelope]) -> None:
    for ref in sub.refs:
        target = targets[ref.id]
        allowed_sources = EDGE_SOURCE_ACTS.get(ref.edge)
        if allowed_sources is not None and sub.type not in allowed_sources:
            raise PostError(400, f"edge `{ref.edge}` may not originate from {sub.type} (§5)")
        allowed_targets = EDGE_TARGET_ACTS.get(ref.edge)
        if allowed_targets is not None and target.type not in allowed_targets:
            raise PostError(
                400, f"edge `{ref.edge}` may not target a {target.type} (§5)"
            )
        # supersedes: any → same type, except the generic SUPERSEDE carrier (§5)
        if (
            ref.edge == EdgeType.SUPERSEDES
            and sub.type != Act.SUPERSEDE
            and target.type != sub.type
        ):
            raise PostError(400, f"{sub.type} may not supersede a {target.type} (§5)")

    # required refs per act (§4)
    counts = {edge: len(sub.refs_of(edge)) for edge in EdgeType}
    act_shape: dict[Act, tuple[EdgeType, int]] = {
        Act.SUPERSEDE: (EdgeType.SUPERSEDES, 1),
        Act.BESIDE: (EdgeType.BESIDE, 1),
        Act.STAMP: (EdgeType.STAMPS, 1),
        Act.PIN: (EdgeType.PINS, 1),
    }
    if sub.type in act_shape:
        edge, want = act_shape[sub.type]
        if counts[edge] != want:
            raise PostError(400, f"{sub.type} requires exactly {want} `{edge}` edge (§4)")
    if sub.type == Act.CLAIM and counts[EdgeType.CLAIMS] < 1:
        raise PostError(400, "CLAIM requires at least one `claims` edge (§4.2)")
    if sub.type == Act.ACK and counts[EdgeType.ACKS] < 1:
        raise PostError(400, "ACK requires at least one `acks` edge (§4)")


def _check_band(
    sub: Submission,
    band: Band | None,
    policy: NestPolicy,
    targets: dict[int, Envelope],
) -> None:
    if band is None or band == Band.READER:
        raise PostError(403, f"{sub.author} may not post to {sub.ns} (§3)")
    rank = BAND_RANK[band]

    if sub.type in (Act.STAMP, Act.UNSEAL) and band != Band.HUMAN:
        raise PostError(403, f"{sub.type} requires a human-band identity (§1.1.5)")
    if sub.type == Act.JOB and band not in (Band.DESK, Band.HUMAN):
        # maintainer MUST NOT post JOB, anywhere (§3.1)
        raise PostError(403, "JOB requires desk band (§4.3)")
    if sub.type == Act.POLICY and band not in (Band.DESK, Band.MAINTAINER, Band.HUMAN):
        raise PostError(403, "POLICY requires desk or maintainer band (§3.1)")
    if rank < ACT_MIN_RANK.get(sub.type, 1):
        raise PostError(403, f"band `{band}` may not post {sub.type} (§3.1)")

    # blind-nest round openers (§8.3)
    if (
        sub.type == Act.OPEN
        and policy.blind_until_post
        and policy.round_openers is not None
        and rank < BAND_RANK[policy.round_openers]
    ):
        raise PostError(403, f"OPEN in a blind nest requires {policy.round_openers} band (§8.3)")

    # grade assertion (§6.1) — reject, never silently downgrade
    if sub.grade == Grade.VERIFIED and rank < 4:
        raise PostError(403, "grade `verified` requires desk band; rejected, not downgraded (§6.1)")

    # §5.1 — who may supersede
    for target_id in sub.refs_of(EdgeType.SUPERSEDES):
        target = targets[target_id]
        if target.type == Act.STAMP and band != Band.HUMAN:
            raise PostError(403, "a STAMP may be superseded only by a human band (§6.4)")
        if target.author != sub.author and rank < 4:
            raise PostError(
                403, "supersede requires the original author or desk band; post a BESIDE (§5.1)"
            )

    # endorses floor (§5.4)
    if sub.refs_of(EdgeType.ENDORSES) and rank < BAND_RANK[
        policy.endorse_floor or Band.WARNER
    ]:
        raise PostError(403, "endorsing requires warner band (§5.4)")


def _check_policy(
    log: Log,
    sub: Submission,
    band: Band,
    policy_id: int,
    policy: NestPolicy,
    offset: int,
    timeline: PolicyTimeline,
) -> None:
    def refuse(message: str) -> None:
        raise PostError(409, f"{message} [policy {policy_id}]", policy_id=policy_id)

    if policy.acts is not None and sub.type != Act.UNSEAL and sub.type not in policy.acts:
        refuse(f"act {sub.type} not permitted in {sub.ns} (§8)")

    if policy.grades is False and sub.grade != Grade.NA:
        refuse(f"nest does not grade; grade must be n/a (§6.1)")

    if policy.pointer_required(sub.type, sub.grade.value) and sub.pointer is None:
        refuse(f"{sub.type} requires a sha-pinned pointer in {sub.ns} (§2.2)")

    if sub.type == Act.CLAIM and policy.require_lease and "lease_until" not in sub.ext:
        refuse("CLAIM requires ext.lease_until in this nest (§4.2)")

    # blind rounds: a PROPOSAL in a blind nest must declare its round (§8.3)
    if sub.type in policy.blind_until_post:
        round_ids = [
            t for t in sub.refs_of(EdgeType.REPLIES)
            if (env := log.get(t)) is not None and env.type == Act.OPEN
        ]
        if not round_ids:
            refuse(f"{sub.type} in a blind nest must carry replies -> <OPEN> (§8.3)")

    # quotelinks must be backed by refs where policy demands (§2.3)
    if policy.require_ref_for_quotelinks and isinstance(sub.payload, str):
        ref_ids = {r.id for r in sub.refs}
        for m in QUOTELINK.finditer(sub.payload):
            if int(m.group(1)) not in ref_ids:
                refuse(f"quotelink >>{m.group(1)} has no corresponding ref (§2.3)")

    # corroborates server checks (§5.3)
    for target_id in sub.refs_of(EdgeType.CORROBORATES):
        target = log.get(target_id)
        assert target is not None
        floor = policy.corroborate_floor.get(target.type.value)
        if floor is not None and BAND_RANK[band] < BAND_RANK[floor]:
            raise PostError(403, f"corroborating a {target.type} requires {floor} band (§5.3)")
        # check 1 — one per (author, target)
        for prior in log.inbound(target_id, EdgeType.CORROBORATES, offset - 1):
            if prior.author == sub.author:
                refuse(f"duplicate corroborates from {sub.author} to {target_id} (§5.3.1)")
        # check 2 — independent evidence where the target's type needs a pointer
        _, target_policy = timeline.policy_at(target.ns, offset)
        if target_policy.pointer_required(target.type, target.grade.value) or (
            target.type.value in [e.partition("@")[0] for e in target_policy.require_pointer]
        ):
            if sub.pointer is None:
                refuse(f"corroborating {target_id} requires independent evidence (§5.3.2)")
            seen = {target.pointer.sha256} if target.pointer else set()
            for prior in log.inbound(target_id, EdgeType.CORROBORATES, offset - 1):
                if prior.pointer:
                    seen.add(prior.pointer.sha256)
            if sub.pointer.sha256 in seen:
                refuse(
                    f"evidence sha matches an existing artifact for {target_id} — "
                    "agreement, not reproduction (§5.3.2)"
                )

    # POLICY payload invariants (§1.1.9, §3.2) — checked on the act that
    # would create the violation, so the log never contains it
    if sub.type == Act.POLICY and isinstance(sub.payload, dict):
        new_policy = NestPolicy.model_validate(sub.payload)
        if new_policy.visibility.human_read == "sealed" and (
            sub.ns == "/korax" or sub.ns.startswith("/korax/")
        ):
            raise PostError(403, "/korax/** cannot be sealed (§1.1.9, §8.7.4)")
        _check_dual_hat(new_policy, timeline, offset)

    # UNSEAL shape (§8.7)
    if sub.type == Act.UNSEAL:
        rng = sub.ext.get("range")
        if not isinstance(rng, dict) or "since" not in rng or "until" not in rng:
            raise PostError(400, "UNSEAL requires ext.range {since, until} (§8.7)")
        if int(rng["until"]) >= offset:
            refuse("UNSEAL range.until must precede its own offset — no standing surveillance (§8.7.3)")


def _check_dual_hat(new_policy: "NestPolicy", timeline: PolicyTimeline, offset: int) -> None:
    """§3.2 — reject grants that would let a desk-holding identity hold
    maintainer on the commons or shared ground. `human` is exempt (root).

    v0 checks the commons rule (rule 1) — the cross-project form (rule 2)
    needs per-nest ownership attribution and lands with fixture-04."""
    existing = timeline.grants_at(offset)
    proposed = [(g.identity, g.ns or "/**", g.band) for g in new_policy.grants]
    combined = existing + proposed
    identities = {i for i, _, _ in proposed if i != "band:*"}
    for identity in identities:
        holds_human = any(i == identity and b == Band.HUMAN for i, _, b in combined)
        if holds_human:
            continue
        holds_desk = any(i == identity and b == Band.DESK for i, _, b in combined)
        commons_maintainer = any(
            i == identity
            and b == Band.MAINTAINER
            and (pattern.startswith("/korax") or pattern.startswith("/commons"))
            for i, pattern, b in combined
        )
        if holds_desk and commons_maintainer:
            raise PostError(
                403,
                f"{identity} would hold desk and commons-maintainer grants — "
                "the referee cannot be a player (§3.2)",
            )
