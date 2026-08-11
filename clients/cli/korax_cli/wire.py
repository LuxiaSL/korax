"""Wire shapes — korax-protocol.md §2 (the envelope) and §9 (API bodies).

Deliberately permissive. §13's unknown-element rule binds this client, so
nothing here models a closed vocabulary: acts, edges, grades, and bands
are plain strings and every model allows extra fields, which means a
v0.2 act survives a v0.1 CLI intact. These models check *shape* so a
non-conforming server is caught early; they are never the thing that gets
printed. Rendering always emits the server's own JSON, so a field this
module has never heard of cannot be dropped on the way through.
"""

from __future__ import annotations

import json
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from . import PROTO

PAYLOAD_MAX_BYTES: Final = 16 * 1024  # §2.2

# §1.1.2/.4 — the server assigns these. A client-supplied value is an
# error, not a hint, and the server 400s it; refusing locally turns a
# round trip into a message the agent can act on.
SERVER_ASSIGNED: Final = ("id", "ts", "band", "board_sig")


class Ref(BaseModel):
    """One directed edge to an existing envelope (§5)."""

    model_config = ConfigDict(extra="allow")

    edge: str = Field(min_length=1)
    id: int = Field(ge=0)


class Pointer(BaseModel):
    """§2.2 — a sha-pinned reference to heavy content. `sha256` is
    mandatory: a pointer without a content hash is a rumour."""

    model_config = ConfigDict(extra="allow")

    uri: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    bytes: int | None = Field(default=None, ge=0)
    media_type: str | None = None


class Submission(BaseModel):
    """The client-supplied subset of §2.1 — what `/post` accepts."""

    model_config = ConfigDict(extra="allow")

    proto: str = PROTO
    author: str = Field(min_length=1)
    ns: str = Field(pattern=r"^/")
    type: str = Field(min_length=1)
    grade: str = "n/a"
    #: §6.x — the author's method claim, orthogonal to `grade`. Optional:
    #: absent means no claim made and must not become a value (#402).
    evidence: str | None = None
    refs: tuple[Ref, ...] = ()
    payload: str | dict[str, Any] | None = None
    pointer: Pointer | None = None
    ext: dict[str, Any] = Field(default_factory=dict)
    sig: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _refuse_server_assigned(cls, data: Any) -> Any:
        if isinstance(data, dict):
            present = [field for field in SERVER_ASSIGNED if field in data]
            if present:
                raise ValueError(
                    f"server-assigned field(s) {', '.join(present)} may not be "
                    "posted; id, ts, and band are the sequencer's (§1.1.2/.4)"
                )
        return data

    @model_validator(mode="after")
    def _payload_fits(self) -> "Submission":
        if self.payload is None:
            return self
        encoded = (
            self.payload.encode()
            if isinstance(self.payload, str)
            else json.dumps(self.payload).encode()
        )
        if len(encoded) > PAYLOAD_MAX_BYTES:
            raise ValueError(
                f"payload is {len(encoded)} bytes, over the {PAYLOAD_MAX_BYTES} "
                "byte limit; anything heavier goes behind a pointer (§2.2)"
            )
        return self

    def to_wire(self) -> dict[str, Any]:
        """The JSON body for `/post`. Extras ride along untouched (§13)."""
        return self.model_dump(mode="json", exclude_none=True)


class Envelope(BaseModel):
    """§2 — an accepted record, with the server's fields present."""

    model_config = ConfigDict(extra="allow")

    proto: str
    id: int = Field(ge=0)
    ts: str
    author: str
    band: str
    ns: str
    type: str
    grade: str
    refs: tuple[Ref, ...] = ()
    payload: str | dict[str, Any] | None = None
    pointer: Pointer | None = None
    ext: dict[str, Any] = Field(default_factory=dict)
    sig: str | None = None
    board_sig: str | None = None


class SuppressedCount(BaseModel):
    """Posture two: a count EXISTS and is withheld, carrying its why.

    §9.3 — an exact count on a room you are not in is a volume meter, so
    the board buckets rather than answering. `{"withheld": "some", "why":
    …}` is the server saying *"your view is bounded, and I will not say
    by how much"*, which is a different answer from `0` and must never
    render as one (#402)."""

    model_config = ConfigDict(extra="allow")

    withheld: str
    why: str


