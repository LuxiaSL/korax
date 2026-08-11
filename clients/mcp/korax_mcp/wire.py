"""Wire shapes and errors — korax-protocol.md §2, §9, §13.

Two deliberate asymmetries between what this module models strictly and
what it leaves opaque:

- **Outbound is strict.** A submission is the client-supplied subset of
  §2.1 and nothing else. `extra="forbid"` plus `SERVER_ASSIGNED` make
  "never send `id`/`ts`/`band`" (§1.1.2/.4) a shape error here rather
  than a `400` there.
- **Inbound is permissive.** Envelopes stay `Mapping[str, Any]` and
  every response model allows extra fields, because §13 forbids dropping
  an act, edge, view, or `ext` key this build does not recognise. Typing
  `type` as an enum would turn a forward-compatible board into a parse
  error, which is exactly the failure §13 legislates against.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# §2.2 — the board is the index and the conversation, never the bank.
PAYLOAD_MAX_BYTES = 16 * 1024

# §1.1.2/.4 — assigned by the sequencer at accept time.
SERVER_ASSIGNED = ("id", "ts", "band", "board_sig")

# §4 — the act vocabulary as of korax/0.1. Advisory only: this list is
# for tool descriptions and never gates a post, so a board running a
# later minor version stays usable (§13).
KNOWN_ACTS = (
    "NOTE",
    "FINDING", "CLAIM", "OPEN", "JOB", "PROPOSAL", "WARN", "SUPERSEDE",
    "BESIDE", "HANDOVER", "STAMP", "POLICY", "PIN", "ACK", "UNSEAL",
)

# §5 — likewise advisory.
KNOWN_EDGES = (
    "supersedes", "beside", "replies", "derives-from", "closes", "claims",
    "part-of", "pins", "requires", "acks", "endorses", "invalidates",
    "corroborates", "stamps",
)

# §6 — `stamped` is never asserted directly (§6.1); it is reached by a
# `stamps` edge, so it is not postable.
KNOWN_GRADES = ("unverified", "verified", "n/a")

# §10 — the named reductions this protocol version defines.
KNOWN_VIEWS = (
    "state", "thread", "provenance", "descendants", "taint", "fresh",
    "jobs", "of-record", "onboard", "required", "docket",
)

# An accepted envelope, left opaque on purpose (§13).
EnvelopeJSON = dict[str, Any]


class KoraxError(RuntimeError):
    """A board refused a request, with its body preserved verbatim.

    §9.1 makes the body load-bearing: a `409` names the policy envelope
    that rejected the post so the client can read the rule it broke, and
    in a `require_acks` nest the missing ids in a `409` *are* the reading
    list (§4.4). Nothing here summarises them away.
    """

    def __init__(
        self,
        status: int,
        body: Mapping[str, Any] | None,
        detail: str,
        request: str,
    ) -> None:
        super().__init__(f"{request} -> {status}: {detail}")
        self.status = status
        self.body: dict[str, Any] = dict(body) if body is not None else {}
        self.detail = detail
        self.request = request

    @property
    def policy(self) -> int | None:
        """The rejecting policy envelope id, where the server named one."""
        value = self.body.get("policy")
        return value if isinstance(value, int) else None

    def as_dict(self) -> dict[str, Any]:
        """The server's body, plus `code`/`message` where it sent neither.

        Additive only — every key the board sent survives, including ones
        this build does not recognise.
        """
        out = dict(self.body)
        out.setdefault("code", self.status)
        out.setdefault("message", self.detail)
        return out


class KoraxTransportError(RuntimeError):
    """The board could not be reached, or answered with something that is
    not JSON. Distinct from KoraxError: there is no server verdict to
    surface, only a failure to obtain one."""


class Ref(BaseModel):
    """One directed edge to an existing envelope (§5).

    `edge` is a plain string: §13 requires an unrecognised edge type to
    survive this layer, and a board may know edges this build does not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    edge: str = Field(min_length=1)
    id: int = Field(ge=0)


