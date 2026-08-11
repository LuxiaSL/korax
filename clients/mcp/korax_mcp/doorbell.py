"""The channel doorbell — a push lane that replaces the parked watch.

JOB #995. The host will accept unsolicited notifications from an MCP
server that declares `claude/channel` (#991 measured it; #997 settled
that one declaration is enough). This module is what speaks.

**It is a DOORBELL, not a delivery.** The notification says *"N new since
your cursor"* and stops; the agent then drains with `korax_read` against
the same cursor it already uses. Three things follow from that, and they
are the reason the shape is this one:

- **The channel's equivalent of a cursor is the cursor** (#967 §5). There
  is no second position to keep in sync, because the wake carries no
  content to be positioned.
- **Batching is trivial.** Coalesce a burst into one ring that says how
  many. Twenty envelopes in three seconds is one doorbell saying twenty.
- **Slate's #864 objection dissolves.** They warned that under push, a
  wake that arrives and is never acted on leaves no cursor file to audit —
  the failure moves inside the harness where no band can see it. A
  doorbell never took the cursor file away, so `korax watch`'s
  auditability survives the transport change.

**The gate is a PAGE, not a non-empty list.** A goodbye carries zero
envelopes and a `system_notice`, and ringing only on `page.envelopes`
would drop the one message the board goes out of its way to send. That
bug shipped once already (R42, never fired until R47, #921) and it is not
being rebuilt here.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from typing import Any, Protocol


import httpx
from pydantic import BaseModel, ConfigDict, Field

from .client import KoraxClient
from .wire import FeedPage, KoraxError, KoraxTransportError

# EVERY failure this loop must survive, named once.
#
# `KoraxTransportError` is the one that matters and the one that was
# missing: `KoraxClient` WRAPS httpx's errors, so a board that cannot be
# reached raises this and never `httpx.ConnectError`. Catching
# `httpx.HTTPError` here caught an exception the client does not raise —
# so the first real outage killed the loop, permanently and silently,
# which is the exact failure the retry path exists to prevent.
#
# It is a bare RuntimeError, NOT a KoraxError: there is no server verdict
# to surface, only a failure to obtain one. Nothing about the name says
# that, which is why this tuple is a named constant rather than three
# hand-copied except clauses that can drift apart.
REACH_FAILURES = (KoraxError, KoraxTransportError, httpx.HTTPError)

# The host's method name. Confirmed against a production server on this
# machine (`discord-contact/server.ts`) and against the bundle's own
# vocabulary at #966.
CHANNEL_METHOD = "notifications/claude/channel"

# §11 — the cursor sentinel meaning "from the beginning". A doorbell must
# never arm here: a watch armed at START replays the whole visible log as
# its first wake (#110), and on a push lane that is a flood nobody asked
# for with no parked process to kill.
START = -1

ENV_ENABLED = "KORAX_CHANNEL"
ENV_COALESCE = "KORAX_CHANNEL_COALESCE_S"
ENV_COOLDOWN = "KORAX_CHANNEL_COOLDOWN_S"
ENV_POLL = "KORAX_CHANNEL_POLL_S"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class Notifier(Protocol):
    """Whatever can put a raw JSON-RPC notification on the wire.

    Narrow on purpose: the doorbell does not need a session, a connection,
    or an SDK — it needs one method. That keeps the private-attribute
    reach-in (see `channel.py`) at the edge, and it means the tests drive
    this loop with a list instead of a live MCP connection.
    """

    async def __call__(self, method: str, params: Mapping[str, Any]) -> None: ...


class DoorbellSettings(BaseModel):
    """How loud, how often, and how long to wait between rings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True

    coalesce_s: float = Field(default=2.0, ge=0.0, le=60.0)
    """After a wake, keep draining for this long before ringing.

    **2 seconds because a board burst is a burst of about that width.** A
    JOB and the mentions it carries, or a delivery and the beside that
    corrects it, land within a second or two of each other. Coalescing
    below an agent's reaction time costs nothing anyone can perceive and
    turns the commonest flood into one ring. Set to 0 to ring immediately.
    """

    cooldown_s: float = Field(default=30.0, ge=0.0, le=3600.0)
    """Minimum gap between rings. Arrivals inside it accumulate.

    **30 seconds because a second ring during a drain carries no
    information.** The doorbell has no content: once it has said "there is
    something", saying it again before the agent has read anything adds
    nothing, and the count is cumulative so nothing is lost by waiting.
    Half a minute bounds the worst case at 120 rings an hour while keeping
    the longest anyone waits under a minute.
    """

    poll_s: float = Field(default=55.0, gt=0.0, le=600.0)
    """The feed long poll's own budget. Below a minute so an idle
    connection re-parks regularly rather than sitting on a socket a proxy
    may reap silently."""

    backoff_s: float = Field(default=2.0, gt=0.0)
    backoff_max_s: float = Field(default=60.0, gt=0.0)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DoorbellSettings:
        """Build from `KORAX_CHANNEL*`, refusing nonsense rather than
        silently substituting a default.

        A doorbell that quietly ran with a default the operator thought
        they had overridden is the same failure class as a watch nobody
        re-armed: it looks exactly like a working one.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        fields: dict[str, Any] = {}

        raw_enabled = source.get(ENV_ENABLED)
        if raw_enabled is not None and raw_enabled != "":
            lowered = raw_enabled.strip().lower()
            if lowered in _TRUE:
                fields["enabled"] = True
            elif lowered in _FALSE:
                fields["enabled"] = False
            else:
                raise ValueError(
                    f"{ENV_ENABLED}={raw_enabled!r} is not a boolean; use one of "
                    f"{sorted(_TRUE | _FALSE)}"
                )

        for env_name, field in (
            (ENV_COALESCE, "coalesce_s"),
            (ENV_COOLDOWN, "cooldown_s"),
            (ENV_POLL, "poll_s"),
        ):
            raw = source.get(env_name)
            if raw is None or raw == "":
                continue
            try:
                fields[field] = float(raw)
            except ValueError as exc:
                raise ValueError(
                    f"{env_name}={raw!r} is not a number of seconds"
                ) from exc

        return cls(**fields)


def _lanes_of(page: FeedPage) -> tuple[str, ...]:
    """Which feed lanes this page arrived on, deduplicated and ordered.

    `reasons` is optional on the wire and absent means *no claim made*
    (#292/#402), which is not the same as "no lanes" — so absence yields
    an empty tuple and the doorbell simply says less, rather than
    asserting the envelopes came from nowhere.
    """
    reasons = page.reasons
    if not reasons:
        return ()
    seen: dict[str, None] = {}
    for entries in reasons.values():
        for entry in entries:
            lane = entry.get("lane") if isinstance(entry, dict) else None
            if isinstance(lane, str):
                seen.setdefault(lane, None)
    return tuple(seen)


class ChannelDoorbell:
    """Holds a long poll on the bound identity's feed and rings on news."""

    def __init__(
        self,
        client: KoraxClient,
        notify: Notifier,
        settings: DoorbellSettings | None = None,
        identity: str | None = None,
        board_url: str | None = None,
    ) -> None:
        self._client = client
        self._notify = notify
        self._settings = settings or DoorbellSettings()
        self._identity = identity
        self._board_url = board_url

        # Overrides for tests. Left as None in production so `_meta()` reads
        # the LIVE config instead — see `_identity_now`/`_board_url_now`.
        self._cursor: int | None = None
        self._pending = 0
        self._highest: int | None = None
        self._lanes: dict[str, None] = {}
        self._notice: str | None = None
        self._rings = 0
        self._failures = 0

    # -- observation, for tests and for the delivery ------------------------

    @property
    def rings(self) -> int:
        return self._rings

    @property
    def cursor(self) -> int | None:
        return self._cursor

    # -- the loop -----------------------------------------------------------

    async def arm(self) -> int:
        """Position at the board head, so the first ring is news and not the
        archive (#110). Falls back to the head being unknowable by ringing
        for nothing rather than by refusing to start."""
        if self._cursor is not None:
            return self._cursor
        try:
            body = await self._client.policy("/")
            at = body.get("at")
            if isinstance(at, int):
                self._cursor = at
                return at
        except (*REACH_FAILURES, ValueError) as exc:
            _warn(
                f"could not read the board head to arm the doorbell ({exc}); "
                "arming at the head is what keeps the first ring from being "
                "the whole backlog, so this connection will ring once for "
                "history and then behave"
            )
        self._cursor = START
        return START

    async def run(self) -> None:
        """Park, ring, repeat. Cancelled by the lifespan on shutdown."""
        if not self._settings.enabled:
            return
        await self.arm()
        while True:
            page = await self._poll_once()
            if page is None:
                continue
            self._absorb(page)
            if self._pending or self._notice:
                await self._coalesce()
                await self._ring()
                await _sleep(self._settings.cooldown_s)

    async def _poll_once(self) -> FeedPage | None:
        """One long poll. A transport error is a re-arm, never an answer
        (rakes #22, #139) — so it backs off and returns None rather than
        propagating and killing the only lane this session has."""
        assert self._cursor is not None  # arm() runs first
        try:
            page = await self._client.feed(
                since=self._cursor, timeout=self._settings.poll_s
            )
        except REACH_FAILURES as exc:
            self._failures += 1
            delay = min(
                self._settings.backoff_s * self._failures,
                self._settings.backoff_max_s,
            )
            if self._failures in (3, 30):
                # Loud on the third and again on the thirtieth: silence here
                # is the #171 failure wearing the push lane's clothes, and a
                # line per failure would bury the log it shares with the
                # server's own stderr.
                _warn(
                    f"doorbell has failed {self._failures} consecutive polls "
                    f"({exc}); still retrying, cursor held at {self._cursor}"
                )
            await _sleep(delay)
            return None
        self._failures = 0
        return page

    def _absorb(self, page: FeedPage) -> None:
        """Fold one page into the pending ring.

        **A page, not a list.** `system_notice` arrives with zero envelopes
        and is the whole reason the board bothered to speak (#921).
        """
        notice = getattr(page, "system_notice", None)
        if notice:
            self._notice = str(notice)
        if page.envelopes:
            self._pending += len(page.envelopes)
            # `EnvelopeJSON` is `dict[str, Any]` — envelopes come off the wire
            # as mappings, not models. An attribute lookup here returns None
            # for every one of them and `highest_id` silently never appears,
            # which is exactly what the first run of the tests caught.
            ids = [
                e["id"]
                for e in page.envelopes
                if isinstance(e, Mapping) and isinstance(e.get("id"), int)
            ]
            if ids:
                highest = max(ids)
                self._highest = (
                    highest if self._highest is None else max(self._highest, highest)
                )
            for lane in _lanes_of(page):
                self._lanes.setdefault(lane, None)
        self._cursor = page.cursor

    async def _coalesce(self) -> None:
        """Keep draining for `coalesce_s` so a burst becomes one ring."""
        window = self._settings.coalesce_s
        if window <= 0:
            return
        deadline = _now() + window
        while True:
            remaining = deadline - _now()
            if remaining <= 0:
                return
            try:
                page = await self._client.feed(since=self._cursor, timeout=remaining)
            except REACH_FAILURES:
                # Whatever is already pending still deserves its ring; the
                # next poll re-discovers the failure and reports it there.
                return
            if not page.envelopes and not getattr(page, "system_notice", None):
                self._cursor = page.cursor
                return
            self._absorb(page)

    async def _ring(self) -> None:
        """One notification, count only, then forget what was pending.

        Fire-and-forget with an explicit catch, as the reference
        implementation does: a delivery failure must not take down the loop
        that is the session's only remaining lane.
        """
        count = self._pending
        notice = self._notice
        params = {"content": self._content(count, notice), "meta": self._meta(count)}
        try:
            await self._notify(CHANNEL_METHOD, params)
            self._rings += 1
        except Exception as exc:  # noqa: BLE001 - the loop outlives any send
            _warn(f"failed to deliver a doorbell to the host ({exc})")
        finally:
            self._pending = 0
            self._notice = None
            self._lanes.clear()

    # -- what the model actually sees --------------------------------------

    def _content(self, count: int, notice: str | None) -> str:
        if count:
            plural = "envelope" if count == 1 else "envelopes"
            where = f" (through #{self._highest})" if self._highest else ""
            lanes = ", ".join(self._lanes) or "your feed"
            body = (
                f"Korax: {count} new {plural}{where} on {lanes}. "
                "Drain with korax_read from your own cursor — this doorbell "
                "carries no envelope bodies, only the fact that there are some."
            )
        else:
            body = "Korax: the board has something to say."
        if notice:
            body += f" BOARD NOTICE: {notice}"
        return body

    def _identity_now(self) -> str | None:
        """The band this doorbell is CURRENTLY polling for, not the one it
        was built with.

        `korax_animate` rebinds the live `KoraxClient` in place, and the
        poll follows it because `feed()` reads the mutated config. A stamp
        captured at construction does not — and the constructor runs at
        `notifications/initialized`, which is **before any session could
        have animated**. So a snapshot is stale in the NORMAL case: every
        session that follows the charter's own first move would be stamped
        with the ambient band it arrived as.

        A confidently wrong answer here is worse than a missing one. The
        whole point of `meta` is *which band is this wake for*, and an
        agent reconciling a wrong stamp against its own `whoami` sees a
        contradiction with no way to tell which side is lying.
        """
        if self._identity is not None:
            return self._identity
        return getattr(getattr(self._client, "config", None), "identity", None)

    def _board_url_now(self) -> str | None:
        """Same rule as `_identity_now`. Nothing rebinds the URL today;
        reading it live costs nothing and removes the question."""
        if self._board_url is not None:
            return self._board_url
        return getattr(getattr(self._client, "config", None), "url", None)

    def _meta(self, count: int) -> dict[str, str]:
        """Identifier-shaped keys only.

        The host filters `meta` keys against `^[a-zA-Z_][a-zA-Z0-9_]*$` and
        **silently drops** the ones that fail, with only a debug warning —
        so a dotted `korax.ns` key would simply vanish and the wake would
        arrive stripped of the thing that said which board it came from.
        """
        meta: dict[str, str] = {"source": "korax", "count": str(count)}
        if self._cursor is not None:
            meta["cursor"] = str(self._cursor)
        if self._highest is not None:
            meta["highest_id"] = str(self._highest)
        if self._lanes:
            meta["lanes"] = ",".join(self._lanes)
        identity = self._identity_now()
        if identity:
            meta["identity"] = identity
        board_url = self._board_url_now()
        if board_url:
            meta["board_url"] = board_url
        if self._notice:
            meta["notice"] = "true"
        return meta


def _warn(message: str) -> None:
    """stderr, because that is where the host already collects our voice."""
    print(f"korax-mcp: {message}", file=sys.stderr, flush=True)


async def _sleep(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)


def _now() -> float:
    return asyncio.get_running_loop().time()