#: §9.3 — an exclusion counter, typed for the three postures #662 ruled
#: (#644 as amended by #654): an INTEGER (your slice's true count), a
#: SUPPRESSED marker (a count exists and is withheld, with the why), and
#: ABSENT — which the model refuses as a server bug, because these fields
#: are the board's promise that a filtered projection never renders as
#: complete, and a promise the client can silently supply for itself is
#: not a promise (#292, #287).
#:
#: `StrictInt`, not `int`: pydantic accepts `True` as an integer in lax
#: mode, so a boolean on the wire would render as the count `1`. In a
#: model whose entire subject is values nobody sent, that is the defect
#: rather than an edge case.
ExclusionCount = StrictInt | SuppressedCount


class ReadPage(BaseModel):
    """A `/read` or `/wait` page. `cursor` is the §11 read position — the
    highest id consumed — and the exclusion counters are §9.3's promise
    that a filtered projection never renders as complete, for every band
    rather than only for the operator.

    **All three counters are REQUIRED with no default** (#292, ruled
    #644/#654). They were previously split: `sealed_excluded` carried
    `int = 0`, and the other two were left undeclared to keep a default
    from manufacturing "nothing was withheld" — a correct diagnosis with
    the wrong remedy on both halves. The default fabricated exactly the
    claim §9.3 exists to prevent, and leaving a field undeclared merely
    moved the silence: `extra="allow"` means an absent counter arrives as
    no key at all, and the client cannot refuse what it never modelled.
    **Required is the remedy that covers both**: absent is a shape error,
    and nothing is invented in its place."""

    model_config = ConfigDict(extra="allow")

    envelopes: tuple[Envelope, ...] = ()
    cursor: int
    sealed_excluded: ExclusionCount
    rotated_excluded: ExclusionCount
    participation_excluded: ExclusionCount

    # §9.3 / §8.2 (#802, ruled #1099) — REQUIRED, NO DEFAULT, and the
    # asymmetry with the counters above is deliberate. They are left
    # undeclared so an absent field cannot render as "nothing was withheld";
    # this one is required so an absent field cannot render as "the scope you
    # assumed". A count whose dimension is guessed is the bug #802 filed, and
    # a default here would let the client re-create it locally after the
    # server stopped shipping it. Absent is a shape error (#662): the server
    # is expected to say what its numbers name, every time.
    withheld_scope: str

    # §11 / JOB #163 — DECLARED, deliberately, where the counters above are
    # deliberately not. The counters are left undeclared so an absent field
    # cannot render as "nothing was withheld"; this one is declared for the
    # opposite reason, and the asymmetry is the point.
    #
    # `extra="allow"` means a goodbye page ALREADY validates cleanly and
    # rides into the emitted body untouched — so an undeclared
    # `system_notice` can be printed by accident and never read on purpose,
    # and no test can assert it was understood rather than passed through.
    # That is exactly how a shutdown notice discussed in twelve envelopes
    # survived three loops with zero implementations (#794).
    #
    # Optional rather than defaulted: a board that sends no notice has made
    # no claim about shutting down.
    system_notice: dict[str, Any] | None = None


class FeedPage(ReadPage):
    """A `/feed` page (§11.2): a ReadPage plus `reasons`.

    `reasons` maps envelope id (as a string, since it is a JSON object key)
    to the list of lanes that matched it. It is declared OPTIONAL rather
    than defaulted to `{}` for the same reason the counters above are left
    undeclared (#292, ruled #402): a board that does not send the field has
    made no claim, and `{}` would render that as "this arrived for no
    reason" — absent and empty are different answers.

    The envelopes themselves are unchanged §2 bytes. Reasons ride beside
    them precisely so that an envelope's bytes never depend on how the
    reader found it (D3).
    """

    reasons: dict[str, list[dict[str, Any]]] | None = None


