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

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class ReadPage(BaseModel):
    """A `/read` or `/wait` page. `cursor` is the §11 read position — the
    highest id consumed — and `sealed_excluded` is §8.7.5's promise that
    a filtered projection never renders as complete."""

    model_config = ConfigDict(extra="allow")

    envelopes: tuple[Envelope, ...] = ()
    cursor: int
    sealed_excluded: int = 0


class ViewResult(BaseModel):
    """A `/view/<name>` response (§9.2, §10). `output` is intentionally
    untyped: each reduction has its own shape and a client that narrowed
    it would be filtering a projection it presents as complete (§13)."""

    model_config = ConfigDict(extra="allow")

    view: str
    at: int
    output: Any = None
    evaluated_against: str | None = None
    sealed_excluded: int = 0


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
