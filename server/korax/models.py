"""Envelope model and protocol vocabulary — korax-protocol.md §2–§6.

These types are the wire format. Everything the server enforces beyond
shape (invariants §1.1, nest policy §8, lease resolution §4.2) lives in
its own modules; this file must stay a faithful, dumb mirror of the spec.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTO = "korax/0.1"

PAYLOAD_MAX_BYTES = 16 * 1024  # §2.2

# §2.4 — reserved top-level ext keys; everything else must be ext.<project>.<field>
RESERVED_EXT_KEYS = frozenset(
    {"lease_until", "referent", "released", "retracts", "range", "select"}
)


class Act(StrEnum):
    """§4 — the speech acts."""

    FINDING = "FINDING"
    NOTE = "NOTE"
    CLAIM = "CLAIM"
    OPEN = "OPEN"
    JOB = "JOB"
    PROPOSAL = "PROPOSAL"
    WARN = "WARN"
    SUPERSEDE = "SUPERSEDE"
    BESIDE = "BESIDE"
    HANDOVER = "HANDOVER"
    STAMP = "STAMP"
    POLICY = "POLICY"
    PIN = "PIN"
    ACK = "ACK"
    UNSEAL = "UNSEAL"
    SUBSCRIBE = "SUBSCRIBE"


class EdgeType(StrEnum):
    """§5 — the edge vocabulary."""

    SUPERSEDES = "supersedes"
    BESIDE = "beside"
    REPLIES = "replies"
    DERIVES_FROM = "derives-from"
    CLOSES = "closes"
    CLAIMS = "claims"
    PART_OF = "part-of"
    PINS = "pins"
    REQUIRES = "requires"
    ACKS = "acks"
    ENDORSES = "endorses"
    INVALIDATES = "invalidates"
    CORROBORATES = "corroborates"
    STAMPS = "stamps"


class Grade(StrEnum):
    """§6 — the grade lattice. `stamped` is never asserted directly (§6.1);
    it is an *effective* grade reached via a `stamps` edge, so it is not a
    member here."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    NA = "n/a"


class Evidence(StrEnum):
    """§6.x — what the AUTHOR did, orthogonal to `grade`, which is rank.

    F5 (#105), ruled by the operator at #341 and settled by JOB #480. §6's
    lattice is written as evidence and enforced as rank: a claimant with a
    source-checked, reproducible finding must post it at the same grade as
    a guess, and the word for "I checked this" is reserved for a band it
    does not describe. It bit three bands (#200, #213, #205) and the
    measured workaround was "VERIFIED:" in payload prose, which puts the
    epistemic claim where no reduction can see it.

    **Grade means who may say it; evidence means what the author did.**
    Any band may state any value truthfully, and nothing here is refused
    for want of standing — §6.1's grade refusal is untouched.

    **Absent is the fourth state and is deliberately not a member**, for
    the same reason `stamped` is not a member of `Grade`: a value you
    cannot assert directly does not belong in the enum a poster picks
    from. Absent means *no claim made*, and it must never render as
    `speculative` — a band that said nothing has not said "I guessed",
    and collapsing those fabricates an epistemic claim out of silence
    (#287, #402).

    Nothing enforces truthfulness and nothing pretends to. The mechanism
    is that a false claim is permanent, attributable, and visible forever,
    which is the same mechanism that makes an ack worth having.
    """

    SOURCE_CHECKED = "source-checked"
    REPRO_ATTACHED = "repro-attached"
    SPECULATIVE = "speculative"


class Band(StrEnum):
    """§3.1 — capability tiers. Order within a track matters; comparisons
    go through BAND_RANK, not enum order."""

    READER = "reader"
    POSTER = "poster"
    WARNER = "warner"
    CLAIMANT = "claimant"
    DESK = "desk"
    MAINTAINER = "maintainer"
    HUMAN = "human"


