"""The doorbell loop. JOB #995.

Driven with a scripted feed rather than a live board: every property worth
asserting here is about what the loop does with a sequence of pages, and a
real board makes that sequence a race. The live end-to-end — a wake
reaching a session's context with no parked process — is the delivery's
demonstration, not a unit test's job.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from korax_mcp.doorbell import (
    CHANNEL_METHOD,
    START,
    ChannelDoorbell,
    DoorbellSettings,
)
from korax_mcp.wire import FeedPage, KoraxError


def _env(env_id: int) -> dict:
    return {
        "proto": "korax/0.1",
        "id": env_id,
        "ts": "2026-08-11T05:00:00Z",
        "author": "band:2887f5287fd2",
        "band": "claimant",
        "ns": "/korax-dev/board",
        "type": "NOTE",
        "grade": "n/a",
        "payload": "x",
    }


def _page(ids: list[int], cursor: int, *, notice=None, reasons=None) -> FeedPage:
    body = {
        "envelopes": [_env(i) for i in ids],
        "cursor": cursor,
        "sealed_excluded": 0,
        "rotated_excluded": 0,
        "participation_excluded": 0,
    }
    if notice is not None:
        body["system_notice"] = notice
    if reasons is not None:
        body["reasons"] = reasons
    return FeedPage.model_validate(body)


class ScriptedClient:
    """A client whose `feed` returns a fixed script, then blocks forever.

    Blocking at the end matters: the doorbell's `run()` is an infinite
    loop, so the test cancels it. A script that raised StopIteration would
    make the loop's exit look like a design feature instead of a test
    artifact.
    """

    def __init__(self, pages: list, head: int | None = 100) -> None:
        self._pages = list(pages)
        self._head = head
        self.calls: list[int] = []

    async def policy(self, ns: str) -> dict:
        if self._head is None:
            raise KoraxError(500, None, "no head for you", "GET /policy")
        return {"at": self._head}

    async def feed(self, since: int = -1, timeout: float = 60.0):
        self.calls.append(since)
        if not self._pages:
            await asyncio.sleep(3600)
        item = self._pages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def __call__(self, method: str, params: dict) -> None:
        self.sent.append((method, params))


async def _run_until(doorbell: ChannelDoorbell, rings: int, timeout: float = 2.0):
    task = asyncio.create_task(doorbell.run())
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while doorbell.rings < rings:
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(
                    f"expected {rings} ring(s), saw {doorbell.rings}"
                )
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


NO_WAIT = DoorbellSettings(coalesce_s=0.0, cooldown_s=0.0, poll_s=0.1)


class TestArming:
    @pytest.mark.anyio
    async def test_arms_at_the_head_not_at_the_start(self) -> None:
        """A watch armed at START replays the archive as its first wake
        (#110). On a push lane that is a flood with no process to kill."""
        client = ScriptedClient([], head=985)
        doorbell = ChannelDoorbell(client, Recorder(), settings=NO_WAIT)
        assert await doorbell.arm() == 985

    @pytest.mark.anyio
    async def test_unreachable_head_degrades_rather_than_refuses(self) -> None:
        """A doorbell that rings for history beats one that will not start."""
        client = ScriptedClient([], head=None)
        doorbell = ChannelDoorbell(client, Recorder(), settings=NO_WAIT)
        assert await doorbell.arm() == START


class TestRinging:
    @pytest.mark.anyio
    async def test_rings_once_with_the_count(self) -> None:
        client = ScriptedClient([_page([11, 12, 13], cursor=13)])
        rec = Recorder()
        doorbell = ChannelDoorbell(client, rec, settings=NO_WAIT)
        await _run_until(doorbell, 1)

        method, params = rec.sent[0]
        assert method == CHANNEL_METHOD
        assert params["meta"]["count"] == "3"
        assert params["meta"]["highest_id"] == "13"
        assert "3 new envelopes" in params["content"]

    @pytest.mark.anyio
    async def test_carries_no_envelope_bodies(self) -> None:
        """The doorbell/delivery distinction, asserted rather than trusted.

        This is the property the whole design rests on — it is what keeps
        the cursor authoritative and what makes batching free. A future
        edit that helpfully inlines the payloads would pass every other
        test in this file.
        """
        client = ScriptedClient([_page([11], cursor=11)])
        rec = Recorder()
        doorbell = ChannelDoorbell(client, rec, settings=NO_WAIT)
        await _run_until(doorbell, 1)

        _, params = rec.sent[0]
        assert set(params) == {"content", "meta"}
        assert "payload" not in params["content"]
        assert all(isinstance(v, str) for v in params["meta"].values())

    @pytest.mark.anyio
    async def test_meta_keys_are_identifier_shaped(self) -> None:
        """The host filters `meta` keys against `^[a-zA-Z_][a-zA-Z0-9_]*$`
        and SILENTLY drops the failures. A dotted `korax.ns` key would
        simply vanish, taking with it the thing that says which board."""
        import re

        client = ScriptedClient([_page([11], cursor=11, reasons={"11": ({"lane": "mention"},)})])
        rec = Recorder()
        doorbell = ChannelDoorbell(
            client, rec, settings=NO_WAIT,
            identity="band:2887f5287fd2", board_url="https://korax.example",
        )
        await _run_until(doorbell, 1)

        _, params = rec.sent[0]
        assert params["meta"], "meta should not be empty"
        for key in params["meta"]:
            assert re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", key), (
                f"meta key {key!r} is not identifier-shaped; the host would "
                "drop it silently"
            )

    @pytest.mark.anyio
    async def test_a_system_notice_rings_with_zero_envelopes(self) -> None:
        """THE GATE IS A PAGE, NOT A NON-EMPTY LIST.

        A goodbye carries zero envelopes and a `system_notice`. Gating on
        `page.envelopes` dropped exactly that message for two revisions —
        R42 shipped a goodbye that never once fired until R47 (#921). This
        is that bug, asserted against.
        """
        client = ScriptedClient([_page([], cursor=99, notice="board restarting")])
        rec = Recorder()
        doorbell = ChannelDoorbell(client, rec, settings=NO_WAIT)
        await _run_until(doorbell, 1)

        _, params = rec.sent[0]
        assert "BOARD NOTICE" in params["content"]
        assert params["meta"]["notice"] == "true"


