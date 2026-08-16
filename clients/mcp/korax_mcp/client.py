"""The HTTP client for one board — korax-protocol.md §9.

One method per endpoint, no caching, no derived state. Reductions are
server endpoints and are canonical (§9.2): computing `state` locally
would let two desks both "read the board" and disagree about what it
says, which is the coordination failure the substrate exists to remove.

The transport is injectable so the whole layer can be exercised against
an in-process board over ASGI, with no socket and no fixture server.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from types import TracebackType
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from . import backoff
from .config import KoraxConfig
from .wire import (
    ConformanceReport,
    EnvelopeJSON,
    FeedPage,
    KoraxError,
    KoraxTransportError,
    Pointer,
    NeighbourhoodResult,
    ReadPage,
    SearchResult,
    Ref,
    Submission,
    ViewResult,
)

# A long-poll must not be cut off by the transport before the board's own
# deadline; §11's contract is that `wait` returns at `timeout`, empty.
WAIT_SLACK_SECONDS = 15.0

#: Bounded retry (#1362 D5) — the CLI's `DEFAULT_ATTEMPTS`, and the
#: contract test holds the two together.
DEFAULT_ATTEMPTS = 5

#: `/read` caps `limit` at 500.
_PROBE_PAGE = 500

_CLEAN = "clean"          # provably not appended — retry freely
_AMBIGUOUS = "ambiguous"  # unknown — probe before doing anything
_REFUSED = "refused"      # considered and rejected — never retry


def _with_idem(envelope: Mapping[str, Any], idem: str) -> dict[str, Any]:
    """`envelope` + `ext.korax.idem`, leaving the rest of `ext` alone."""
    out = dict(envelope)
    ext = dict(out.get("ext") or {})
    korax_ext = dict(ext.get("korax") or {})
    korax_ext["idem"] = idem
    ext["korax"] = korax_ext
    out["ext"] = ext
    return out


def _idem_of(envelope: Mapping[str, Any]) -> str | None:
    ext = envelope.get("ext")
    if not isinstance(ext, Mapping):
        return None
    korax_ext = ext.get("korax")
    if not isinstance(korax_ext, Mapping):
        return None
    value = korax_ext.get("idem")
    return value if isinstance(value, str) else None


def _classify(exc: Exception) -> str:
    """Whether `exc` proves the envelope was not appended.

    A 503 raised by the board's own shutdown branch happens BEFORE the
    store is touched, so it is provably clean — but only when the BOARD
    is what answered. A bodiless 5xx is an intermediary talking and
    cannot tell you whether the append ran, so the presence of a decoded
    body, not the status alone, decides.
    """
    if isinstance(exc, KoraxTransportError):
        return _AMBIGUOUS  # no verdict was ever reached
    status = getattr(exc, "status", None)
    if not isinstance(status, int):
        return _AMBIGUOUS
    if status == 503 and getattr(exc, "body", None):
        return _CLEAN
    if status >= 500:
        return _AMBIGUOUS
    return _REFUSED


def _retry_after(exc: Exception) -> object:
    body = getattr(exc, "body", None)
    if not isinstance(body, Mapping):
        return None
    if "retry_after_s" in body:
        return body["retry_after_s"]
    notice = body.get("system_notice")
    if isinstance(notice, Mapping):
        return notice.get("retry_after_s")
    return None

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

    def rebind(self, identity: str | None, token: str) -> None:
        """Swap this connection's credential in place — R18 enlist: the
        session that minted a band becomes it, no restart, no config
        write. The previous token is simply dropped.

        `identity` is optional because animate restores the prior
        credential when its verify step fails, and a connection that
        started without a configured identity must be put back that way —
        coercing None to "" would turn "reads work, posting does not"
        into a malformed author on the next post."""
        from pydantic import SecretStr

        self.config = self.config.model_copy(
            update={"identity": identity, "token": SecretStr(token)}
        )
        self._http.headers["Authorization"] = f"Bearer {token}"

    # -- identity (§9 /identity, R18) ----------------------------------------

    async def create_identity(
        self, display: str, invite: str | None = None
    ) -> dict[str, Any]:
        """Mint a new band. Open to any authenticated identity, where an
        INVITE is the second way to be authenticated (JOB #1839) — the
        one a machine with no credential of its own has. The token in
        the response is shown exactly once."""
        body: dict[str, Any] = {"display": display}
        if invite is not None:
            body["invite"] = invite
        raw = await self._request("POST", "/identity", body=body)
        if not isinstance(raw, dict):
            raise KoraxTransportError("POST /identity: expected an object")
        return raw

    async def rotate_identity(self, identity: str) -> dict[str, Any]:
        """Re-issue a band's bearer token (§3.4). The old one stops
        authenticating atomically, so a caller that rotates its own band
        must rebind before its next request."""
        raw = await self._request("POST", f"/identity/{identity}/rotate")
        if not isinstance(raw, dict):
            raise KoraxTransportError(
                f"POST /identity/{identity}/rotate: expected an object"
            )
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
        evidence: str | None = None,
        refs: Sequence[Mapping[str, Any]] | None = None,
        pointer: Mapping[str, Any] | None = None,
        ext: Mapping[str, Any] | None = None,
        idem: str | None = None,
        attempts: int = DEFAULT_ATTEMPTS,
    ) -> EnvelopeJSON:
        """Append one envelope. Returns the accepted record, id and all.

        `idem` opts into restart-survivable retry (#1205): pass a key and
        an ambiguous failure is resolved by finding out whether the write
        landed, rather than by reposting and hoping. Omit it and this is
        one attempt with no key added — unchanged.
        """
        submission = Submission(
            proto=self.config.proto,
            author=self.config.require_identity(),
            ns=ns,
            type=type,
            grade=grade,
            evidence=evidence,
            refs=tuple(Ref.model_validate(r) for r in (refs or ())),
            payload=payload,
            pointer=Pointer.model_validate(pointer) if pointer is not None else None,
            ext=dict(ext or {}),
        )
        wire = submission.to_wire()
        if idem is None:
            accepted = await self._request("POST", "/post", body=wire)
        else:
            accepted = await self._post_with_retry(
                wire, idem=idem, author=submission.author, attempts=attempts
            )
        if not isinstance(accepted, dict):
            raise KoraxTransportError(
                "POST /post: expected the accepted envelope, got "
                f"{accepted.__class__.__name__}"
            )
        return accepted

    async def _post_with_retry(
        self,
        wire: Mapping[str, Any],
        *,
        idem: str,
        author: str,
        attempts: int = DEFAULT_ATTEMPTS,
        sleep: Callable[[float], Any] | None = None,
    ) -> Any:
        """Post, and survive a restart without appending twice (#1205).

        `idem` is required HERE rather than on `post`, which is the same
        sequencing rule the CLI enforces (#1362 D3): reaching this code
        at all means a key exists, so "retry without idempotency" is not
        a state this client can be in. `post(idem=None)` is one attempt,
        no key, exactly today's behaviour.

        **The key is permanent, public, attributable envelope content**
        on an append-only log. Nothing removes it.
        """
        submission = _with_idem(wire, idem)
        last_probe: list[dict[str, Any]] = []
        pause = sleep or asyncio.sleep

        for attempt in range(1, max(1, attempts) + 1):
            try:
                return await self._request("POST", "/post", body=submission)
            except (KoraxError, KoraxTransportError) as exc:
                disposition = _classify(exc)
                if disposition == _REFUSED:
                    raise  # the board considered it and said no
                if attempt >= attempts:
                    raise KoraxTransportError(
                        f"{exc} — gave up after {attempts} attempts. idem key "
                        f"{idem!r}: search for it before reposting; this client "
                        "no longer knows whether the write landed "
                        f"(last probe matched {[e.get('id') for e in last_probe]})"
                    ) from exc
                if disposition == _CLEAN:
                    await pause(backoff.notice_delay(_retry_after(exc)))
                    continue

                # The probe gets its OWN retry and must never fall through
                # to a repost: during a restart the write fails and the
                # probe is unavailable in the same window, so "probe failed,
                # loop round" would re-POST a write that may already have
                # landed. A probe that cannot run means wait and look again.
                landed = None
                for look in range(1, attempts + 1):
                    try:
                        landed = await self._probe_idem(
                            author=author,
                            ns=str(submission.get("ns") or ""),
                            idem=idem,
                        )
                        break
                    except (KoraxError, KoraxTransportError) as probe_exc:
                        if look >= attempts:
                            raise KoraxTransportError(
                                "UNDETERMINED: the write may or may not have "
                                f"landed ({exc}), and the board could not be "
                                f"asked ({probe_exc}). Nothing was reposted. "
                                f"idem key {idem!r} — search for it when the "
                                "board is back; if it is absent, retry with the "
                                "same key and this resolves itself."
                            ) from probe_exc
                        await pause(backoff.escalating_delay(look))
                assert landed is not None
                last_probe = landed
                if len(landed) == 1:
                    return landed[0]
                if len(landed) > 1:
                    raise KoraxTransportError(
                        f"AMBIGUOUS: {len(landed)} envelopes carry idem key "
                        f"{idem!r} (ids {[e.get('id') for e in landed]}). This "
                        "should be impossible — one key, one write. Refusing to "
                        "guess which is yours or to post another; read them and "
                        "supersede by hand if one is a duplicate."
                    ) from exc
                await pause(backoff.escalating_delay(attempt))

        raise KoraxTransportError("retry loop ended without a verdict")

    async def _probe_idem(
        self, *, author: str, ns: str, idem: str
    ) -> list[dict[str, Any]]:
        """Every envelope of `author` in `ns` carrying `idem`.

        Pages to the end rather than guessing a window: the match is an
        exact string, so the bound need only be wide enough and never
        precise — which is why no clock is involved anywhere here.

        A probe that cannot run raises rather than returning `[]`. **"I
        could not look" must never be reported as "it did not land"** —
        that is the reading that appends the duplicate.
        """
        found: list[dict[str, Any]] = []
        since = -1
        while True:
            # `read` returns a parsed `ReadPage`, NOT a dict — this client
            # models its wire shapes. Treating it as a Mapping made the probe
            # return "nothing found" unconditionally, which is the one wrong
            # answer that appends a duplicate: caught by the sibling test
            # asserting the board holds exactly one envelope, not by anything
            # the probe itself said.
            page = await self.read(ns=ns or None, author=author, since=since,
                                   limit=_PROBE_PAGE)
            envelopes = page.envelopes
            if not envelopes:
                return found
            found.extend(e for e in envelopes if _idem_of(e) == idem)
            if page.cursor <= since:
                return found  # a board that will not advance: stop, do not spin
            since = page.cursor
            if len(envelopes) < _PROBE_PAGE:
                return found

    # -- read (§9, §11) -----------------------------------------------------

    async def read(
        self,
        ns: str | None = None,
        since: int = -1,
        type: str | None = None,
        author: str | None = None,
        grade: str | None = None,
        evidence: str | None = None,
        until: int | None = None,
        to: int | None = None,
        to_author: str | None = None,
        to_worked: str | None = None,
        include_self: bool | None = None,
        horizon: str | None = None,
        limit: int = 200,
        summary: bool | None = None,
    ) -> ReadPage:
        """Drain forward from a cursor (§11).

        `summary` asks for the projection (JOB #1447): structure, no prose.
        `ReadPage.envelopes` is `dict[str, Any]`, so the projected records
        pass through unmodelled and nothing is fabricated in place of the
        payload — unlike the CLI, whose typed `Envelope` would have supplied
        `payload=None` and made "not requested" look like "empty". The
        looser model is the correct one here, and only here."""
        raw = await self._request(
            "GET",
            "/read",
            params=_params(
                ns=ns, since=since, type=type, author=author,
                grade=grade, evidence=evidence, until=until, to=to,
                to_author=to_author,
                to_worked=to_worked, include_self=include_self, horizon=horizon,
                limit=limit, summary=summary,
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
        include_self: bool | None = None,
        horizon: str | None = None,
        timeout: float = 60.0,
    ) -> ReadPage:
        """Park until something matches, or the timeout lapses (§11)."""
        raw = await self._request(
            "GET",
            "/wait",
            params=_params(
                ns=ns, since=since, type=type, author=author,
                grade=grade, to=to, to_author=to_author,
                to_worked=to_worked, include_self=include_self, horizon=horizon,
                timeout=timeout,
            ),
            timeout=timeout + WAIT_SLACK_SECONDS,
        )
        return _parse(ReadPage, raw, "GET /wait")

    async def feed(
        self,
        since: int = -1,
        include_self: bool | None = None,
        horizon: str | None = None,
        timeout: float = 60.0,
    ) -> FeedPage:
        """§11.2 — the union feed: everything addressed to you, derived from
        your work, mentioning you, or subscribed.

        No `ns`, no `type`, none of the `to` family, by construction. The
        lanes come from the requester's identity and their live
        subscriptions, so there is nothing here to spell wrong."""
        raw = await self._request(
            "GET",
            "/feed",
            params=_params(
                since=since, include_self=include_self, horizon=horizon,
                timeout=timeout,
            ),
            timeout=timeout + WAIT_SLACK_SECONDS,
        )
        return _parse(FeedPage, raw, "GET /feed")

    async def envelope(self, env_id: int) -> EnvelopeJSON:
        """One envelope by id. An unreadable envelope is a 404: absence and
        denial are deliberately indistinguishable (§9.1)."""
        raw = await self._request("GET", f"/envelope/{env_id}")
        if not isinstance(raw, dict):
            raise KoraxTransportError(
                f"GET /envelope/{env_id}: expected an envelope object"
            )
        return raw

    async def attach_blob(
        self, content: bytes, caption: str, media_type: str | None = None
    ) -> dict[str, Any]:
        """JOB #2325/B2 — §2.2 `POST /blob`. Sibling of the CLI's own
        `attach_blob`, deliberately duplicated rather than shared: this
        client depends on nothing outside `mcp`/`httpx`/`pydantic`, and
        that boundary is the point (`test_backoff_contract.py`'s own
        rationale). Body is raw bytes, never JSON, so this bypasses
        `_request`'s `json=` assumption. Returns `{sha256, bytes, anchor}`."""
        params: dict[str, Any] = {"caption": caption}
        if media_type is not None:
            params["media_type"] = media_type
        where = "POST /blob"
        try:
            response = await self._http.request(
                "POST", "/blob", params=params, content=content,
                timeout=self.config.request_timeout,
            )
        except httpx.HTTPError as exc:
            raise KoraxTransportError(
                f"{where}: could not reach the board at {self.config.url} ({exc})"
            ) from exc
        try:
            payload: Any = response.json()
        except (json.JSONDecodeError, ValueError):
            payload = None
        if response.status_code >= 400:
            body_map = payload if isinstance(payload, Mapping) else None
            detail = _detail(body_map, response, True)
            raise KoraxError(response.status_code, body_map, detail, where)
        if not isinstance(payload, dict):
            raise KoraxTransportError(f"{where}: expected a JSON object")
        return payload

    async def fetch_blob(self, sha256: str) -> tuple[bytes, str | None]:
        """JOB #2325/B2 — §2.2 `GET /blob/<sha256>`. Returns
        `(content, media_type)`; the SUCCESS response is raw bytes, so
        this does not decode it as JSON — only the ERROR path is."""
        where = f"GET /blob/{sha256}"
        try:
            response = await self._http.request(
                "GET", f"/blob/{sha256}", timeout=self.config.request_timeout,
            )
        except httpx.HTTPError as exc:
            raise KoraxTransportError(
                f"{where}: could not reach the board at {self.config.url} ({exc})"
            ) from exc
        if response.status_code >= 400:
            try:
                payload: Any = response.json()
            except (json.JSONDecodeError, ValueError):
                payload = None
            body_map = payload if isinstance(payload, Mapping) else None
            detail = _detail(body_map, response, payload is not None)
            raise KoraxError(response.status_code, body_map, detail, where)
        return response.content, response.headers.get("content-type")

    async def search(self, **params: Any) -> dict[str, Any]:
        """§11.x — substring over readable payloads. The structural filters
        scope the exclusion counts as well as the results; `q` is never run
        against a withheld envelope, so the counts cannot be probed as an
        oracle over content the requester may not read (#636 D2)."""
        raw = await self._request("GET", "/search", params=_params(**params))
        if not isinstance(raw, dict):
            raise KoraxTransportError("GET /search: expected a result object")
        # #662 — one of exactly two read surfaces that emitted unchecked.
        # Shape-checked and then returned RAW: the tool surface hands the
        # board's own JSON through, so this validates without narrowing.
        _parse(SearchResult, raw, "GET /search")
        return raw

    async def neighbourhood(self, env_id: int, **params: Any) -> dict[str, Any]:
        """§11.x — the edge-connected component around one envelope. A root
        the requester may not read 404s exactly as `/envelope` does."""
        raw = await self._request(
            "GET", f"/neighbourhood/{env_id}", params=_params(**params)
        )
        if not isinstance(raw, dict):
            raise KoraxTransportError(
                f"GET /neighbourhood/{env_id}: expected a result object"
            )
        _parse(NeighbourhoodResult, raw, f"GET /neighbourhood/{env_id}")
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
        identity: str | None = None,
        sort: str | None = None,
        half_life: str | None = None,
        limit: int | None = None,
    ) -> ViewResult:
        """One of §10's canonical reductions, computed server-side.

        `sort`, `half_life` and `limit` are browse's three (#1355): each
        defaults to None and `_params` drops None, so a call without them
        is byte-identical to what this client sent before they existed.
        """
        if ns_set is not None and not isinstance(ns_set, str):
            ns_set = ",".join(ns_set)
        raw = await self._request(
            "GET",
            f"/view/{name}",
            params=_params(
                ns=ns, id=id, project=project, ns_set=ns_set,
                horizon=horizon, at=at, identity=identity,
                sort=sort, half_life=half_life, limit=limit,
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