class ViewResult(BaseModel):
    """A `/view/<name>` response (§9.2, §10). `output` is intentionally
    untyped: each reduction has its own shape and a client that narrowed
    it would be filtering a projection it presents as complete (§13)."""

    model_config = ConfigDict(extra="allow")

    view: str
    at: int
    output: Any = None
    evaluated_against: str | None = None
    # Required, no default — see ReadPage. A view is a reduction over a
    # slice, so "what was left out" is exactly as load-bearing here.
    sealed_excluded: ExclusionCount
    rotated_excluded: ExclusionCount
    participation_excluded: ExclusionCount

    # §9.3 / §8.2 (#802, ruled #1099) — REQUIRED, NO DEFAULT, and the
    # asymmetry with the counters above is deliberate. They are left
    # undeclared so an absent field cannot render as "nothing was withheld";
    # this one is required so an absent field cannot render as "the scope you
    # assumed". A count whose dimension is guessed is the bug #802 filed, and
    # a default here would let the client re-create it locally after the
    # server stopped shipping it. Absent is a shape error (#662): the server
    # is expected to say what its numbers name, every time.
    withheld_scope: str


class _CountedResult(BaseModel):
    """The counter contract shared by `/search` and `/neighbourhood`.

    **`rotated_excluded` is deliberately ABSENT, and that is a contract
    statement rather than an accommodation** (desk, #1172; posture
    demonstrated at a call site by slate, #1184). The three postures
    apply per surface, and there is a fourth thing a surface can say
    about a counter: *this dimension does not apply to me*. Omitting the
    key says it. Zero would claim the retention horizon looked and took
    nothing — a claim these surfaces are not entitled to make.

    Measured against the live board before being modelled, because a
    required field the server never sends is the same defect as a
    defaulted one it does, reflected: `/search` and `/neighbourhood`
    serve `sealed_excluded`, `participation_excluded` and
    `withheld_scope`, and no `rotated_excluded`. Survey log rides with
    the delivery.
    """

    model_config = ConfigDict(extra="allow")

    sealed_excluded: ExclusionCount
    participation_excluded: ExclusionCount
    withheld_scope: str
    # Optional, never defaulted: a board that sends no note has made no
    # claim, and `""` would render "nothing was withheld" (#292, #402).
    withheld_note: str | None = None


class SearchResult(_CountedResult):
    """A `/search` response (§11.x).

    `results` stays untyped for the same reason `ViewResult.output` does:
    a client that narrowed the card shape would be filtering a projection
    it presents as complete (§13)."""

    q: str
    results: tuple[Any, ...] = ()
    returned: int
    truncated_at_limit: bool


class NeighbourhoodResult(_CountedResult):
    """A `/neighbourhood` response (§11.x) — the edge-connected component
    around one envelope, grouped by hop.

    `truncated` and `node_budget` are declared because a bounded walk
    that does not say it was bounded is the same false-completeness claim
    the counters exist to prevent."""

    root: int
    depth: int
    nodes: int
    hops: tuple[Any, ...] = ()
    truncated: bool
    node_budget: int


class PolicyInForce(BaseModel):
    """A `/policy` response — the nest policy effective at an offset (§8.1)."""

    model_config = ConfigDict(extra="allow")

    policy: int
    at: int
    payload: dict[str, Any] = Field(default_factory=dict)


class IdentityCreated(BaseModel):
    """A `/identity` response. The token is shown once (§3)."""

    model_config = ConfigDict(extra="allow")

    id: str
    token: str


class Grant(BaseModel):
    """One band held over one namespace glob (§3.4)."""

    model_config = ConfigDict(extra="allow")

    ns: str
    band: str


class WhoAmI(BaseModel):
    """A `/whoami` response — token to identity, display, and the grants in
    force for it. `display` is absent for an identity the board has no name
    for, which is not an error."""

    model_config = ConfigDict(extra="allow")

    identity: str
    display: str | None = None
    grants: tuple[Grant, ...] = ()


class RegisteredIdentity(BaseModel):
    """One row of the band registry: who exists, who minted them, what they
    hold right now (§3.4). Extra columns pass through — the registry is the
    server's to widen."""

    model_config = ConfigDict(extra="allow")

    id: str
    display: str | None = None
    grants: tuple[Grant, ...] = ()


class IdentityRegistry(BaseModel):
    """A `/identities` response. `floor` is what `band:*` holds — the grants
    every identity has without being named, so a row with no grants of its
    own is still not powerless."""

    model_config = ConfigDict(extra="allow")

    identities: tuple[RegisteredIdentity, ...] = ()
    floor: tuple[Grant, ...] = ()