class TestCoalescing:
    @pytest.mark.anyio
    async def test_a_burst_becomes_one_ring(self) -> None:
        """#967 §5, answered: twenty envelopes in three seconds is one
        doorbell that says twenty."""
        client = ScriptedClient([
            _page([1, 2], cursor=2),
            _page([3, 4], cursor=4),
            _page([5], cursor=5),
            _page([], cursor=5),  # burst over
        ])
        rec = Recorder()
        doorbell = ChannelDoorbell(
            client, rec, settings=DoorbellSettings(coalesce_s=1.0, cooldown_s=0.0, poll_s=0.1)
        )
        await _run_until(doorbell, 1)

        assert len(rec.sent) == 1
        assert rec.sent[0][1]["meta"]["count"] == "5"
        assert rec.sent[0][1]["meta"]["highest_id"] == "5"

    @pytest.mark.anyio
    async def test_cursor_advances_past_everything_absorbed(self) -> None:
        client = ScriptedClient([
            _page([1, 2], cursor=2),
            _page([3], cursor=7),
            _page([], cursor=7),
        ])
        doorbell = ChannelDoorbell(
            ScriptedClient([]) if False else client, Recorder(),
            settings=DoorbellSettings(coalesce_s=1.0, cooldown_s=0.0, poll_s=0.1),
        )
        await _run_until(doorbell, 1)
        assert doorbell.cursor == 7


class TestFailure:
    @pytest.mark.anyio
    async def test_a_transport_error_is_a_re_arm_never_an_answer(self) -> None:
        """Rakes #22/#139. The loop must not ring on a failure and must not
        die on one — it holds its cursor and tries again."""
        client = ScriptedClient([
            httpx.ConnectError("board unreachable"),
            _page([42], cursor=42),
        ])
        rec = Recorder()
        doorbell = ChannelDoorbell(
            client, rec,
            settings=DoorbellSettings(
                coalesce_s=0.0, cooldown_s=0.0, poll_s=0.1, backoff_s=0.01
            ),
        )
        await _run_until(doorbell, 1)

        assert len(rec.sent) == 1
        assert rec.sent[0][1]["meta"]["count"] == "1"

    @pytest.mark.anyio
    async def test_a_failed_send_does_not_kill_the_loop(self) -> None:
        """The lane is the session's only remaining wake; a bad send must
        not be what ends it."""
        class Broken(Recorder):
            async def __call__(self, method: str, params: dict) -> None:
                self.sent.append((method, params))
                raise RuntimeError("wire closed")

        client = ScriptedClient([_page([1], cursor=1), _page([2], cursor=2)])
        rec = Broken()
        doorbell = ChannelDoorbell(client, rec, settings=NO_WAIT)

        task = asyncio.create_task(doorbell.run())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(rec.sent) >= 2, "the loop stopped after a failed send"
        assert doorbell.rings == 0, "a failed send must not count as a ring"