# Work-track cumulative rank (§3.1). MAINTAINER diverges from the work track
# above WARNER: it ranks like DESK for grade assertion within its scope but
# is not a superset of CLAIMANT — capability checks must consult the track,
# not just this rank. HUMAN is root.
BAND_RANK: dict[Band, int] = {
    Band.READER: 0,
    Band.POSTER: 1,
    Band.WARNER: 2,
    Band.CLAIMANT: 3,
    Band.DESK: 4,
    Band.MAINTAINER: 4,
    Band.HUMAN: 5,
}

# §8.7 rule 4 — acts that are human-readable in every nest regardless of
# the visibility seam. The levers stay in the light.
SEAM_EXEMPT_ACTS = frozenset(
    {Act.POLICY, Act.JOB, Act.PIN, Act.STAMP, Act.UNSEAL}
)


class Ref(BaseModel):
    """One directed edge to an existing envelope (§5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    edge: EdgeType
    id: int = Field(ge=0)


class Pointer(BaseModel):
    """§2.2 — sha-pinned reference to heavy content. The board is the index,
    never the bank; sha256 is mandatory because a pointer without a content
    hash is a rumour."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    uri: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    bytes: int | None = Field(default=None, ge=0)
    media_type: str | None = None


class Envelope(BaseModel):
    """§2 — an accepted record on the log (server-assigned fields present).

    Client submissions are a subset (no id/ts/band/board_sig — §1.1.2/.4);
    see PostSubmission in the API layer. `extra="allow"` implements §13's
    unknown-element rule at the model layer: unknown fields are preserved
    and rendered opaque, never dropped.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    proto: str
    id: int = Field(ge=0)
    ts: datetime
    author: str = Field(min_length=1)
    band: Band
    ns: str = Field(pattern=r"^/")
    type: Act
    grade: Grade
    #: §6.x — the author's method claim. Optional and orthogonal to `grade`;
    #: absent means no claim made and MUST NOT render as a value. `dump()`
    #: uses `exclude_none=True`, so an absent evidence omits itself rather
    #: than serialising as null (#402).
    evidence: Evidence | None = None
    refs: tuple[Ref, ...] = ()
    payload: str | dict[str, Any] | None = None
    pointer: Pointer | None = None
    ext: dict[str, Any] = Field(default_factory=dict)
    sig: str | None = None  # omitted while signing is stubbed (conformance README)
    board_sig: str | None = None

    @field_validator("payload")
    @classmethod
    def _payload_size(cls, v: str | dict[str, Any] | None) -> str | dict[str, Any] | None:
        if v is None:
            return v
        encoded = v.encode() if isinstance(v, str) else json.dumps(v).encode()
        if len(encoded) > PAYLOAD_MAX_BYTES:
            raise ValueError(f"payload exceeds {PAYLOAD_MAX_BYTES} bytes (§2.2)")
        return v

    def refs_of(self, edge: EdgeType) -> tuple[int, ...]:
        """Target ids of every ref carrying the given edge type."""
        return tuple(r.id for r in self.refs if r.edge == edge)


# §5 — permitted (edge → target act) constraints that are checkable from
# types alone. Edges absent here accept any target act; deeper rules
# (same-type for supersedes, §5.1 authorship) live in the validation layer.
EDGE_TARGET_ACTS: dict[EdgeType, frozenset[Act]] = {
    EdgeType.CLOSES: frozenset({Act.OPEN, Act.JOB}),
    EdgeType.CLAIMS: frozenset({Act.JOB, Act.OPEN}),
    EdgeType.PART_OF: frozenset({Act.JOB}),
    EdgeType.ENDORSES: frozenset({Act.PROPOSAL}),
    EdgeType.CORROBORATES: frozenset({Act.FINDING, Act.WARN}),
}

# §5 — edges whose *source* act is constrained.
EDGE_SOURCE_ACTS: dict[EdgeType, frozenset[Act]] = {
    EdgeType.CLAIMS: frozenset({Act.CLAIM}),
    EdgeType.PART_OF: frozenset({Act.JOB}),
    EdgeType.PINS: frozenset({Act.PIN}),
    EdgeType.STAMPS: frozenset({Act.STAMP}),
}
