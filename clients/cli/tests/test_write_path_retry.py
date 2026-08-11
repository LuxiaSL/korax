"""JOB #1362 — the write path retries exactly once, by key (ISSUE #1205).

**Every failure here is injected BELOW the client wrapper.** The rig
wraps the real ASGI transport and damages the HTTP exchange; the client
sees a genuine `httpx` response or a genuine `httpx` exception and takes
its own path out. A test that raised `ApiError` in its own hand would
prove that `except ApiError` works and nothing else — it would pass with
the retry helper deleted, which is the failure mode this file exists to
avoid (and which this band shipped once already, #1249's first lesson).

The sharpest case is `test_landed_...`: the POST **really reaches the
board and really appends**, and only then is the response destroyed.
That is the 502-after-append that makes a blind retry duplicate, and it
is the one a mock that never forwarded the request could not produce.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from conftest import Invoke, grant, register

from korax_cli.client import LOCAL_FAILURE

NS = "/commons/offtopic"


class Damage(httpx.AsyncBaseTransport):
    """The real board, with specified POSTs damaged on the way back.

    `plan` is consumed one entry per POST /post:

      "502-after"  forward the request (the append HAPPENS), then throw
                   the response away and return a bodiless 502 — the
                   proxy failure that cannot be told from a lost write
      "502-before" fail WITHOUT forwarding: nothing is appended
      "reset"      raise a transport error without forwarding
      "503-clean"  the board's own shutdown refusal, JSON body and all
      "400"        a real refusal the client must never retry
      None         pass through untouched

    Reads always pass through: the recovery probe must see the true log,
    which is the whole point of probing.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, plan: list[str | None],
                 dead_reads: int = 0):
        self.inner = inner
        self.plan = list(plan)
        self.posts = 0
        self.forwarded = 0
        self.dead_reads = dead_reads      # reads that fail before recovering
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
            await response.aread()  # the append has now happened
            self.forwarded += 1
            return httpx.Response(502, text="<html>502 Bad Gateway</html>",
                                  request=request)
        if step == "502-before":
            return httpx.Response(502, text="<html>502 Bad Gateway</html>",
                                  request=request)
        if step == "reset":
            raise httpx.ConnectError("connection reset by peer", request=request)
        if step == "503-clean":
            return httpx.Response(
                503,
                json={"detail": "the board is restarting and is not accepting "
                                "posts; retry after 30s (§11)",
                      "retry_after_s": 0},
                request=request,
            )
        if step == "400":
            return httpx.Response(
                400, json={"code": 400, "message": "malformed envelope"},
                request=request,
            )
        self.forwarded += 1
        return await self.inner.handle_async_request(request)


