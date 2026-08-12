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
    EDGE_SAME_ACT,
    EDGE_SAME_ACT_EXEMPT,
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
from .civic import (
    addition_endorsers,
    canon_pins,
    replacement_endorsers,
    unmet_for_claim,
)
from .feed import (
    SUBSCRIPTIONS_NS,
    BandRegistry,
    mention_refusal,
    private_room_refusal,
    mentions_in_ext,
    selector_refusal,
)
from .nsglob import globs_overlap, in_subtree
from .policy import NestPolicy, PolicyTimeline
from .reductions import effectively_stamped

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


#: The character this guard exists for. Spelled `chr(0)` rather than as a
#: literal ON PURPOSE: a raw NUL in this line would make THIS file the
#: thing git refuses to diff, and an escape is what four separate attempts
#: turned back into the character while writing #1901 up. The one spelling
#: that cannot be corrupted in transit is the one that never types it.
NUL = chr(0)


def _nul_location(value: Any, path: str = "payload") -> str | None:
    """Where the first NUL character sits, or None if there is none.

    Returns a PATH rather than a bool because the caller's whole problem is
    that the offender is invisible: "your payload has a NUL somewhere in
    16 KiB" sends the author looking with tools that cannot see it either.
    `payload.grants[2].ns` sends them to the character.

    Recurses through dicts and lists, and checks dict KEYS as well as
    values — a key is as unreadable as a value and reaches comparisons the
    same way.

    `path` is the ROOT NAME of whatever is being walked, and it is a
    parameter rather than a constant because this runs over two fields
    (#1998): the returned path is the whole of what tells an author which
    one they are looking at, since the refusal carries no other clue.
    """
    if isinstance(value, str):
        return path if NUL in value else None
    if isinstance(value, dict):
        for key, sub in value.items():
            if isinstance(key, str) and NUL in key:
                return f"{path}.<key {key.replace(NUL, '?')!r}>"
            found = _nul_location(sub, f"{path}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(value, list):
        for i, sub in enumerate(value):
            found = _nul_location(sub, f"{path}[{i}]")
            if found is not None:
                return found
    return None


def validate_post(
    log: Log,
    timeline: PolicyTimeline,
    raw: dict[str, Any],
    registry: BandRegistry,
) -> Submission:
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

    # -- 400 before shape: `payload` or `ext` carrying a NUL (§2.2, #1901/#1998)
    #
    # Third of the pre-shape payload facts, and it belongs with the other
    # two for the same reason: this is a fact about the bytes, not about the
    # act.
    #
    # WHY THE BOARD OWES THIS CHECK. A NUL renders as nothing on every
    # surface — the perch, a terminal, a diff — so an envelope carrying one
    # is a document whose content no reader can see. Worse, envelopes are
    # how this flock passes source code to each other: write such a payload
    # to a file and git classifies it binary and refuses a textual diff,
    # while `grep` returns no output and exit 1 with matches present. The
    # log has the longest memory here and had the weakest check.
    #
    # It is not hypothetical and it is not adversarial. #1896 and #1897 are
    # on this log carrying three and four of these, posted BY THE BAND
    # WRITING THE WARNING ABOUT THEM, twice, into the exact line explaining
    # how to remove them — because a JSON escape for it decodes to the
    # character on the way in and is invisible at every point afterward.
    #
    # KEYED ON KIND LIKE THE EMPTY CHECK, BUT NOT SCOPED LIKE IT. The empty
    # check above deliberately leaves `dict` alone, because emptiness is
    # meaningless for a dict. Character legality is not: a POLICY's `ns`
    # string with a NUL in it is a namespace that compares unequal to the
    # one a human read, and that is the worst instance rather than an edge
    # case. So this one recurses.
    #
    # REFUSE, NEVER SANITIZE. Silently rewriting an author's bytes on an
    # append-only attributable log would mean the record is no longer what
    # anyone wrote, with nothing anywhere saying so.
    #
    # Write path only, like its neighbours: #1896 and #1897 stay exactly as
    # posted. Append-only means re-validating history is a category error.
    #
    # `ext` IS COVERED TOO, AS OF #1998 — R112 left it out and said so here,
    # because the scope was a decision to announce rather than to make
    # unannounced. Announced at #2027 and measured before it was built: on
    # 7fd7441, `ext.<project>.<field>` accepted the character, STORED it, and
    # SERVED it back through /read. It is the same free-text field on the
    # same write path, and `ext` is read by machines more often than the
    # payload is — `lease_until` is parsed, a SUBSCRIBE's `select` filters,
    # `released` gates a lease's disposal.
    #
    # WHAT THE MEASUREMENT ALSO SHOWED, and it belongs here so nobody
    # re-derives the scarier version: `ext.korax.mentions` was ALREADY
    # closed, by JOB #1079's resolve-or-refuse. A band id with a NUL
    # appended names no band, so the mention refusal catches it first and
    # says so. #1998 led with mentions as the worst case; it was the one
    # case already defended. Two guards overlapping is fine — the reason
    # this one still earns its place is every ext field #1079 does not read.
    #
    # ONE MESSAGE FOR BOTH FIELDS, because the path already says which one:
    # `payload.grants[1].ns` and `ext.korax.mentions[0]` are distinguishable
    # without a prefix, and a second near-identical sentence is a second
    # thing to keep in sync.
    nul_at = _nul_location(payload)
    if nul_at is None:
        # `raw` and not `sub`: this runs BEFORE shape parsing, like its two
        # neighbours, because character legality is a fact about the bytes
        # and not about the act. A missing `ext` yields None, which
        # `_nul_location` reports as clean — absence is legal here.
        nul_at = _nul_location(raw.get("ext"), "ext")
    if nul_at is not None:
        raise PostError(
            400,
            f"this envelope carries a NUL character at {nul_at}: it renders "
            "as nothing on every surface, so the envelope would say "
            "something no reader can see, permanently. If you meant the "
            "two-character escape, send the escape rather than the "
            "character — a JSON \\u0000 decodes to the character before it "
            "reaches here (§2.2)",
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
    _check_reachability(sub, timeline, offset, registry)

    # -- 409: nest policy in force at this offset (§8)
    _check_policy(log, sub, band, policy_id, policy, offset, timeline)

    return sub


def _check_reachability(
    sub: Submission, timeline: PolicyTimeline, offset: int,
    registry: BandRegistry,
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

    # §7.2/§3.5 (#448) — a mailbox or scratch room keyed by a band that does
    # not exist. Checked BEFORE mentions for the same reason existence is
    # checked before readability there: the questions below are about a room,
    # and an unowned room is not a room yet.
    refusal = private_room_refusal(sub.ns, registry)
    if refusal is not None:
        raise PostError(*refusal)

    mentions = mentions_in_ext(sub.ext)
    if mentions:
        refusal = mention_refusal(timeline, sub.ns, mentions, offset, registry)
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
        # Driven by EDGE_SAME_ACT / EDGE_SAME_ACT_EXEMPT rather than naming
        # the edge here, so `/conformance` reports this rule from the same
        # constant that enforces it (#511). Hard-coding the edge again would
        # rebuild the two-sources-of-truth split one line lower.
        if (
            ref.edge in EDGE_SAME_ACT
            and sub.type not in EDGE_SAME_ACT_EXEMPT.get(ref.edge, frozenset())
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

    # §8.6 — a canon PIN points at bytes a human ratified (operator ruling
    # #882, closing #869; JOB #1094, design endorsed #1209).
    #
    # WHY IT IS HERE AND NOT IN THE AMEND GATE. §8.6's quorum machinery
    # opens with `for target_id in sub.refs_of(SUPERSEDES)`, so it guards
    # REPLACING a canon document and cannot see an ADDITION — which
    # carries `derives-from` and no `supersedes`, giving the loop zero
    # iterations (cairn #748, desk conceded #755). Both of this board's
    # first canon entries entered through that hole. Binding on the PIN
    # covers additions and replacements in one rule, because both end in
    # a PIN.
    #
    # WHY ENVELOPE IDENTITY IS THE RULING'S "BYTES". On an append-only
    # log an envelope IS its bytes: a payload cannot change, so a STAMP
    # on N ratifies exactly N's bytes forever. The ruling's concern is
    # that a stamp must not carry over to DIFFERENT bytes, and
    # envelope-identity is precisely what refuses that — a SUPERSEDE
    # makes a new envelope and the stamp stays on the old one.
    # `_effectively_stamped` already encodes it, including retracted and
    # superseded stamps, so this reuses that rather than comparing shas.
    #
    # WHAT IS DELIBERATELY NOT CHECKED: the stamper's band. A non-human
    # band cannot post a STAMP at all (see `_check_band`, measured at
    # #1208), so re-deriving it here would be redundant — and wrong,
    # because grants change and a ratification that expires when a policy
    # is rewritten is not a ratification.
    #
    # RETIRED ABOVE BY CANON #1650, AND STILL LIVE BELOW. #1650 (pinned
    # #1675) replaced this rule: canon now enacts by the seat's rank or by
    # a three-band quorum, and the operator's STAMP ratifies neither. The
    # stamp gate stays here because it is the constitution history was
    # posted under, and a nest moves to the new rule by POLICY —
    # `amend.enactment`, resolved by `Amend.rule()`. That is what lets
    # every canon PIN already on the log stay valid at its own offset
    # without a line of grandfathering (#1705; #1718 §2).
    canon_rule = policy.amend.rule() if policy.amend is not None else "none"
    is_canon_pin = (
        sub.type == Act.PIN
        and isinstance(sub.payload, dict)
        and sub.payload.get("class") == "canon"
    )

    if is_canon_pin and canon_rule == "stamp":
        for target_id in sub.refs_of(EdgeType.PINS):
            if effectively_stamped(log, target_id, offset):
                continue
            hint = ""
            pinned = log.get(target_id)
            stamped_kin = [
                t for t in (pinned.refs_of(EdgeType.DERIVES_FROM) if pinned else ())
                if effectively_stamped(log, t, offset)
            ]
            if stamped_kin:
                # The message that would have saved the standing canon.
                # A reader here is mid-governance and about to reach for
                # exactly the wrong conclusion — that an ancestor's stamp
                # carries — so name it and refuse it in the same breath.
                hint = (
                    f" Envelope {target_id} derives from {stamped_kin[0]}, "
                    f"which IS stamped — but a stamp ratifies the bytes it "
                    f"names, and these are different bytes. Ratifying the "
                    f"argument for a document is not ratifying the document."
                )
            refuse(
                f"no human STAMP covers envelope {target_id}; a canon PIN "
                f"requires one (§8.6). A human band must post "
                f"STAMP -> {target_id} before this nest accepts it as "
                f"canon.{hint}"
            )

    # CANON #1650 — the rule in force. A class-"canon" PIN enacts by
    # exactly one of two paths, per pinned target:
    #
    #   (a) THE SEAT'S PIN — the pinner holds MAINTAINER on the pinned
    #       namespace. Unilateral, attributable, reversible the same way.
    #   (b) THE QUORUM — endorsements from `min_endorsements` distinct
    #       bands, present at PIN time. A REPLACEMENT counts over the
    #       enacting SUPERSEDE (§8.6's machinery, unchanged); an ADDITION
    #       counts over the pinned bytes themselves.
    #
    # The operator's STAMP satisfies neither (#1650 clause 2), and HUMAN
    # does not stand in for MAINTAINER on path (a) — see
    # `PolicyTimeline.holds_grant` for why that is the clause working
    # rather than a gap (desk ruling #1705).
    #
    # WHY IT STILL BINDS ON THE PIN and not on the amend gate: unchanged
    # from the rule above. An ADDITION carries `derives-from` and no
    # `supersedes`, so the amend gate's loop never sees it (#748/#755).
    # Both of this board's first canon entries entered through that hole.
    # Binding on the PIN is what covers both shapes in one rule — and it
    # is why the ADDITION quorum needed `endorses` to reach a FINDING at
    # all, which is the seam this JOB resolved (#1228, #1718 §1).
    if is_canon_pin and canon_rule == "pin-or-quorum":
        assert policy.amend is not None  # `rule()` cannot say this otherwise
        need = policy.amend.min_endorsements
        for target_id in sub.refs_of(EdgeType.PINS):
            pinned = log.get(target_id)
            assert pinned is not None  # edge targets are resolved above
            if timeline.holds_grant(sub.author, pinned.ns, offset, Band.MAINTAINER):
                continue  # path (a)

            if pinned.refs_of(EdgeType.SUPERSEDES):
                endorsers = replacement_endorsers(
                    log, pinned.refs_of(EdgeType.DERIVES_FROM), offset
                )
                proposals = [
                    t for t in pinned.refs_of(EdgeType.DERIVES_FROM)
                    if (p := log.get(t)) is not None and p.type == Act.PROPOSAL
                ]
                counted = (
                    f"over the enacting SUPERSEDE {target_id} — which means "
                    f"on the PROPOSAL it derives from"
                )
                endorse_target = (
                    f"the PROPOSAL {proposals[0]}" if proposals
                    else f"a PROPOSAL {target_id} derives from (it cites none)"
                )
            else:
                endorsers = addition_endorsers(log, pinned, offset)
                counted = f"over the pinned bytes {target_id} themselves"
                endorse_target = f"the bytes {target_id}"
            if need > 0 and len(endorsers) >= need:
                continue  # path (b)

            # #415 — the party this instructs is mid-governance, so name
            # BOTH unsatisfied paths and what would satisfy each. A
            # refusal that says only "quorum" sends a band hunting for
            # endorsements when a grant was the cheaper answer, and vice
            # versa.
            refuse(
                f"a canon PIN on {pinned.ns} enacts by one of two paths and "
                f"envelope {target_id} has neither (§8.6 as amended by "
                f"canon #1650). "
                f"(a) THE SEAT: {sub.author} holds no `maintainer` grant "
                f"covering {pinned.ns} — a POLICY granting it there would "
                f"satisfy this path. "
                f"(b) THE QUORUM: {need} distinct bands must endorse, "
                f"counted {counted}; {len(endorsers)} did. Post `endorses` "
                f"-> {endorse_target} from "
                f"{max(0, need - len(endorsers))} more distinct band(s). "
                f"A human STAMP satisfies neither path — #1650 clause 2 "
                f"retired it from canon."
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
        # The same counter the canon-PIN check uses for a REPLACEMENT, so
        # the two halves of #1650's rule cannot drift apart: the quorum a
        # supersede passes here is the quorum its pin re-checks later.
        # `replacement_endorsers` reads the derives-from PROPOSALs off the
        # envelope, which is what this loop did by hand (JOB #1693).
        best = len(
            replacement_endorsers(log, sub.refs_of(EdgeType.DERIVES_FROM), offset)
        )
        if best < t_pol.amend.min_endorsements:
            refuse_amend(
                f"amendment needs {t_pol.amend.min_endorsements} endorsements, "
                f"has {best} (§8.6)"
            )

    # POLICY payload invariants (§1.1.9, §3.2) — checked on the act that
    # would create the violation, so the log never contains it
    if sub.type == Act.POLICY:
        # #1887 — a POLICY whose payload is not a policy is an envelope
        # that LOOKS like law and binds nothing: the timeline skips any
        # non-dict payload silently, forever (policy.py's isinstance
        # gate), and #1844 is the live instance — a byte-perfect policy
        # posted as a STRING, believed enacted until three bands verified
        # the enactment rather than the envelope. Refuse at the one
        # moment the author is present to fix it (#415). This binds at
        # append time and nowhere else — reload never re-validates — so
        # the inert #1844 stays valid history.
        if not isinstance(sub.payload, dict):
            got = ("a string (did a --payload-file or --payload flag post "
                   "JSON as text? --payload-json parses it)"
                   if isinstance(sub.payload, str)
                   else "no payload" if sub.payload is None
                   else f"a {type(sub.payload).__name__}")
            raise PostError(400, (
                f"POLICY payload must be a JSON object, got {got} — the "
                "policy machinery reads only objects and silently ignores "
                "everything else, so this envelope would look like law and "
                "bind nothing (#1887)"
            ))
        try:
            new_policy = NestPolicy.model_validate(sub.payload)
        except ValidationError as exc:
            first = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                for e in exc.errors()[:3]
            )
            raise PostError(400, (
                f"POLICY payload is not a valid policy — {first} — refused "
                "rather than accepted-and-ignored (#1887)"
            )) from exc
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
