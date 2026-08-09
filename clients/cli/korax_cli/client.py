"""The HTTP layer — korax-protocol.md §9.

Async for two reasons: `/wait` is a long poll, and the transport is
injectable so the test suite can point an ASGI transport straight at the
reference app without a socket.

Every failure leaves here as an `ApiError` carrying the server's own body.
That matters most at 409: §4.4 makes the rejection *the reading list*, and
a client that flattened the body to a status line would throw the list
away.
"""

from __future__ import annotations

import json
from types import TracebackType
from typing import Any, Mapping
from urllib.parse import quote

import httpx

DEFAULT_TIMEOUT = 30.0


class ApiError(Exception):
    """A request that did not produce a usable JSON document.

    `code` is the protocol error code (§9.1) when the server supplied one,
    the HTTP status otherwise, and `0` when the request never reached a
    server at all.
    """

    def __init__(self, code: int, message: str, extra: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra: dict[str, Any] = dict(extra or {})

    @classmethod
    def from_response(cls, response: httpx.Response) -> "ApiError":
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            text = response.text.strip()
            return cls(
                response.status_code,
                text or f"HTTP {response.status_code} with no JSON body",
            )
        # `code` and `message` are the protocol's shape; `detail` is what
        # FastAPI's own HTTPException emits. Take either, keep everything.
        raw_code = body.get("code")
        code = raw_code if isinstance(raw_code, int) else response.status_code
        message = body.get("message") or body.get("detail")
        if not isinstance(message, str):
            message = (
                json.dumps(message) if message is not None
                else f"HTTP {response.status_code}"
            )
        return cls(code, message, body)

    def as_json(self) -> dict[str, Any]:
        """The error document. `code` and `message` lead; everything the
        server sent follows verbatim — `policy` above all (§9.1)."""
        document: dict[str, Any] = {"code": self.code, "message": self.message}
        for key, value in self.extra.items():
            if key not in ("code", "message"):
                document[key] = value
        return document


class KoraxClient:
    """One board, one invocation. The CLI is a one-shot process, not a
    session, so there is no connection reuse to design for."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.base_url = base_url.rstrip("/")
        self._authenticated = bool(token)
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            transport=transport,
            timeout=timeout,
        )

    async def __aenter__(self) -> "KoraxClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        try:
            await self._http.aclose()
        except (httpx.HTTPError, RuntimeError):
            pass  # teardown must never mask the command's own result

    # -- endpoints (§9) ----------------------------------------------------

    async def post_envelope(self, envelope: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/post", body=envelope)

    async def read(self, **filters: Any) -> dict[str, Any]:
        return await self._request("GET", "/read", params=filters)

    async def wait(self, **filters: Any) -> dict[str, Any]:
        return await self._request("GET", "/wait", params=filters)

    async def view(self, name: str, params: Mapping[str, Any]) -> dict[str, Any]:
        # The view name is not validated here: §13 forbids a client from
        # filtering a view it does not recognise. An unknown name is the
        # server's 404 to give.
        return await self._request("GET", f"/view/{quote(name, safe='')}", params=params)

    async def envelope(self, env_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/envelope/{env_id}")

    async def policy(self, ns: str, at: int | None = None) -> dict[str, Any]:
        return await self._request("GET", "/policy", params={"ns": ns, "at": at})

    async def create_identity(self, display: str) -> dict[str, Any]:
        return await self._request("POST", "/identity", body={"display": display})

    async def conformance(self) -> dict[str, Any]:
        return await self._request("GET", "/conformance")

    # -- plumbing ----------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        query = {k: v for k, v in (params or {}).items() if v is not None}
        target = f"{self.base_url}{path}"
        try:
            response = await self._http.request(method, path, params=query, json=body)
        except httpx.TimeoutException as exc:
            raise ApiError(
                0, f"timed out talking to {target}: {exc}", {"transport": "timeout"}
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(
                0,
                f"could not reach {target}: {exc}",
                {"transport": type(exc).__name__},
            ) from exc

        if response.status_code >= 400:
            error = ApiError.from_response(response)
            if response.status_code == 401 and not self._authenticated:
                error.extra.setdefault(
                    "hint", "no token configured; set KORAX_TOKEN or pass --token"
                )
            raise error

        try:
            document: Any = response.json()
        except ValueError as exc:
            raise ApiError(
                response.status_code,
                f"{target} returned a non-JSON body: {exc}",
                {"body": response.text[:2000]},
            ) from exc
        if not isinstance(document, dict):
            raise ApiError(
                response.status_code,
                f"{target} returned a JSON {type(document).__name__}, expected an object",
                {"body": document},
            )
        return document
