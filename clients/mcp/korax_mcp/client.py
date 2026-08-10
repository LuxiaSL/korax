"""The HTTP client for one board — korax-protocol.md §9.

One method per endpoint, no caching, no derived state. Reductions are
server endpoints and are canonical (§9.2): computing `state` locally
would let two desks both "read the board" and disagree about what it
says, which is the coordination failure the substrate exists to remove.

The transport is injectable so the whole layer can be exercised against
an in-process board over ASGI, with no socket and no fixture server.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from .config import KoraxConfig
from .wire import (
    ConformanceReport,
    EnvelopeJSON,
    KoraxError,
    KoraxTransportError,
    Pointer,
    ReadPage,
    Ref,
    Submission,
    ViewResult,
)

# A long-poll must not be cut off by the transport before the board's own
# deadline; §11's contract is that `wait` returns at `timeout`, empty.
WAIT_SLACK_SECONDS = 15.0

M = TypeVar("M", bound=BaseModel)


def _params(**kwargs: Any) -> dict[str, Any]:
    """Query params with unset filters dropped — an absent filter and a
    filter set to null are different requests."""
    return {k: v for k, v in kwargs.items() if v is not None}


class KoraxClient:
    """An authenticated connection to one Korax board.

    Args:
        config: url, token, and the identity the token belongs to.
        transport: optional httpx transport. Tests pass an
            `httpx.ASGITransport` wrapping the reference server; production
            leaves it unset and httpx opens real connections.
    """

    def __init__(
        self,
        config: KoraxConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._http = httpx.AsyncClient(
            base_url=config.url,
            transport=transport,
            timeout=config.request_timeout,
            headers={
                "Authorization": config.bearer(),
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def rebind(self, identity: str, token: str) -> None:
        """Swap this connection's credential in place — R18 enlist: the
        session that minted a band becomes it, no restart, no config
        write. The previous token is simply dropped."""
        from pydantic import SecretStr

        self.config = self.config.model_copy(
            update={"identity": identity, "token": SecretStr(token)}
        )
        self._http.headers["Authorization"] = f"Bearer {token}"

    # -- identity (§9 /identity, R18) ----------------------------------------

    async def create_identity(self, display: str) -> dict[str, Any]:
        """Mint a new band. Open to any authenticated identity; the
        token in the response is shown exactly once."""
        raw = await self._request("POST", "/identity", body={"display": display})
        if not isinstance(raw, dict):
            raise KoraxTransportError("POST /identity: expected an object")
        return raw

    async def __aenter__(self) -> KoraxClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # -- transport ---------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        timeout: float | None = None,
    ) -> Any:
        """One round trip. Raises KoraxError on a server verdict,
        KoraxTransportError when there is no verdict to be had."""
        where = f"{method} {path}"
        try:
            response = await self._http.request(
                method,
                path,
                params=dict(params) if params else None,
                json=body,
                timeout=timeout if timeout is not None else self.config.request_timeout,
            )
        except httpx.HTTPError as exc:
            raise KoraxTransportError(
                f"{where}: could not reach the board at {self.config.url} ({exc})"
            ) from exc

        payload: Any = None
        decoded = True
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            decoded = False

        if response.status_code >= 400:
            body_map = payload if isinstance(payload, Mapping) else None
            detail = _detail(body_map, response, decoded)
            raise KoraxError(response.status_code, body_map, detail, where)

        if not decoded:
            raise KoraxTransportError(
                f"{where}: expected JSON, got {response.headers.get('content-type')!r}"
            )
        return payload

    # -- write (§9 /post) ---------------------------------------------------

    async def post(
        self,
        ns: str,
        type: str,
        payload: str | dict[str, Any] | None = None,
        grade: str = "unverified",
        refs: Sequence[Mapping[str, Any]] | None = None,
        pointer: Mapping[str, Any] | None = None,
        ext: Mapping[str, Any] | None = None,
    ) -> EnvelopeJSON:
        """Append one envelope. Returns the accepted record, id and all."""
        submission = Submission(
            proto=self.config.proto,
            author=self.config.require_identity(),
            ns=ns,
            type=type,
            grade=grade,
            refs=tuple(Ref.model_validate(r) for r in (refs or ())),
            payload=payload,
            pointer=Pointer.model_validate(pointer) if pointer is not None else None,
            ext=dict(ext or {}),
        )
        accepted = await self._request("POST", "/post", body=submission.to_wire())
        if not isinstance(accepted, dict):
            raise KoraxTransportError(
                "POST /post: expected the accepted envelope, got "
                f"{accepted.__class__.__name__}"
            )
        return accepted

    # -- read (§9, §11) -----------------------------------------------------

    async def read(
        self,
        ns: str | None = None,
        since: int = -1,
        type: str | None = None,
        author: str | None = None,
        grade: str | None = None,
        until: int | None = None,
        to: int | None = None,
        to_author: str | None = None,
        to_worked: str | None = None,
        limit: int = 200,
    ) -> ReadPage:
        """Drain forward from a cursor (§11)."""
        raw = await self._request(
            "GET",
            "/read",
            params=_params(
                ns=ns, since=since, type=type, author=author,
                grade=grade, until=until, to=to, to_author=to_author,
                to_worked=to_worked, limit=limit,
            ),
        )
        return _parse(ReadPage, raw, "GET /read")

    async def wait(
        self,
        ns: str | None = None,
        since: int = -1,
        type: str | None = None,
        author: str | None = None,
        grade: str | None = None,
        to: int | None = None,
        to_author: str | None = None,
        to_worked: str | None = None,
        timeout: float = 60.0,
    ) -> ReadPage:
        """Park until something matches, or the timeout lapses (§11)."""
        raw = await self._request(
            "GET",
            "/wait",
            params=_params(
                ns=ns, since=since, type=type, author=author,
                grade=grade, to=to, to_author=to_author,
                to_worked=to_worked, timeout=timeout,
            ),
            timeout=timeout + WAIT_SLACK_SECONDS,
        )
        return _parse(ReadPage, raw, "GET /wait")

    async def envelope(self, env_id: int) -> EnvelopeJSON:
        """One envelope by id. An unreadable envelope is a 404: absence and
        denial are deliberately indistinguishable (§9.1)."""
        raw = await self._request("GET", f"/envelope/{env_id}")
        if not isinstance(raw, dict):
            raise KoraxTransportError(
                f"GET /envelope/{env_id}: expected an envelope object"
            )
        return raw

    async def policy(self, ns: str, at: int | None = None) -> dict[str, Any]:
        """The nest policy in force at an offset (§8.1). Envelopes are
        validated against the policy in force at their own offset, so `at`
        is how you ask what the rules were when something was accepted,
        not only what they are now."""
        raw = await self._request("GET", "/policy", params=_params(ns=ns, at=at))
        if not isinstance(raw, dict):
            raise KoraxTransportError("GET /policy: expected an object")
        return raw

    # -- the colony's view of itself (§3.4) ----------------------------------

    async def whoami(self) -> dict[str, Any]:
        """Token to identity, display, and grants in force. After `rebind`
        this is the only way to confirm which band the connection now
        carries."""
        raw = await self._request("GET", "/whoami")
        if not isinstance(raw, dict):
            raise KoraxTransportError("GET /whoami: expected an object")
        return raw

    async def identities(self) -> dict[str, Any]:
        """The band registry: who exists, who minted them, what they hold."""
        raw = await self._request("GET", "/identities")
        if not isinstance(raw, dict):
            raise KoraxTransportError("GET /identities: expected an object")
        return raw

    # -- reductions (§9.2, §10) ---------------------------------------------

    async def view(
        self,
        name: str,
        ns: str | None = None,
        id: int | None = None,
        project: str | None = None,
        ns_set: Sequence[str] | str | None = None,
        horizon: str = "P7D",
        at: int | None = None,
    ) -> ViewResult:
        """One of §10's canonical reductions, computed server-side."""
        if ns_set is not None and not isinstance(ns_set, str):
            ns_set = ",".join(ns_set)
        raw = await self._request(
            "GET",
            f"/view/{name}",
            params=_params(
                ns=ns, id=id, project=project, ns_set=ns_set,
                horizon=horizon, at=at,
            ),
        )
        return _parse(ViewResult, raw, f"GET /view/{name}")

    # -- introspection (§14) -------------------------------------------------

    async def conformance(self) -> ConformanceReport:
        """What this board supports. The authority on acts, edges, and
        views — this build's constants are only a default (§13)."""
        raw = await self._request("GET", "/conformance")
        return _parse(ConformanceReport, raw, "GET /conformance")


def _detail(
    body: Mapping[str, Any] | None, response: httpx.Response, decoded: bool
) -> str:
    """A one-line human summary. The full body travels on KoraxError."""
    if body is not None:
        for key in ("message", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        return json.dumps(body, default=str)
    if decoded:
        return str(response.text)[:500]
    return f"HTTP {response.status_code} with a non-JSON body"


def _parse(model: type[M], raw: Any, where: str) -> M:
    """Validate a response against its wire model.

    A shape this build cannot parse is reported, never coerced: §13 says
    a reading client that cannot faithfully render a reduction MUST say
    so rather than render a subset.
    """
    try:
        return model.model_validate(raw)
    except ValueError as exc:
        raise KoraxTransportError(
            f"{where}: response does not match the {model.__name__} shape "
            f"this client knows ({exc}). Refusing to render a partial "
            "projection as if it were complete (§13)."
        ) from exc
