"""JOB #1362, MCP half — the write path retries by key (ISSUE #1205).

The sibling of `clients/cli/tests/test_write_path_retry.py`. Same three
states, same rule about the instrument: **failures are injected BELOW the
client**, by damaging the HTTP exchange, so the client meets a real
`httpx` response or a real `httpx` exception. A test that raised
`KoraxTransportError` itself would pass with the retry code deleted.

The load-bearing case is `test_landed_...`, where the POST really
appends and only the response dies — the failure a blind retry turns
into a permanent duplicate.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from conftest import World

pytestmark = pytest.mark.anyio

NS = "/commons/offtopic"


class Damage(httpx.AsyncBaseTransport):
    """The real board with POSTs damaged on the way back. See the CLI
    sibling for the plan vocabulary; reads always pass through, because
    the recovery probe has to see the true log."""

    def __init__(self, inner: httpx.AsyncBaseTransport, plan: list[str | None],
                 dead_reads: int = 0):
        self.inner = inner
        self.plan = list(plan)
        self.posts = 0
        self.dead_reads = dead_reads
        self.blocked_reads = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/read":
            if self.dead_reads > 0:
                self.dead_reads -= 1
                self.blocked_reads += 1
                raise httpx.ConnectError("board is down", request=request)
            return await self.inner.handle_async_request(request)
        if not (request.method == "POST" and request.url.path == "/post"):
            return await self.inner.handle_async_request(request)
        step = self.plan.pop(0) if self.plan else None
        self.posts += 1
        if step == "502-after":
            response = await self.inner.handle_async_request(request)
            await response.aread()  # the append has happened
            return httpx.Response(502, text="502 Bad Gateway", request=request)
        if step == "502-before":
            return httpx.Response(502, text="502 Bad Gateway", request=request)
        if step == "reset":
            raise httpx.ConnectError("reset by peer", request=request)
        if step == "503-clean":
            return httpx.Response(
                503,
                json={"detail": "the board is restarting", "retry_after_s": 0},
                request=request,
            )
        if step == "400":
            return httpx.Response(
                400, json={"code": 400, "message": "malformed"}, request=request
            )
        return await self.inner.handle_async_request(request)


@pytest.fixture()
def nosleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def damaged_client(world: World, identity: str, token: str,
                   plan: list[str | None], dead_reads: int = 0):
    from pydantic import SecretStr

    from korax_mcp.client import KoraxClient
    from korax_mcp.config import KoraxConfig

    transport = Damage(httpx.ASGITransport(app=world.app), plan, dead_reads)
    client = KoraxClient(
        KoraxConfig(url="http://board.test", token=SecretStr(token),
                    identity=identity),
        transport=transport,
    )
    return client, transport


async def _with_key(world: World, identity: str, token: str, key: str) -> list[int]:
    """What the BOARD holds under this key — the duplicate check."""
    client = world.client_for(identity, token)
    try:
        page = await client.read(ns=NS, author=identity, since=-1, limit=500)
    finally:
        await client.aclose()
    return [
        env["id"]
        for env in page.envelopes
        if (env.get("ext") or {}).get("korax", {}).get("idem") == key
    ]


@pytest.fixture()
def poster(world: World) -> tuple[str, str]:
    identity, token = world.register("mcp-retry-band")
    world.grant(identity, "/commons/**", "warner")
    return identity, token


async def test_landed_the_append_happened_and_the_response_died(
    world: World, poster, nosleep
) -> None:
    identity, token = poster
    client, transport = damaged_client(world, identity, token, ["502-after"])
    try:
        accepted = await client.post(
            ns=NS, type="NOTE", payload="hello", grade="n/a", idem="m-landed"
        )
    finally:
        await client.aclose()

    matches = await _with_key(world, identity, token, "m-landed")
    assert len(matches) == 1, f"the write was duplicated: {matches}"
    assert accepted["id"] == matches[0]
    assert transport.posts == 1, "recovery must not re-POST after finding it"


async def test_did_not_land_nothing_appended_so_repost(
    world: World, poster, nosleep
) -> None:
    identity, token = poster
    client, transport = damaged_client(world, identity, token,
                                       ["reset", "502-before"])
    try:
        accepted = await client.post(
            ns=NS, type="NOTE", payload="hello", grade="n/a", idem="m-lost"
        )
    finally:
        await client.aclose()

    matches = await _with_key(world, identity, token, "m-lost")
    assert len(matches) == 1, matches
    assert accepted["id"] == matches[0]
    assert transport.posts == 3


async def test_ambiguous_refuses_and_appends_nothing(
    world: World, poster, nosleep
) -> None:
    """Two envelopes, one key — the impossible state, kept loud.

    When the instrument that decides "did it land" has itself failed,
    guessing is the one move that cannot be walked back.
    """
    identity, token = poster
    clean = world.client_for(identity, token)
    try:
        for text in ("first", "second"):
            await clean.post(ns=NS, type="NOTE", payload=text, grade="n/a",
                             idem="m-dup")
    finally:
        await clean.aclose()
    before = await _with_key(world, identity, token, "m-dup")
    assert len(before) == 2, before

    client, _ = damaged_client(world, identity, token, ["502-before"])
    from korax_mcp.wire import KoraxTransportError

    try:
        with pytest.raises(KoraxTransportError, match="AMBIGUOUS"):
            await client.post(ns=NS, type="NOTE", payload="third", grade="n/a",
                              idem="m-dup")
    finally:
        await client.aclose()

    assert await _with_key(world, identity, token, "m-dup") == before, (
        "a refusal that still appended is not a refusal"
    )


async def test_a_clean_503_retries_without_probing(
    world: World, poster, nosleep
) -> None:
    identity, token = poster
    client, transport = damaged_client(world, identity, token, ["503-clean"])
    try:
        await client.post(ns=NS, type="NOTE", payload="x", grade="n/a",
                          idem="m-503")
    finally:
        await client.aclose()
    assert len(await _with_key(world, identity, token, "m-503")) == 1
    assert transport.posts == 2


async def test_a_400_is_never_retried(world: World, poster, nosleep) -> None:
    identity, token = poster
    client, transport = damaged_client(world, identity, token, ["400"] * 5)
    from korax_mcp.wire import KoraxError

    try:
        with pytest.raises(KoraxError):
            await client.post(ns=NS, type="NOTE", payload="x", grade="n/a",
                              idem="m-400")
    finally:
        await client.aclose()
    assert transport.posts == 1, "a considered refusal must not be retried"


async def test_no_key_means_one_attempt_and_no_field(
    world: World, poster, nosleep
) -> None:
    """D3's other half: opting out is real, so the permanent key is never
    added to somebody's envelope on their behalf."""
    identity, token = poster
    client, transport = damaged_client(world, identity, token, ["502-before"])
    from korax_mcp.wire import KoraxError

    try:
        with pytest.raises(KoraxError):
            await client.post(ns=NS, type="NOTE", payload="bare", grade="n/a")
    finally:
        await client.aclose()
    assert transport.posts == 1

    clean = world.client_for(identity, token)
    try:
        accepted = await clean.post(ns=NS, type="NOTE", payload="bare",
                                    grade="n/a")
    finally:
        await clean.aclose()
    assert "idem" not in (accepted.get("ext") or {}).get("korax", {})


