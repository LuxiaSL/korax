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

import asyncio
import json
from collections.abc import Callable
from types import TracebackType
from typing import Any, Mapping
from urllib.parse import quote

import httpx

from . import backoff

DEFAULT_TIMEOUT = 30.0

#: §9.1 (#680) — the `code` a failure carries when it never reached the
#: wire. `code` is the PROTOCOL status and the server puts a real one
#: there (`409`, `422`, …); a transport failure or a local refusal has no
#: such status, and the value that used to stand in for one was `0`.
#:
#: **Zero is the one value the adjacent channel defines as success.** The
#: JSON is what you `tee`; the exit status is what you branch on; the two
#: are read together constantly, and a reader who glanced at `code: 0`
#: carried a false fact for hours (#680's transcript). A string cannot be
#: mistaken for a status or for a shell exit code.
#:
#: It lives HERE rather than in `cli.py` because this module raises the
#: transport failures — putting the constant next to the error type means
#: a new failure path reaches for the sentinel that is already in scope,
#: instead of the `0` that was there before it (which is exactly how the
#: two sites below outlived the first fix attempt).
LOCAL_FAILURE = "local"

#: How many times `post_with_retry` will try before giving up. Bounded on
#: purpose (#1362 D5): an unbounded write retry against a board that is
#: down is #914's lesson pointed at the write path.
DEFAULT_ATTEMPTS = 5

#: Page size for the recovery probe. `/read` caps `limit` at 500.
_PROBE_PAGE = 500

# What a failed attempt tells us about whether the envelope was appended.
_CLEAN = "clean"          # provably not appended — retry freely
_AMBIGUOUS = "ambiguous"  # unknown — probe before doing anything
_REFUSED = "refused"      # considered and rejected — never retry


def _with_idem(envelope: Mapping[str, Any], idem: str) -> dict[str, Any]:
    """`envelope` + `ext.korax.idem`, without disturbing what is there.

    Copies rather than mutates: the caller's dict is reused across
    attempts and a helper that edited it in place would make the second
    attempt's payload depend on the first attempt's failure path.
    """
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


def _classify(exc: "ApiError") -> str:
    """Whether `exc` proves the envelope was not appended.

    The distinction #1205 is about. A 503 raised by the board's own
    shutdown branch happens BEFORE the store is touched, so it is
    provably clean — but only when the board is what answered. **A
    bodiless 5xx is an intermediary talking, and it cannot tell you
    whether the append ran**, which is why the body's presence, not the
    status code alone, decides.
    """
    code = exc.code
    if code == LOCAL_FAILURE:
        return _AMBIGUOUS  # timeout or connection failure: never a verdict
    if not isinstance(code, int):
        return _AMBIGUOUS
    if code == 503 and exc.extra:
        return _CLEAN
    if code >= 500:
        return _AMBIGUOUS
    return _REFUSED


def _retry_after(exc: "ApiError") -> object:
    """`retry_after_s` from a goodbye/refusal body, in any of its shapes."""
    for key in ("retry_after_s", "retry_after"):
        if key in exc.extra:
            return exc.extra[key]
    notice = exc.extra.get("system_notice")
    if isinstance(notice, Mapping):
        return notice.get("retry_after_s")
    return None


def _ambiguous(idem: str, candidates: list[dict[str, Any]]) -> "ApiError":
    """The refusal that is the feature (#1362 D2).

    Unreachable by construction — one key cannot honestly match two
    envelopes — and kept loud anyway, because an impossible branch that
    stays quiet when it fires is how a guard becomes decorative
    (#1196/#1250). If this ever raises, the guard itself has failed and
    a human must look; the one thing it must not do is pick.
    """
    ids = [env.get("id") for env in candidates]
    return ApiError(
        LOCAL_FAILURE,
        f"AMBIGUOUS: {len(candidates)} envelopes carry idem key {idem!r} "
        f"(ids {ids}). This should be impossible — one key, one write. "
        "Refusing to guess which is yours or to post another; read them "
        "and supersede by hand if one is a duplicate.",
        {"idem": idem, "candidates": ids, "transport": "ambiguous-idem"},
    )


def _undetermined(
    write_exc: "ApiError", probe_exc: "ApiError", idem: str
) -> "ApiError":
    """The write is unknown AND the board will not say — stop.

    The honest terminal state of a restart that outlasts the retry
    budget: the POST was ambiguous and every look since has failed too.
    **Stopping is the correct move and reposting is not**, because the
    write may be on the log already and nothing here can rule that out.
    Hands back the key so a human — or a later run with `--idem` — can
    finish it safely.
    """
    return ApiError(
        LOCAL_FAILURE,
        f"UNDETERMINED: the write may or may not have landed ({write_exc.message}), "
        f"and the board could not be asked ({probe_exc.message}). Nothing was "
        f"reposted. idem key {idem!r} — search for it when the board is back; "
        f"if it is absent, retry with --idem {idem} and this resolves itself.",
        {"idem": idem, "transport": "undetermined",
         "write_error": write_exc.message, "probe_error": probe_exc.message},
    )