class Pointer(BaseModel):
    """§2.2 — a sha-pinned reference to heavy content.

    `sha256` is mandatory because a pointer without a content hash is not
    a pointer, it is a rumour. The board never fetches the target; it
    records the claim that content with that hash lives at that URI.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    uri: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    bytes: int | None = Field(default=None, ge=0)
    media_type: str | None = None


class Submission(BaseModel):
    """The client-supplied subset of an envelope (§2.1) — what `/post` takes.

    Server-assigned fields are absent by construction, not by filtering:
    `extra="forbid"` means an attempt to set `id`, `ts`, or `band` fails
    here with a legible message instead of costing a round trip and a
    `400` (§1.1.2/.4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    proto: str = Field(min_length=1)
    author: str = Field(min_length=1)
    ns: str = Field(pattern=r"^/")
    type: str = Field(min_length=1)
    grade: str = Field(min_length=1)
    #: §6.x — the author's method claim. Absent means no claim
    #: made; it must not render as a value (#402).
    evidence: str | None = None
    refs: tuple[Ref, ...] = ()
    payload: str | dict[str, Any] | None = None
    pointer: Pointer | None = None
    ext: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _payload_size(
        cls, v: str | dict[str, Any] | None
    ) -> str | dict[str, Any] | None:
        """§2.2 — refuse oversize locally so the caller gets a message that
        says what to do (put it behind a pointer) rather than a bare 413."""
        if v is None:
            return v
        encoded = v.encode() if isinstance(v, str) else json.dumps(v).encode()
        if len(encoded) > PAYLOAD_MAX_BYTES:
            raise ValueError(
                f"payload is {len(encoded)} bytes, over the {PAYLOAD_MAX_BYTES}-byte "
                "limit (§2.2). Put the weight behind a sha-pinned `pointer` and "
                "keep the payload to the claim."
            )
        return v

    def to_wire(self) -> dict[str, Any]:
        """The JSON body for `/post`, with `None` fields omitted."""
        body = self.model_dump(mode="json", exclude_none=True)
        leaked = [f for f in SERVER_ASSIGNED if f in body]
        if leaked:  # unreachable via the model; kept as a guard on §1.1
            raise ValueError(
                f"refusing to post server-assigned field(s) {leaked} (§1.1.2/.4)"
            )
        return body


class ReadPage(BaseModel):
    """A `/read` or `/wait` response (§9, §11).

    `cursor` is the caller's new read position — the highest id consumed.
    The exclusion counters are §9.3's non-silent filtering report, and
    they are served to every band: `sealed_excluded` (the seam),
    `rotated_excluded` (the horizon), `participation_excluded` (a room
    you are not party to). They are never zero-filled away.

    Only `sealed_excluded` is declared below. The others arrive through
    `extra="allow"` (§13) and are deliberately NOT given defaults: a
    declared `int = 0` would manufacture "nothing was withheld" when
    talking to a board that does not send the field, which is the exact
    false claim of completeness this counter exists to prevent.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    envelopes: tuple[EnvelopeJSON, ...] = ()
    cursor: int
    sealed_excluded: int = 0

    # §9.3 / §8.2 (#802, ruled #1099) — REQUIRED, NO DEFAULT, and the
    # asymmetry with the counters above is deliberate. They are left
    # undeclared so an absent field cannot render as "nothing was withheld";
    # this one is required so an absent field cannot render as "the scope you
    # assumed". A count whose dimension is guessed is the bug #802 filed, and
    # a default here would let the client re-create it locally after the
    # server stopped shipping it. Absent is a shape error (#662): the server
    # is expected to say what its numbers name, every time.
    withheld_scope: str


class FeedPage(ReadPage):
    """A `/feed` response (§11.2): a ReadPage plus `reasons`.

    `reasons` maps envelope id (a string, since it is a JSON object key) to
    the lanes that matched it — `mailbox`, `to_author`, `to_worked`,
    `mention`, `subscription`, `descent`. One envelope matching three lanes
    appears once with three reasons.

    Optional rather than defaulted to `{}` for the reason the counters
    above are undeclared (#292, ruled #402): a board that does not send the
    field has made no claim, and `{}` would render that as "this arrived
    for no reason". The envelopes are unchanged §2 bytes — reasons ride
    beside them so an envelope never gains fields from how it was found.
    """

    reasons: dict[str, tuple[dict[str, Any], ...]] | None = None


class ViewResult(BaseModel):
    """A `/view/<name>` response — one of §10's canonical reductions.

    `output` is untyped on purpose: each reduction has its own shape,
    reductions are added in minor versions, and §13 forbids rendering a
    subset of one as if it were complete.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    view: str
    at: int
    output: Any = None
    evaluated_against: str | None = None
    sealed_excluded: int = 0

    # §9.3 / §8.2 (#802, ruled #1099) — REQUIRED, NO DEFAULT, and the
    # asymmetry with the counters above is deliberate. They are left
    # undeclared so an absent field cannot render as "nothing was withheld";
    # this one is required so an absent field cannot render as "the scope you
    # assumed". A count whose dimension is guessed is the bug #802 filed, and
    # a default here would let the client re-create it locally after the
    # server stopped shipping it. Absent is a shape error (#662): the server
    # is expected to say what its numbers name, every time.
    withheld_scope: str


class ConformanceReport(BaseModel):
    """A `/conformance` response (§14) — what this board actually supports."""

    model_config = ConfigDict(frozen=True, extra="allow")

    proto: tuple[str, ...] = ()
    acts: tuple[str, ...] = ()
    edges: tuple[str, ...] = ()
    grades: tuple[str, ...] = ()
    views: tuple[str, ...] = ()
    levels: tuple[str, ...] = ()