async def test_the_key_leaves_other_ext_fields_alone(
    world: World, poster, nosleep
) -> None:
    identity, token = poster
    other, _ = world.register("mentioned")
    client = world.client_for(identity, token)
    try:
        accepted = await client.post(
            ns=NS, type="NOTE", payload="with a mention", grade="n/a",
            idem="m-ext", ext={"korax": {"mentions": [other]}},
        )
    finally:
        await client.aclose()
    korax_ext = accepted["ext"]["korax"]
    assert korax_ext["mentions"] == [other]
    assert korax_ext["idem"] == "m-ext"


async def test_a_probe_that_cannot_run_never_becomes_did_not_land(
    world: World, poster, nosleep
) -> None:
    """The restart window: the POST appends, the response dies, and the
    probe is unavailable too. A failed probe must retry the PROBE — never
    fall through to a repost of a write that may already be on the log."""
    identity, token = poster
    client, transport = damaged_client(world, identity, token, ["502-after"],
                                       dead_reads=2)
    try:
        accepted = await client.post(ns=NS, type="NOTE", payload="x",
                                     grade="n/a", idem="m-drain")
    finally:
        await client.aclose()

    matches = await _with_key(world, identity, token, "m-drain")
    assert len(matches) == 1, f"the write was duplicated: {matches}"
    assert accepted["id"] == matches[0]
    assert transport.posts == 1, "a failed probe must never trigger a repost"
    assert transport.blocked_reads == 2


async def test_an_unanswerable_board_stops_rather_than_reposting(
    world: World, poster, nosleep
) -> None:
    """UNDETERMINED is the honest end: the write may be on the log and
    nothing here can rule it out, so stop and hand back the key."""
    identity, token = poster
    client, transport = damaged_client(world, identity, token, ["502-after"],
                                       dead_reads=99)
    from korax_mcp.wire import KoraxTransportError

    try:
        with pytest.raises(KoraxTransportError, match="UNDETERMINED"):
            await client.post(ns=NS, type="NOTE", payload="x", grade="n/a",
                              idem="m-undet", attempts=3)
    finally:
        await client.aclose()

    assert transport.posts == 1, "nothing may be reposted while unknown"
    assert len(await _with_key(world, identity, token, "m-undet")) == 1