def _exhausted(
    exc: "ApiError", idem: str, last_probe: list[dict[str, Any]], attempts: int
) -> "ApiError":
    """Give-up carries the key and the last probe (#1362 D5).

    Whoever picks this up next needs exactly two things to finish the
    job by hand: the string to search for, and what the last look found.
    """
    return ApiError(
        exc.code,
        f"{exc.message} — gave up after {attempts} attempts. "
        f"idem key {idem!r}: search for it before reposting, because this "
        "client no longer knows whether the write landed.",
        {
            **exc.extra,
            "idem": idem,
            "attempts": attempts,
            "last_probe_matches": [env.get("id") for env in last_probe],
        },
    )


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
        self.transport = transport  # kept so a command can open a second
        # connection as another identity (enlist) over the same transport
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

    async def post_with_retry(
        self,
        envelope: dict[str, Any],
        *,
        idem: str,
        author: str,
        attempts: int = DEFAULT_ATTEMPTS,
        base: float = backoff.DEFAULT_BASE,
        cap: float = backoff.DEFAULT_MAX,
        on_event: "Callable[[dict[str, Any]], None] | None" = None,
        sleep: "Callable[[float], Any] | None" = None,
    ) -> dict[str, Any]:
        """Post, and survive a restart without appending twice (#1205).

        `idem` is REQUIRED and that is the whole sequencing rule (JOB
        #1362 D3, gate #1359): there is no argument list that spells
        "retry this write without a key", so the duplicate-generating
        state is unreachable rather than merely discouraged. A caller
        that does not want a key calls `post_envelope` and gets exactly
        today's behaviour.

        **The key is permanent, public, attributable envelope content.**
        It rides in `ext.korax.idem`, is written to an append-only log,
        and nothing will ever remove it. That is the price of exact
        recovery and it is paid in public.

        Three outcomes on an ambiguous failure, per D2 — and the third
        is the one that matters. A client that can only answer "landed"
        or "did not land" eventually answers wrongly onto a log that
        cannot forget, so this one is allowed to refuse.
        """
        submission = _with_idem(envelope, idem)
        last_probe: list[dict[str, Any]] = []
        note = on_event or (lambda _event: None)
        pause = sleep or asyncio.sleep

        for attempt in range(1, max(1, attempts) + 1):
            try:
                return await self.post_envelope(submission)
            except ApiError as exc:
                disposition = _classify(exc)

                if disposition == _REFUSED:
                    # A real refusal — 400, 403, 409, a policy rejection.
                    # The board considered this envelope and said no; the
                    # answer will not change by asking again, and §4.4
                    # makes the body a reading list rather than noise.
                    raise

                if attempt >= attempts:
                    raise _exhausted(exc, idem, last_probe, attempts)

                if disposition == _CLEAN:
                    # 503 from the board itself: `api.py` refuses BEFORE
                    # `request.json()` and `board.append`, so nothing was
                    # appended and no probe is needed. Honour the number
                    # the board gave us (§11).
                    note({
                        "retry": "clean-refusal",
                        "attempt": attempt,
                        "detail": "the board refused before touching the store; "
                                  "nothing was appended",
                    })
                    await pause(backoff.notice_delay(_retry_after(exc)))
                    continue

                # _AMBIGUOUS — a bodiless 502, a timeout, a reset. This is
                # the case rake #22's rule is about and the case a naive
                # loop gets permanently wrong: it cannot be read as "it
                # happened" OR as "it will not happen".
                #
                # THE PROBE GETS ITS OWN RETRY, AND IT MUST NEVER FALL
                # THROUGH TO A REPOST. During a restart the write fails and
                # the probe is unavailable in the same window — so the
                # tempting shape ("probe failed, loop round, try again") is
                # a duplicate generator: looping re-POSTS, and the write it
                # could not check may already have landed. A probe that
                # cannot run means WAIT AND LOOK AGAIN, never "assume not".
                # Reads are safe to repeat, which is what makes this legal.
                landed = None
                for look in range(1, attempts + 1):
                    try:
                        landed = await self._probe_idem(
                            author=author,
                            ns=str(submission.get("ns") or ""),
                            idem=idem,
                        )
                        break
                    except ApiError as probe_exc:
                        if look >= attempts:
                            raise _undetermined(exc, probe_exc, idem) from probe_exc
                        note({
                            "retry": "probe-unavailable",
                            "attempt": attempt,
                            "detail": "cannot tell whether the write landed and "
                                      "will not guess; waiting to look again "
                                      f"({probe_exc.message})",
                        })
                        await pause(backoff.escalating_delay(look, base=base, cap=cap))
                assert landed is not None
                last_probe = landed

                if len(landed) == 1:
                    note({
                        "retry": "recovered",
                        "attempt": attempt,
                        "id": landed[0].get("id"),
                        "detail": "the write had landed; returning the original "
                                  "envelope rather than posting a duplicate",
                    })
                    return landed[0]

                if len(landed) > 1:
                    raise _ambiguous(idem, landed)

                note({
                    "retry": "did-not-land",
                    "attempt": attempt,
                    "detail": "no envelope carries this key; reposting",
                })
                await pause(backoff.escalating_delay(attempt, base=base, cap=cap))

        raise ApiError(  # unreachable: the loop returns or raises
            LOCAL_FAILURE, "retry loop ended without a verdict", {"idem": idem}
        )

    async def _probe_idem(
        self, *, author: str, ns: str, idem: str
    ) -> list[dict[str, Any]]:
        """Every envelope of `author` in `ns` carrying `idem` (D2).

        Pages forward to the end of the log rather than guessing a
        window. The match is an exact string, so the bound only has to
        be WIDE ENOUGH and never precise — which is why this needs no
        clock, and why #1344's dependency on #690 was withdrawn: there
        is nothing to place in time.

        Reads are safe to repeat, so a probe that fails is re-raised to
        the caller's retry loop rather than swallowed. **A probe that
        cannot run must never be reported as "did not land"** — that is
        the reading that appends the duplicate.
        """
        found: list[dict[str, Any]] = []
        since = -1
        while True:
            page = await self.read(ns=ns or None, author=author, since=since,
                                   limit=_PROBE_PAGE)
            envelopes = page.get("envelopes")
            if not isinstance(envelopes, list) or not envelopes:
                return found
            for env in envelopes:
                if _idem_of(env) == idem:
                    found.append(env)
            cursor = page.get("cursor")
            if not isinstance(cursor, int) or cursor <= since:
                return found  # a board that will not advance: stop, do not spin
            since = cursor
            if len(envelopes) < _PROBE_PAGE:
                return found

    async def read(self, **filters: Any) -> dict[str, Any]:
        return await self._request("GET", "/read", params=filters)

    async def wait(self, **filters: Any) -> dict[str, Any]:
        return await self._request("GET", "/wait", params=filters)

    async def feed(self, **params: Any) -> dict[str, Any]:
        """§11.2 — the union feed. Takes only `since`, `timeout`, `horizon`
        and `include_self`: the lanes come from the requester's identity
        and their live subscriptions, which is why there is nothing here to
        spell wrong."""
        return await self._request("GET", "/feed", params=params)

    async def view(self, name: str, params: Mapping[str, Any]) -> dict[str, Any]:
        # The view name is not validated here: §13 forbids a client from
        # filtering a view it does not recognise. An unknown name is the
        # server's 404 to give.
        return await self._request("GET", f"/view/{quote(name, safe='')}", params=params)

    async def envelope(self, env_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/envelope/{env_id}")

    async def search(self, **params: Any) -> dict[str, Any]:
        """§11.x — substring over payloads. The structural filters scope
        both the results and the exclusion counts; `q` is never run
        against an envelope the board withheld (#636 D2)."""
        return await self._request("GET", "/search", params=params)

    async def neighbourhood(self, env_id: int, **params: Any) -> dict[str, Any]:
        return await self._request("GET", f"/neighbourhood/{env_id}", params=params)

    async def policy(self, ns: str, at: int | None = None) -> dict[str, Any]:
        return await self._request("GET", "/policy", params={"ns": ns, "at": at})

    async def create_identity(
        self, display: str, invite: str | None = None
    ) -> dict[str, Any]:
        """`invite` is the fresh machine's credential (JOB #1839) — sent
        in the BODY rather than as a bearer header, because it does not
        authenticate the caller as anybody: it authorises exactly one
        mint and names who authorised it."""
        body: dict[str, Any] = {"display": display}
        if invite is not None:
            body["invite"] = invite
        return await self._request("POST", "/identity", body=body)

    async def create_invite(self, uses: int, expires_in_s: int) -> dict[str, Any]:
        return await self._request(
            "POST", "/invite", body={"uses": uses, "expires_in_s": expires_in_s}
        )

    async def rotate_identity(self, identity: str) -> dict[str, Any]:
        return await self._request("POST", f"/identity/{quote(identity, safe='')}/rotate")

    async def whoami(self) -> dict[str, Any]:
        return await self._request("GET", "/whoami")

    async def identities(self) -> dict[str, Any]:
        return await self._request("GET", "/identities")

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
                LOCAL_FAILURE,
                f"timed out talking to {target}: {exc}",
                {"transport": "timeout"},
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(
                LOCAL_FAILURE,
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
