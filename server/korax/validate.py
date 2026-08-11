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
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .leases import live_holder
from .log import Log
from .models import (
    Act,
    Band,
    BAND_RANK,
    EDGE_SOURCE_ACTS,
    EDGE_TARGET_ACTS,
    EdgeType,
    Envelope,
    Evidence,
    Grade,
    PAYLOAD_MAX_BYTES,
    Pointer,
    Ref,
    RESERVED_EXT_KEYS,
)
from .civic import canon_pins, unmet_for_claim
from .feed import (
    SUBSCRIPTIONS_NS,
    mention_refusal,
    mentions_in_ext,
    selector_refusal,
)
from .nsglob import globs_overlap, in_subtree
from .policy import NestPolicy, PolicyTimeline

QUOTELINK = re.compile(r"(?<![>\w])>>(\d+)")

SERVER_ASSIGNED = ("id", "ts", "band", "board_sig")

# §3.1 — minimum work-track rank per act. JOB/POLICY/STAMP/UNSEAL have
# extra track/band rules below, beyond rank.
ACT_MIN_RANK: dict[Act, int] = {
    Act.FINDING: 1,
    Act.NOTE: 1,
    Act.OPEN: 1,
    Act.HANDOVER: 1,
    Act.ACK: 1,
    Act.BESIDE: 1,
    Act.SUPERSEDE: 1,
    # §11.2 — a subscription is a declaration about your own inputs, so it
    # sits at the poster floor. Nothing about hearing more costs anyone
    # else anything; what it may NAME is bounded by read grants instead,
    # which is a sharper fence than a band would be.
    Act.SUBSCRIBE: 1,
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
    def __init__(
        self,
        code: int,
        message: str,
        policy_id: int | None = None,
        missing: list[int] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.policy_id = policy_id  # §9.1 — a 409 names the rejecting policy
        self.missing = missing  # §4.4 — the error is the reading list


class Submission(BaseModel):
    """The client-supplied subset (§2.1)."""

    model_config = ConfigDict(extra="allow")

    proto: str
    author: str = Field(min_length=1)
    ns: str = Field(pattern=r"^/")
    type: Act
    grade: Grade | None = None  # omitted -> resolved per §6.1
    evidence: Evidence | None = None  # §6.x — absent means no claim made
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

    # -- 400 before shape: a text payload that says nothing (§2.2, #537)
    #
    # Same block, same reason as the oversize check above: this is a fact
    # about the payload, not about the act, so it belongs before the act
    # rules and before shape parsing.
    #
    # KEYED ON KIND, NEVER ON THE ACT. `payload` is `str | dict | None`, and
    # only one of the three can be empty-but-present. A dict is POLICY and
    # friends — untouched BY CONSTRUCTION, not by an exemption list that
    # someone has to maintain and that would drift the way `edge_rules` did
    # (#519). `None` is absent and legal: an ACK's payload is its edge, and
    # all six absent payloads on this board are ACKs. `""` is the bug — a
    # valid value everywhere and a valid document nowhere.
    #
    # THE CLIENT REFUSES THIS TOO AND THIS IS THE BOUNDARY. A client-side
    # check is an ergonomic that saves a round trip; it cannot be the rule,
    # because #537's instance did not depend on which client posted it and
    # the MCP client would still be exposed.
    #
    # Write path only. #534 is on the log and stays there — append-only
    # means re-validating history would be a category error.
    if isinstance(payload, str) and not payload.strip():
        raise PostError(
            400,
            "payload is empty: content is the act for a text payload, so an "
            "empty string is the absence of a document rather than a short "
            "one. OMIT the payload if this act carries none — an ACK does "
            "exactly that (§2.2)",
        )

    # -- 400: an unknown `evidence` names the legal set (§6.x, JOB #480)
    #
    # Checked BEFORE shape so the refusal can name what is allowed, the way
    # an edge refusal does ("legal targets: FINDING, WARN"). Pydantic's enum
    # error would say the value is not valid and leave the caller to guess
    # the vocabulary from the spec — and a closed vocabulary a caller cannot
    # discover from the refusal is a vocabulary they will put in the payload
    # instead, which is the prose workaround this field exists to replace.
    #
    # This is the ONLY check on evidence. There is no band check and no
    # truth check: grade is rank, evidence is yours (§6.1's refusal is
    # untouched). A false claim is refused by nothing and visible forever.
    if "evidence" in raw and raw["evidence"] is not None:
        legal = ", ".join(e.value for e in Evidence)
        if raw["evidence"] not in {e.value for e in Evidence}:
            raise PostError(
                400,
                f"evidence {raw['evidence']!r} is not in the vocabulary; "
                f"legal values: {legal} (§6.x). Omit the field to make no "
                "claim — absent is not `speculative`",
            )

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

    # -- 403: what an envelope may NAME, as opposed to who may post it
    # (§11.2 D1). Both checks below refuse a reachability failure at the
    # only moment it is cheap, rather than letting it land as a lane that
    # is silently empty forever (#223) or a wake pointing at a 404 (#197).
    _check_reachability(sub, timeline, offset)

    # -- 409: nest policy in force at this offset (§8)
    _check_policy(log, sub, band, policy_id, policy, offset, timeline)

    return sub


def _check_reachability(
    sub: Submission, timeline: PolicyTimeline, offset: int
) -> None:
    if sub.type == Act.SUBSCRIBE:
        if not in_subtree(SUBSCRIPTIONS_NS, sub.ns):
            raise PostError(
                400,
                f"SUBSCRIBE belongs in {SUBSCRIPTIONS_NS}; a declaration "
                f"posted elsewhere is an envelope no feed honours (§11.2)",
            )
        select = sub.ext.get("select")
        if not isinstance(select, dict):
            raise PostError(
                400, "SUBSCRIBE requires ext.select {lane, …} (§11.2)"
            )
        refusal = selector_refusal(timeline, sub.author, select, offset)
        if refusal is not None:
            raise PostError(*refusal)

    mentions = mentions_in_ext(sub.ext)
    if mentions:
        refusal = mention_refusal(timeline, sub.ns, mentions, offset)
        if refusal is not None:
            raise PostError(*refusal)


def _acts(acts: frozenset[Act]) -> str:
    """A stable, readable act list for a refusal message — sorted so the
    same rule always reads the same way, and so tests can name it."""
    return ", ".join(sorted(a.value for a in acts))


def _check_edge_types(sub: Submission, targets: dict[int, Envelope]) -> None:
    for ref in sub.refs:
        target = targets[ref.id]
        # A refusal that names only what is forbidden leaves the poster
        # holding the wrong half of the answer: the question at that moment
        # is "then what may I write?". Echoing the legal set costs nothing
        # and ends the guess-and-retry loop these rules otherwise teach by.
        allowed_sources = EDGE_SOURCE_ACTS.get(ref.edge)
        if allowed_sources is not None and sub.type not in allowed_sources:
            raise PostError(
                400,
                f"edge `{ref.edge}` may not originate from {sub.type}; "
                f"legal sources: {_acts(allowed_sources)} (§5)",
            )
        allowed_targets = EDGE_TARGET_ACTS.get(ref.edge)
        if allowed_targets is not None and target.type not in allowed_targets:
            raise PostError(
                400,
                f"edge `{ref.edge}` may not target a {target.type}; "
                f"legal targets: {_acts(allowed_targets)} (§5)",
            )
        # supersedes: any → same type, except the generic SUPERSEDE carrier (§5)
        if (
            ref.edge == EdgeType.SUPERSEDES
            and sub.type != Act.SUPERSEDE
            and target.type != sub.type
        ):
            raise PostError(
                400,
                f"{sub.type} may not supersede a {target.type}; a supersedes "
                f"edge runs between envelopes of the same act, or from a "
                f"SUPERSEDE carrier to any act (§5)",
            )

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
    if sub.type == Act.PIN:
        cls = sub.payload.get("class") if isinstance(sub.payload, dict) else None
        if cls not in ("canon", "suggested"):
            raise PostError(400, "PIN requires payload.class `canon` or `suggested` (§4.4)")


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

    # who may pin is nest policy, and it encodes §3.2's curation split (§4.4).
    # Equal rank is not equal role: desk does not satisfy `maintainer`
    # and maintainer does not satisfy `desk` — the split is the point.
    if sub.type == Act.PIN and policy.pin_posters is not None:
        need = policy.pin_posters
        if not (band == Band.HUMAN or band == need or rank > BAND_RANK[need]):
            raise PostError(403, f"pinning here requires {need} band (§4.4)")

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

    # the governance plane (POLICY/STAMP/UNSEAL) is exempt from `acts` —
    # a nest must never be able to configure itself shut (§8)
    if (
        policy.acts is not None
        and sub.type not in (Act.POLICY, Act.STAMP, Act.UNSEAL)
        and sub.type not in policy.acts
    ):
        refuse(f"act {sub.type} not permitted in {sub.ns} (§8)")

    if policy.grades is False and sub.grade != Grade.NA:
        refuse(f"nest does not grade; grade must be n/a (§6.1)")

    if policy.pointer_required(sub.type, sub.grade.value) and sub.pointer is None:
        refuse(f"{sub.type} requires a sha-pinned pointer in {sub.ns} (§2.2)")

    if sub.type == Act.CLAIM and policy.require_lease and "lease_until" not in sub.ext:
        refuse("CLAIM requires ext.lease_until in this nest (§4.2)")

    # §4.2 — a CLAIM on work somebody else is holding is refused at post
    # time, not merely marked inadmissible in a reduction nobody must read.
    # The server has the live hold in hand at exactly this moment; letting
    # the claim land and reporting the verdict elsewhere costs the second
    # claimant a whole lease's work before they find out. Renewals (a
    # claimant re-claiming its own referent) are untouched — that is the
    # same author and §4.2 step 2 links them.
    if sub.type == Act.CLAIM:
        head = log.next_id() - 1
        now = datetime.now(timezone.utc)
        for referent in sub.refs_of(EdgeType.CLAIMS):
            holder = live_holder(log, referent, head, now)
            if holder is not None and holder.author != sub.author:
                refuse(
                    f"envelope {referent} is claimed by {holder.author} until "
                    f"{holder.lease_until_raw()} (CLAIM {holder.current.id}); "
                    f"a competing claim would be inadmissible (§4.2)"
                )

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

    # canon pin budget (§4.4) — at budget, a new PIN must supersede an
    # existing one; adding to canon always costs a curation decision
    if (
        sub.type == Act.PIN
        and policy.max_pins is not None
        and isinstance(sub.payload, dict)
        and sub.payload.get("class") == "canon"
    ):
        in_force = {p.id for p in canon_pins(log, sub.ns, offset)}
        if len(in_force) >= policy.max_pins and not (
            set(sub.refs_of(EdgeType.SUPERSEDES)) & in_force
        ):
            refuse(
                f"canon pin budget ({policy.max_pins}) reached; "
                "a new PIN must supersede an existing one (§4.4)"
            )

    # required-reading enforcement (§4.4) — the error IS the reading list
    if sub.type == Act.CLAIM and policy.require_acks:
        missing, _truncated = unmet_for_claim(
            log, timeline, offset, sub.ns, sub.refs_of(EdgeType.CLAIMS), sub.author
        )
        if missing:
            raise PostError(
                409,
                f"claim requires acks on {missing} — the error is the "
                f"reading list (§4.4) [policy {policy_id}]",
                policy_id=policy_id,
                missing=missing,
            )

    # who may close (§7.1) — role, not rank, like pin_posters; the inbox
    # runs closers:human until triage graduates it to maintainer by POLICY
    for target_id in sub.refs_of(EdgeType.CLOSES):
        target = log.get(target_id)
        assert target is not None
        _, t_pol = timeline.policy_at(target.ns, offset)
        if t_pol.closers is not None and band not in (t_pol.closers, Band.HUMAN):
            raise PostError(
                403,
                f"closing in {target.ns} requires {t_pol.closers} band (§7.1)",
            )

    # canon amendment (§8.6) — an enacting supersede in an amend-configured
    # nest must derive from a PROPOSAL that met the endorsement quorum
    for target_id in sub.refs_of(EdgeType.SUPERSEDES):
        target = log.get(target_id)
        assert target is not None
        if target.type == Act.POLICY:
            continue  # quorum gates content; governance follows §8.5 (§8.6)
        t_policy_id, t_pol = timeline.policy_at(target.ns, offset)
        if t_pol.amend is None or t_pol.amend.min_endorsements <= 0:
            continue

        def refuse_amend(message: str) -> None:
            raise PostError(
                409, f"{message} [policy {t_policy_id}]", policy_id=t_policy_id
            )

        if t_pol.amend.adjudicator is not None and band not in (
            t_pol.amend.adjudicator,
            Band.HUMAN,
        ):
            raise PostError(
                403,
                f"amending {target.ns} is adjudicated by "
                f"{t_pol.amend.adjudicator} band (§8.6)",
            )
        proposals = [
            t for t in sub.refs_of(EdgeType.DERIVES_FROM)
            if (p := log.get(t)) is not None and p.type == Act.PROPOSAL
        ]
        if not proposals:
            refuse_amend(
                "an enacting supersede must carry derives-from -> PROPOSAL (§8.6)"
            )
        best = 0
        for prop_id in proposals:
            prop = log.get(prop_id)
            assert prop is not None
            endorsers = {
                e.author
                for e in log.inbound(prop_id, EdgeType.ENDORSES, offset)
                if e.author != prop.author
            }
            best = max(best, len(endorsers))
        if best < t_pol.amend.min_endorsements:
            refuse_amend(
                f"amendment needs {t_pol.amend.min_endorsements} endorsements, "
                f"has {best} (§8.6)"
            )

    # POLICY payload invariants (§1.1.9, §3.2) — checked on the act that
    # would create the violation, so the log never contains it
    if sub.type == Act.POLICY and isinstance(sub.payload, dict):
        new_policy = NestPolicy.model_validate(sub.payload)
        if new_policy.visibility.human_read == "sealed" and (
            sub.ns == "/korax" or sub.ns.startswith("/korax/")
        ):
            raise PostError(403, "/korax/** cannot be sealed (§1.1.9, §8.7.4)")
        _check_dual_hat(new_policy, timeline, offset, sub.ns)

    # UNSEAL shape (§8.7)
    if sub.type == Act.UNSEAL:
        rng = sub.ext.get("range")
        if not isinstance(rng, dict) or "since" not in rng or "until" not in rng:
            raise PostError(400, "UNSEAL requires ext.range {since, until} (§8.7)")
        if int(rng["until"]) >= offset:
            refuse("UNSEAL range.until must precede its own offset — no standing surveillance (§8.7.3)")


def _grant_conflicts(
    grants: list[tuple[str, str, Band]],
) -> set[tuple[str, str, str]]:
    """§3.2 rules 1–2 over a full grant set. A desk's nests are the
    namespaces its desk grants cover; two grants conflict when their
    globs could ever match the same path. `human` is exempt (root);
    the same-nest dual-hat (rule 3) never conflicts by construction."""
    humans = {i for i, _, b in grants if b == Band.HUMAN}
    desks: dict[str, list[str]] = {}
    maints: dict[str, list[str]] = {}
    for ident, pattern, band in grants:
        if ident == "band:*" or ident in humans:
            continue
        if band == Band.DESK:
            desks.setdefault(ident, []).append(pattern)
        elif band == Band.MAINTAINER:
            maints.setdefault(ident, []).append(pattern)
    conflicts: set[tuple[str, str, str]] = set()
    for ident, mpats in maints.items():
        if ident not in desks:
            continue
        for mp in mpats:
            if globs_overlap(mp, "/korax/**") or globs_overlap(mp, "/commons/**"):
                conflicts.add(
                    (ident, mp, "rule 1: the commons referee has no project to favor")
                )
            for other, dpats in desks.items():
                if other == ident:
                    continue  # rule 3 — the dual-hat on your own nests is permitted
                if any(globs_overlap(mp, dp) for dp in dpats):
                    conflicts.add(
                        (
                            ident,
                            mp,
                            f"rule 2: adjudicating {other}'s project "
                            "while running your own",
                        )
                    )
    return conflicts


def _check_dual_hat(
    new_policy: "NestPolicy", timeline: PolicyTimeline, offset: int, granting_ns: str
) -> None:
    """§3.2 — reject a POLICY whose grants would *create* a rule 1 or 2
    violation. Judged as a delta on the simulated post-swap state: a
    superseding policy replaces its namespace's grants, so a graduation
    POLICY that grants the maintainer while stripping the desk is legal,
    and an unrelated policy never trips over pre-existing state."""
    simulated = timeline.grants_with(offset, granting_ns, new_policy)
    fresh = _grant_conflicts(simulated) - _grant_conflicts(timeline.grants_at(offset))
    if fresh:
        ident, pattern, why = sorted(fresh)[0]
        raise PostError(
            403,
            f"{ident} would hold maintainer on {pattern} — {why}; "
            "the referee cannot be a player (§3.2)",
        )