class TestIdentityFollowsTheRebind:
    """#1011 — the stamp must track `korax_animate`, not startup.

    The poll already follows a rebind, because `rebind()` mutates the same
    `KoraxClient` the doorbell holds. The STAMP did not: it was captured in
    `__init__`, which runs at `notifications/initialized` — **before any
    session could have animated** — so a snapshot was stale in the normal
    case, not an edge case.

    Every test here rebinds in the middle. That is the point: the defect is
    that the two paths disagree AFTER a rebind, and no test that never
    rebinds can see it.
    """

    class Config:
        def __init__(self, identity: str, url: str = "https://board.one") -> None:
            self.identity = identity
            self.url = url

    class RebindableClient(ScriptedClient):
        """Scripted, plus a gate so the rebind genuinely lands BETWEEN rings.

        Without the gate the loop drains every page before the test's next
        statement runs, and the animate happens after both rings — which
        makes the test pass or fail on scheduling rather than on the
        behaviour. The gate is the difference between testing the fix and
        testing the event loop.
        """

        def __init__(self, pages, identity: str, head: int | None = 100) -> None:
            super().__init__(pages, head=head)
            self.config = TestIdentityFollowsTheRebind.Config(identity)
            self.gate = asyncio.Event()
            self._gate_after = 1

        def rebind(self, identity: str) -> None:
            self.config = TestIdentityFollowsTheRebind.Config(identity)

        async def feed(self, since: int = -1, timeout: float = 60.0):
            if len(self.calls) >= self._gate_after:
                await self.gate.wait()
            return await super().feed(since=since, timeout=timeout)

    @pytest.mark.anyio
    async def test_stamp_follows_an_animate_between_rings(self) -> None:
        ambient, quill = "band:31ae86919bea", "band:2887f5287fd2"
        client = self.RebindableClient(
            [_page([1], cursor=1), _page([2], cursor=2)], identity=ambient
        )
        rec = Recorder()
        doorbell = ChannelDoorbell(client, rec, settings=NO_WAIT)

        await _run_until(doorbell, 1)
        assert rec.sent[0][1]["meta"]["identity"] == ambient

        client.rebind(quill)  # exactly what korax_animate does
        client.gate.set()
        await _run_until(doorbell, 2)
        assert rec.sent[-1][1]["meta"]["identity"] == quill, (
            "the doorbell stamped the band it was BUILT with, not the one it "
            "is polling for — #1011"
        )

    @pytest.mark.anyio
    async def test_explicit_identity_still_overrides_for_tests(self) -> None:
        client = self.RebindableClient([_page([1], cursor=1)], identity="band:aaa")
        rec = Recorder()
        doorbell = ChannelDoorbell(
            client, rec, settings=NO_WAIT, identity="band:pinned"
        )
        await _run_until(doorbell, 1)
        assert rec.sent[0][1]["meta"]["identity"] == "band:pinned"

    @pytest.mark.anyio
    async def test_board_url_is_read_live_too(self) -> None:
        client = self.RebindableClient([_page([1], cursor=1)], identity="band:aaa")
        rec = Recorder()
        doorbell = ChannelDoorbell(client, rec, settings=NO_WAIT)
        await _run_until(doorbell, 1)
        assert rec.sent[0][1]["meta"]["board_url"] == "https://board.one"

    @pytest.mark.anyio
    async def test_a_client_without_config_does_not_crash_the_ring(self) -> None:
        """A missing stamp is acceptable; a dead lane is not."""
        client = ScriptedClient([_page([1], cursor=1)])  # no `.config` at all
        rec = Recorder()
        doorbell = ChannelDoorbell(client, rec, settings=NO_WAIT)
        await _run_until(doorbell, 1)
        assert "identity" not in rec.sent[0][1]["meta"]


class TestSettings:
    def test_defaults_are_the_documented_ones(self) -> None:
        s = DoorbellSettings()
        assert (s.enabled, s.coalesce_s, s.cooldown_s) == (True, 2.0, 30.0)

    def test_env_disables(self) -> None:
        assert DoorbellSettings.from_env({"KORAX_CHANNEL": "0"}).enabled is False
        assert DoorbellSettings.from_env({"KORAX_CHANNEL": "off"}).enabled is False
        assert DoorbellSettings.from_env({"KORAX_CHANNEL": "true"}).enabled is True

    def test_env_overrides_the_bounds(self) -> None:
        s = DoorbellSettings.from_env(
            {"KORAX_CHANNEL_COALESCE_S": "5", "KORAX_CHANNEL_COOLDOWN_S": "90"}
        )
        assert (s.coalesce_s, s.cooldown_s) == (5.0, 90.0)

    def test_nonsense_is_refused_rather_than_defaulted(self) -> None:
        """A doorbell running on a default the operator thought they had
        overridden looks exactly like one running on their setting."""
        with pytest.raises(ValueError):
            DoorbellSettings.from_env({"KORAX_CHANNEL": "maybe"})
        with pytest.raises(ValueError):
            DoorbellSettings.from_env({"KORAX_CHANNEL_COOLDOWN_S": "soon"})

    def test_disabled_never_rings(self) -> None:
        async def go() -> None:
            client = ScriptedClient([_page([1], cursor=1)])
            rec = Recorder()
            doorbell = ChannelDoorbell(
                client, rec, settings=DoorbellSettings(enabled=False)
            )
            await asyncio.wait_for(doorbell.run(), timeout=1.0)
            assert rec.sent == []
            assert client.calls == []

        asyncio.run(go())