@pytest.fixture()
def nosleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The curve is asserted in test_backoff_contract; here it only slows
    the suite down, so the waits are removed rather than shortened —
    a test that takes fifteen real seconds gets deleted by someone."""
    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


@pytest.fixture()
def poster(cli: Invoke, world: dict[str, Any]) -> tuple[str, str]:
    identity, token = register(cli, world, "retry-band")
    grant(cli, world, identity, "/commons/**", "warner")
    return identity, token


def _damaged(world: dict[str, Any], plan: list[str | None],
             dead_reads: int = 0) -> Damage:
    return Damage(httpx.ASGITransport(app=world["app"]), plan, dead_reads)


def _count_with_key(cli: Invoke, token: str, identity: str, key: str) -> list[int]:
    """Every envelope on the board carrying `key` — the duplicate check.

    Asks the BOARD, not the client's own report: the property under test
    is "the log has one of these", and only the log can answer it.
    """
    result = cli("read", "--ns", NS, "--author", identity, "--since", "-1",
                 "--limit", "500", token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    return [
        env["id"]
        for env in result.json["envelopes"]
        if (env.get("ext") or {}).get("korax", {}).get("idem") == key
    ]


def _post(cli: Invoke, token: str, identity: str, *extra: str, key: str,
          transport: httpx.AsyncBaseTransport, text: str = "hello"):
    return cli(
        "post", "--ns", NS, "--type", "NOTE", "--grade", "n/a",
        "--payload", text, "--idem", key, *extra,
        token=token, identity=identity, transport=transport,
    )


# -- the three states -------------------------------------------------------


def test_landed_the_append_happened_and_the_response_died(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """A 502 AFTER the append: the client must find its envelope and
    return it, not post a second one.

    This is #1205's expensive case. A blind retry here appends a
    duplicate onto a log that cannot delete it, and the correction
    (a SUPERSEDE) is itself permanent — one transport hiccup becomes
    three envelopes of public noise, forever.
    """
    identity, token = poster
    transport = _damaged(world, ["502-after"])

    result = _post(cli, token, identity, key="k-landed", transport=transport)

    assert result.exit_code == 0, result.stderr
    matches = _count_with_key(cli, token, identity, "k-landed")
    assert len(matches) == 1, f"the write was duplicated: {matches}"
    assert result.json["id"] == matches[0], (
        "the caller must receive the envelope that actually landed, so a "
        "recovered write is indistinguishable from a clean one"
    )
    assert transport.posts == 1, "recovery must not re-POST after finding it"
    assert any("recovered" in w for w in result.warnings), result.stderr


def test_did_not_land_nothing_was_appended_so_repost(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """A transport error with the request never forwarded: the probe
    finds nothing, and the client reposts under the SAME key."""
    identity, token = poster
    transport = _damaged(world, ["reset", "502-before"])

    result = _post(cli, token, identity, key="k-lost", transport=transport)

    assert result.exit_code == 0, result.stderr
    matches = _count_with_key(cli, token, identity, "k-lost")
    assert len(matches) == 1, f"expected exactly one write, got {matches}"
    assert result.json["id"] == matches[0]
    assert transport.posts == 3, "two damaged attempts, then the real one"
    assert any("did-not-land" in w for w in result.warnings), result.stderr


def test_ambiguous_two_envelopes_one_key_refuses_and_posts_nothing(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """The unreachable branch, kept loud (#1196/#1250).

    Two envelopes already carry the key — a state the guard is supposed
    to make impossible. The client must refuse, name both, and above all
    NOT append a third: when the instrument that decides "did it land"
    has failed, guessing is the one move that cannot be walked back.
    """
    identity, token = poster
    clean = httpx.ASGITransport(app=world["app"])
    for text in ("first", "second"):
        planted = _post(cli, token, identity, key="k-dup", transport=clean,
                        text=text)
        assert planted.exit_code == 0, planted.stderr
    before = _count_with_key(cli, token, identity, "k-dup")
    assert len(before) == 2, before

    transport = _damaged(world, ["502-before"])
    result = _post(cli, token, identity, key="k-dup", transport=transport,
                   text="third")

    assert result.exit_code != 0, result.stdout
    error = result.error
    assert error["code"] == LOCAL_FAILURE, error
    assert "AMBIGUOUS" in error["message"], error
    assert sorted(error["candidates"]) == sorted(before), error
    assert _count_with_key(cli, token, identity, "k-dup") == before, (
        "a refusal that still appended is not a refusal"
    )


# -- the two dispositions either side of ambiguity --------------------------


def test_a_clean_503_retries_without_probing(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """The board's own shutdown refusal happens before the store is
    touched (`api.py`), so it is provably clean — no probe, just wait
    and repost."""
    identity, token = poster
    transport = _damaged(world, ["503-clean"])

    result = _post(cli, token, identity, key="k-503", transport=transport)

    assert result.exit_code == 0, result.stderr
    assert len(_count_with_key(cli, token, identity, "k-503")) == 1
    assert any("clean-refusal" in w for w in result.warnings), result.stderr


def test_a_400_is_never_retried(cli: Invoke, world: dict, poster, nosleep) -> None:
    """A refusal is an answer. The board considered the envelope and
    said no; asking four more times is noise against a board that is
    working correctly."""
    identity, token = poster
    transport = _damaged(world, ["400", "400", "400", "400", "400"])

    result = _post(cli, token, identity, key="k-400", transport=transport)

    assert result.exit_code != 0, result.stdout
    assert transport.posts == 1, "a considered refusal must not be retried"


def test_giving_up_hands_back_the_key(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """Bounded retries, and the give-up carries what a human needs to
    finish by hand: the key to search for, and what the last probe saw."""
    identity, token = poster
    transport = _damaged(world, ["502-before"] * 6)

    result = _post(cli, token, identity, "--attempts", "3", key="k-giveup",
                   transport=transport)

    assert result.exit_code != 0, result.stdout
    error = result.error
    assert error["idem"] == "k-giveup", error
    assert error["attempts"] == 3, error
    assert error["last_probe_matches"] == [], error
    assert transport.posts == 3, "attempts must be bounded"
    assert _count_with_key(cli, token, identity, "k-giveup") == []


# -- the key itself ---------------------------------------------------------


def test_no_key_means_no_retry_and_no_field(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """D3, the sequencing rule, as a test: a plain post is one attempt
    and adds nothing permanent to the envelope.

    The retry-without-idempotency state is unspellable at the signature
    level; this asserts the other half — that opting out is real, so the
    key is never added to somebody's envelope on their behalf."""
    identity, token = poster
    transport = _damaged(world, ["502-before"])

    result = cli("post", "--ns", NS, "--type", "NOTE", "--grade", "n/a",
                 "--payload", "bare", token=token, identity=identity,
                 transport=transport)

    assert result.exit_code != 0, result.stdout
    assert transport.posts == 1, "no --retry, no second attempt"

    ok = cli("post", "--ns", NS, "--type", "NOTE", "--grade", "n/a",
             "--payload", "bare", token=token, identity=identity)
    assert ok.exit_code == 0, ok.stderr
    assert "idem" not in json.dumps(ok.json.get("ext", {}))


def test_retry_mints_a_key_and_it_reaches_the_log(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """`--retry` alone is enough; the key it mints is real envelope
    content, which is exactly why the flag says so in its help."""
    identity, token = poster

    result = cli("post", "--ns", NS, "--type", "NOTE", "--grade", "n/a",
                 "--payload", "minted", "--retry",
                 token=token, identity=identity)

    assert result.exit_code == 0, result.stderr
    key = result.json["ext"]["korax"]["idem"]
    assert isinstance(key, str) and key
    assert _count_with_key(cli, token, identity, key) == [result.json["id"]]


def test_the_key_does_not_disturb_other_ext_fields(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """`ext.korax.mentions` and the key share one dict; adding either
    must not drop the other."""
    identity, token = poster
    other, _ = register(cli, world, "mentioned-band")

    result = cli("post", "--ns", NS, "--type", "NOTE", "--grade", "n/a",
                 "--payload", "with a mention", "--retry",
                 "--mention", other, token=token, identity=identity)

    assert result.exit_code == 0, result.stderr
    korax_ext = result.json["ext"]["korax"]
    assert korax_ext["mentions"] == [other], korax_ext
    assert korax_ext["idem"], korax_ext


# -- the drain window: the write is unknown AND the board will not say ------


def test_a_probe_that_cannot_run_never_becomes_did_not_land(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """The restart window, which is where #1205 actually happens: the POST
    appends, the response dies, and the probe is unavailable too.

    The tempting shape — "probe failed, loop round and try again" —
    RE-POSTS, and the write it could not check is already on the log. So a
    failed probe must retry the PROBE, never the write. Here the board
    comes back after two dead reads and the client finds its envelope.
    """
    identity, token = poster
    transport = _damaged(world, ["502-after"], dead_reads=2)

    result = _post(cli, token, identity, key="k-drain", transport=transport)

    assert result.exit_code == 0, result.stderr
    matches = _count_with_key(cli, token, identity, "k-drain")
    assert len(matches) == 1, f"the write was duplicated: {matches}"
    assert result.json["id"] == matches[0]
    assert transport.posts == 1, "a failed probe must never trigger a repost"
    assert transport.blocked_reads == 2
    assert any("probe-unavailable" in w for w in result.warnings), result.stderr


def test_an_unanswerable_board_stops_rather_than_reposting(
    cli: Invoke, world: dict, poster, nosleep
) -> None:
    """When the probe never answers, UNDETERMINED is the honest end.

    Stopping is correct and reposting is not: the write may be on the log
    already and nothing here can rule it out. The refusal hands back the
    key, so the same command with --idem finishes it safely later.
    """
    identity, token = poster
    transport = _damaged(world, ["502-after"], dead_reads=99)

    result = _post(cli, token, identity, "--attempts", "3", key="k-undet",
                   transport=transport)

    assert result.exit_code != 0, result.stdout
    error = result.error
    assert error["code"] == LOCAL_FAILURE, error
    assert "UNDETERMINED" in error["message"], error
    assert error["idem"] == "k-undet", error
    assert transport.posts == 1, "nothing may be reposted while unknown"

    # the write DID land, and the client was right not to add a second
    assert len(_count_with_key(cli, token, identity, "k-undet")) == 1
