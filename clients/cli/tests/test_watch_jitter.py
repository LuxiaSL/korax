"""ISSUE #1370 — the goodbye page's spread, which the comment promised
and the code never had. Light-tracked at #1372 §3.

**The delays are captured from the sleep that ACTUALLY FIRES inside
`cmd_watch`**, not from `backoff.py` in isolation — `test_backoff_contract`
already pins the curve, and a unit test of a helper cannot tell you the
watch calls it. The ruling asked for exactly this distinction.

Two properties, and the FLOOR is the one that matters more. A spread that
could answer EARLY would be worse than the herd it fixes: `retry_after_s`
is the board saying "I will not be ready before this", so a client that
returns sooner arrives mid-restart. Upward-only, always.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from conftest import Invoke

GOODBYE = {
    "envelopes": [],
    "cursor": 7,
    "sealed_excluded": 0,
    "rotated_excluded": 0,
    "participation_excluded": 0,
    "withheld_scope": "board",
    "system_notice": {
        "kind": "restart",
        "note": "the board is restarting",
        "retry_after_s": 30,
    },
}


class _Stop(Exception):
    """Ends the `--repeat` loop at its first sleep. The loop is infinite by
    design; a test that let it run would hang rather than fail."""


@pytest.fixture()
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Every delay `cmd_watch` asks for, in order — then stop the loop."""
    seen: list[float] = []

    async def capture(seconds: float) -> None:
        seen.append(seconds)
        raise _Stop

    monkeypatch.setattr(asyncio, "sleep", capture)
    return seen


def _goodbye_transport() -> httpx.AsyncBaseTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/feed", "/wait"):
            return httpx.Response(200, json=GOODBYE, request=request)
        return httpx.Response(200, json={"identity": "band:test",
                                         "display": "t", "grants": []},
                              request=request)
    return httpx.MockTransport(handler)


def _dead_transport() -> httpx.AsyncBaseTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("board is down", request=request)
    return httpx.MockTransport(handler)


def _watch(cli: Invoke, world: dict, tmp_path, transport, extra=()):
    try:
        return cli("watch", "--repeat", "--cursor-file",
                   str(tmp_path / "c.cursor"), *extra,
                   token=world["op_token"], identity=world["operator"],
                   transport=transport)
    except _Stop:
        return None


def test_the_goodbye_wait_is_spread_and_never_early(
    cli: Invoke, world: dict, tmp_path, slept: list[float]
) -> None:
    """`retry_after_s: 30` must produce a wait of AT LEAST 30 — and,
    across runs, not always exactly 30.

    The floor is asserted on every sample; the spread is asserted over
    many, because any single draw may legitimately sit near the floor.
    """
    for _ in range(40):
        _watch(cli, world, tmp_path, _goodbye_transport())

    assert slept, "the goodbye page did not reach a sleep at all"
    assert all(d >= 30.0 for d in slept), (
        f"a client answered EARLIER than the board asked: {min(slept)} < 30. "
        "That is worse than the herd — it returns a client to a board that "
        "is still restarting"
    )
    assert len(set(slept)) > 1, (
        f"every wait was identical ({slept[0]}): this is #1370 — the comment "
        "demands a spread and the code slept exactly retry_after_s"
    )
    assert max(slept) <= 45.0, f"spread exceeded the +50% bound: {max(slept)}"


def test_the_failure_path_is_spread_too(
    cli: Invoke, world: dict, tmp_path, slept: list[float]
) -> None:
    """Watches that fail together hold identical `failures` counters, so
    an unjittered escalating curve re-synchronizes them — the same herd
    by a slower route (#1370's second half)."""
    for _ in range(40):
        _watch(cli, world, tmp_path, _dead_transport())

    assert slept, "a transport failure did not reach a sleep"
    assert all(d >= 5.0 for d in slept), min(slept)
    assert len(set(slept)) > 1, (
        f"every failure wait was identical ({slept[0]}): the failure path "
        "still re-synchronizes every watch on this host"
    )


def test_a_zero_retry_after_stays_zero(
    cli: Invoke, world: dict, tmp_path, slept: list[float]
) -> None:
    """`retry_after_s: 0` means "now"; the spread must not invent a wait
    where the board asked for none."""
    page = dict(GOODBYE, system_notice=dict(GOODBYE["system_notice"],
                                            retry_after_s=0))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/feed", "/wait"):
            return httpx.Response(200, json=page, request=request)
        return httpx.Response(200, json={"identity": "band:test",
                                         "display": "t", "grants": []},
                              request=request)

    for _ in range(10):
        _watch(cli, world, tmp_path, httpx.MockTransport(handler))

    assert slept and all(d == 0.0 for d in slept), slept
