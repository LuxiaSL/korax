"""The two seams between our server and the host's channel lane.

JOB #995. Both reach past the SDK's public surface, and the brief's
ruling 1 permits that **on the condition that the failure is loud**:

    #987 forbade the `_lowlevel_server` reach-in in anything that merges.
    That was right for a spike and wrong to carry forward — the
    alternative is dropping to the lowlevel `Server` and giving up
    `@server.tool()` across the whole tool surface, a large rewrite
    bought for a stylistic point.

**The rake being dodged is that both failures are otherwise silent.** A
capability quietly undeclared produces `kind:"capability"` inside the
host, no wake ever, and a session that looks exactly like a quiet board
(#171, again). A notifier that cannot reach the wire produces the same
nothing. So each seam is checked at startup, against the SDK actually
installed, and a break is an exception with the reason in it — not a
warning, and never a `None` that flows on.

`tests/test_channel_seam.py` fails RED if either seam moves. That test is
the condition of this module's existence; delete it and the dependency
becomes the silent one the brief refused.

### The upstream ask

`MCPServer` (the FastMCP wrapper) does not plumb `experimental_capabilities`
through to `create_initialization_options()`, though the lowlevel `Server`
accepts the argument — `mcp/server/lowlevel/server.py` takes it and
`mcp/server/mcpserver/server.py` calls with no arguments on both run
paths. That is a small, reasonable gap to report upstream; when a
passthrough lands, `declare_channel_capability()` collapses to one
keyword argument at construction and this module keeps only the notifier.

`ServerRunner.init_options` looks like the seam and is not: it is public
and documented as the `InitializeResult` payload, and nothing populates
it on the stdio path (#991).
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

# What we declare, and only what we implement. #997 measured that
# `claude/channel` ALONE registers — the second key, `claude/channel/
# permission`, is sufficient but not necessary — and a doorbell answers no
# permission round trip. Declaring a capability we do not implement would
# advertise a path nothing here serves.
CHANNEL_CAPABILITY = "claude/channel"
CHANNEL_CAPABILITIES: dict[str, dict[str, Any]] = {CHANNEL_CAPABILITY: {}}

# The kwarg and attribute this module depends on, named once so the guard
# rail and the error messages cannot drift apart from the code they guard.
LOWLEVEL_ATTR = "_lowlevel_server"
INIT_OPTIONS_METHOD = "create_initialization_options"
EXPERIMENTAL_KWARG = "experimental_capabilities"
SESSION_CONNECTION_ATTR = "_connection"
CONNECTION_NOTIFY_METHOD = "notify"


# NO INSTRUCTIONS BLOCK HERE ANY MORE (#1065, JOB #1070).
#
# There was one, and it was written in the indicative about a lane that may
# not exist: this server cannot observe whether the host accepted the
# channel, so it cannot honestly tell a session it has a doorbell. The claim
# now lives in the charter fragment in the only form that is true on every
# host — *a doorbell is proven only by a wake arriving* — beside the watch's
# own obligation, so one paragraph serves both lanes and neither promises
# what it cannot check.

class ChannelSeamError(RuntimeError):
    """An SDK internal this module depends on has moved.

    Raised rather than warned. The whole point of the guard rail is that
    the alternative — carrying on with the capability undeclared — is
    indistinguishable from a working server on a quiet board.
    """


def check_capability_seam(server: Any) -> None:
    """Verify the capability seam before relying on it.

    Two things must hold: the wrapper still exposes the lowlevel server,
    and that server's `create_initialization_options` still accepts the
    experimental-capabilities mapping. Either moving means our declaration
    silently stops reaching the wire.
    """
    low = getattr(server, LOWLEVEL_ATTR, None)
    if low is None:
        raise ChannelSeamError(
            f"MCPServer has no `{LOWLEVEL_ATTR}`. The channel capability is "
            "declared by reaching through the FastMCP wrapper to the lowlevel "
            f"server, because the wrapper never passes `{EXPERIMENTAL_KWARG}` "
            "through. That attribute has moved or been renamed, so "
            f"`{CHANNEL_CAPABILITY}` would go undeclared — which the host "
            "reports as kind:'capability' and which looks, from inside a "
            "session, exactly like a board with nothing to say."
        )

    factory = getattr(low, INIT_OPTIONS_METHOD, None)
    if factory is None or not callable(factory):
        raise ChannelSeamError(
            f"the lowlevel server has no callable `{INIT_OPTIONS_METHOD}`; "
            "the channel capability cannot be declared."
        )

    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError) as exc:  # pragma: no cover - exotic callables
        raise ChannelSeamError(
            f"could not inspect `{INIT_OPTIONS_METHOD}` to confirm it still "
            f"accepts `{EXPERIMENTAL_KWARG}`: {exc}"
        ) from exc

    if EXPERIMENTAL_KWARG not in signature.parameters:
        raise ChannelSeamError(
            f"`{INIT_OPTIONS_METHOD}` no longer accepts `{EXPERIMENTAL_KWARG}` "
            f"(parameters: {sorted(signature.parameters)}). The SDK's way of "
            "declaring experimental capabilities has changed; declaring "
            f"`{CHANNEL_CAPABILITY}` needs rewiring against the new one."
        )


def declare_channel_capability(
    server: Any, capabilities: Mapping[str, dict[str, Any]] | None = None
) -> None:
    """Declare `claude/channel` in this server's `initialize` result.

    Wraps the lowlevel factory rather than replacing the options object:
    every other capability the wrapper derives from registered handlers
    (tools, prompts, resources) keeps deriving normally, and we add one
    key. `setdefault` so an explicit caller-supplied mapping still wins.
    """
    check_capability_seam(server)
    declared = dict(capabilities if capabilities is not None else CHANNEL_CAPABILITIES)

    low = getattr(server, LOWLEVEL_ATTR)
    original = getattr(low, INIT_OPTIONS_METHOD)

    def with_channel(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault(EXPERIMENTAL_KWARG, declared)
        return original(*args, **kwargs)

    setattr(low, INIT_OPTIONS_METHOD, with_channel)


def check_notifier_seam(session: Any) -> None:
    """Verify the raw-notification seam before relying on it.

    `ServerSession.send_notification` takes a typed `ServerNotification`,
    which is a closed union of the SDK's own methods —
    `notifications/claude/channel` is not in it and cannot be. The raw
    path is the connection's own `notify(method, params)`, which is public
    on `Connection`; only reaching the connection off the session is not.
    """
    connection = getattr(session, SESSION_CONNECTION_ATTR, None)
    if connection is None:
        raise ChannelSeamError(
            f"ServerSession has no `{SESSION_CONNECTION_ATTR}`. The doorbell "
            f"sends `{CONNECTION_NOTIFY_METHOD}` on the connection-scoped "
            "channel because the typed notification union has no member for a "
            "host-specific method. That attribute has moved, so no doorbell "
            "would ever reach the host — silently, since a wake that is never "
            "sent and a board with no news are the same nothing."
        )
    notify = getattr(connection, CONNECTION_NOTIFY_METHOD, None)
    if notify is None or not callable(notify):
        raise ChannelSeamError(
            f"the connection has no callable `{CONNECTION_NOTIFY_METHOD}`; "
            "the doorbell has no way onto the wire."
        )


def connection_notifier(session: Any) -> Any:
    """A `Notifier` bound to this session's connection-scoped channel."""
    check_notifier_seam(session)
    connection = getattr(session, SESSION_CONNECTION_ATTR)

    async def notify(method: str, params: Mapping[str, Any]) -> None:
        await getattr(connection, CONNECTION_NOTIFY_METHOD)(method, dict(params))

    return notify
