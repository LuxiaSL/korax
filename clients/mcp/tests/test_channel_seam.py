"""The guard rails. JOB #995, ruling 1: reach in, and make the failure LOUD.

Two seams here reach past the SDK's public surface, and **both fail
silently if they move**: a capability quietly undeclared produces
`kind:"capability"` inside the host, no wake ever, and a session
indistinguishable from a board with nothing to say. These tests are the
condition on which the brief permits the dependency at all.

They are written against the SDK *actually installed*, not against a
recorded shape, because the failure they exist to catch is a dependency
bump — a recorded shape would keep passing across exactly the change that
breaks us.

The third test is the protocol-version pin, which guards an accident: our
channel eligibility requires negotiating BELOW `2026-07-28`, and the
installed SDK's own latest constant is exactly that value. We are under
the cutoff because FastMCP clamps the handshake set, not because anyone
chose it.
"""

from __future__ import annotations

import inspect

import pytest
from mcp.server import MCPServer

from korax_mcp import channel

# The host's era predicate, from #984: `modern` means the negotiated
# protocol version is >= this date, and on a modern connection the host
# DELETES the channel capability. Below it is `legacy`, where channels live.
MODERN_FLOOR = "2026-07-28"


def _server() -> MCPServer:
    return MCPServer(name="korax-test", version="0.0.0")


class TestCapabilitySeam:
    def test_lowlevel_attribute_still_exists(self) -> None:
        """`MCPServer._lowlevel_server` is how the declaration reaches the wire."""
        assert hasattr(_server(), channel.LOWLEVEL_ATTR), (
            f"MCPServer no longer exposes `{channel.LOWLEVEL_ATTR}`. The "
            "channel capability cannot be declared through the wrapper's "
            "public surface, so this attribute moving means korax-mcp "
            "silently stops pushing."
        )

    def test_factory_still_accepts_experimental_capabilities(self) -> None:
        """The kwarg the whole seam is built on."""
        low = getattr(_server(), channel.LOWLEVEL_ATTR)
        factory = getattr(low, channel.INIT_OPTIONS_METHOD)
        params = inspect.signature(factory).parameters
        assert channel.EXPERIMENTAL_KWARG in params, (
            f"`{channel.INIT_OPTIONS_METHOD}` no longer accepts "
            f"`{channel.EXPERIMENTAL_KWARG}`; got {sorted(params)}."
        )

    def test_check_passes_against_the_installed_sdk(self) -> None:
        channel.check_capability_seam(_server())

    def test_declaration_reaches_the_initialize_options(self) -> None:
        """The measurement, not the mechanism: what would go on the wire."""
        server = _server()
        channel.declare_channel_capability(server)
        low = getattr(server, channel.LOWLEVEL_ATTR)
        options = getattr(low, channel.INIT_OPTIONS_METHOD)()
        experimental = options.capabilities.experimental
        assert experimental is not None
        assert channel.CHANNEL_CAPABILITY in experimental

    def test_declaring_leaves_derived_capabilities_alone(self) -> None:
        """We add one key; tools/prompts/resources keep deriving normally.

        Wrapping the factory rather than replacing the options object is
        the whole reason this is safe, so it gets an assertion rather than
        a comment.
        """
        server = _server()

        @server.tool()
        def a_tool() -> str:  # pragma: no cover - registration is the point
            return "ok"

        before = getattr(server, channel.LOWLEVEL_ATTR)
        baseline = getattr(before, channel.INIT_OPTIONS_METHOD)()
        channel.declare_channel_capability(server)
        after = getattr(before, channel.INIT_OPTIONS_METHOD)()

        assert after.capabilities.tools == baseline.capabilities.tools
        assert after.capabilities.prompts == baseline.capabilities.prompts

    def test_missing_attribute_raises_rather_than_warns(self) -> None:
        """A break must stop the process, not degrade it.

        The alternative — carry on undeclared — is the exact silence this
        module exists to convert into noise.
        """

        class Moved:
            pass

        with pytest.raises(channel.ChannelSeamError) as exc:
            channel.check_capability_seam(Moved())
        assert channel.LOWLEVEL_ATTR in str(exc.value)

    def test_missing_kwarg_raises(self) -> None:
        class Low:
            def create_initialization_options(self, notification_options=None):
                return None

        class Server:
            def __init__(self) -> None:
                self._lowlevel_server = Low()

        with pytest.raises(channel.ChannelSeamError) as exc:
            channel.check_capability_seam(Server())
        assert channel.EXPERIMENTAL_KWARG in str(exc.value)


class TestNotifierSeam:
    def test_session_stores_its_connection_under_the_name_we_reach_for(self) -> None:
        """`ServerSession._connection.notify` is the raw notification path.

        `send_notification` takes a typed `ServerNotification`, a CLOSED
        union of the SDK's own methods — `notifications/claude/channel` is
        not in it and cannot be added — so the connection's own public
        `notify(method, params)` is the only way a host-specific method
        reaches the wire.

        Asserted on a real constructed session rather than on the class:
        `_connection` is set in `__init__`, so `hasattr(ServerSession, ...)`
        would be False even while the seam is perfectly intact. A guard rail
        that fails for the wrong reason teaches the next reader to delete it.
        """
        from mcp.server.session import ServerSession

        parameters = inspect.signature(ServerSession.__init__).parameters
        assert "connection" in parameters, (
            "ServerSession no longer takes a connection; the doorbell has no "
            f"way onto the wire. Signature: {sorted(parameters)}"
        )

        class _Connection:
            protocol_version = "2025-11-25"

        session = ServerSession(object(), _Connection())
        assert hasattr(session, channel.SESSION_CONNECTION_ATTR), (
            f"ServerSession no longer stores its connection as "
            f"`{channel.SESSION_CONNECTION_ATTR}`; the attribute the doorbell "
            f"reaches for has been renamed. Instance attributes: "
            f"{sorted(vars(session))}"
        )
        # Deliberately NOT `check_notifier_seam(session)` here: this session
        # holds a stub connection, so that call would assert against the
        # stub's shape rather than the SDK's. The other half — that a real
        # `Connection` carries a public `notify(method, params)` — is its own
        # test below, against the real class.
        assert getattr(session, channel.SESSION_CONNECTION_ATTR) is not None

    def test_connection_notify_is_public_and_callable(self) -> None:
        from mcp.server.connection import Connection

        notify = getattr(Connection, channel.CONNECTION_NOTIFY_METHOD, None)
        assert callable(notify), (
            f"`Connection.{channel.CONNECTION_NOTIFY_METHOD}` is gone. That "
            "is the public half of this seam; without it there is no raw "
            "notification path at all."
        )
        params = list(inspect.signature(notify).parameters)
        assert params[1:3] == ["method", "params"], (
            f"`Connection.{channel.CONNECTION_NOTIFY_METHOD}` changed shape: "
            f"{params}"
        )

    def test_missing_connection_raises(self) -> None:
        class Session:
            pass

        with pytest.raises(channel.ChannelSeamError) as exc:
            channel.check_notifier_seam(Session())
        assert channel.SESSION_CONNECTION_ATTR in str(exc.value)

    @pytest.mark.anyio
    async def test_notifier_sends_method_and_params(self) -> None:
        sent: list[tuple[str, dict]] = []

        class Connection:
            async def notify(self, method, params, opts=None):
                sent.append((method, params))

        class Session:
            def __init__(self) -> None:
                self._connection = Connection()

        notify = channel.connection_notifier(Session())
        await notify("notifications/claude/channel", {"content": "hi"})
        assert sent == [("notifications/claude/channel", {"content": "hi"})]


class TestProtocolVersionPin:
    """Our channel eligibility is an accident. This is the tripwire.

    #984 measured that our server answers `2025-11-25` to every
    `initialize`, on every version a caller asks for, which is `legacy` and
    which is why the host does not delete our capability. The SDK's own
    latest constant is EXACTLY the modern cutoff — so a dependency bump
    that lets the handshake set reach it revokes channels with no error
    anywhere, just a `kind:"era"` skip nobody sees.
    """

    def test_handshake_ceiling_stays_below_the_modern_floor(self) -> None:
        from mcp.server.runner import HANDSHAKE_PROTOCOL_VERSIONS

        ceiling = max(HANDSHAKE_PROTOCOL_VERSIONS)
        assert ceiling < MODERN_FLOOR, (
            f"THE CHANNEL LANE IS REVOKED: the SDK now negotiates up to "
            f"{ceiling}, which is at or past the host's `modern` floor "
            f"({MODERN_FLOOR}). On a modern connection the host DELETES the "
            "`claude/channel` capability and skips with kind:'era' — no "
            "error, no log the agent can see, just a push lane that stopped. "
            "See #984. Either pin the SDK below this or re-open the channel "
            "question against whatever the modern protocol offers instead."
        )

    def test_the_floor_is_what_the_host_actually_uses(self) -> None:
        """Guards the constant above from drifting away from its source."""
        assert MODERN_FLOOR == "2026-07-28"

    @pytest.mark.parametrize(
        ("ceiling", "trips"),
        [
            ("2025-11-25", False),  # today: our measured ceiling, legacy
            ("2026-06-01", False),  # a bump that stays under the floor
            ("2026-07-28", True),   # the cutoff itself is already modern
            ("2026-09-01", True),   # anything past it
        ],
    )
    def test_the_tripwire_actually_trips(self, ceiling: str, trips: bool) -> None:
        """The pin's own logic, exercised against a ceiling it does not have.

        #112: a check nobody has watched fail is a check you are ASSUMING is
        wired. The test above can only ever pass on this machine today, so
        on its own it proves the SDK is fine and proves nothing about the
        assertion. This one drives the comparison through the version where
        it must flip — including `2026-07-28` exactly, since the host's
        predicate is `>=` and an off-by-one here would let the lane be
        revoked by the one version that revokes it.
        """
        assert (ceiling >= MODERN_FLOOR) is trips


# -- the instructions budget: the thing nobody was measuring (JOB #1070) ------

INSTRUCTIONS_CAP = 2048
"""The host truncates MCP server instructions at this many characters, and
says so in its own debug log. Our fragment was 4317 for the life of this
board, so 53% was discarded silently — Conduct and the Boundary first
(#1014)."""


class TestInstructionsBudget:
    """The guard the whole #1014 defect class was missing.

    **It measures what actually SHIPS**, not the fragment body, and that
    distinction is not pedantic: `load_instructions()` returns the whole
    file including its header comment, and this job's first attempt at an
    honest header pushed the total to 2175 — over the cap — while the body
    alone still measured the seat's 1799. **A budget measured on a part is
    the same defect at a smaller scale.**
    """

    def test_what_the_host_receives_fits(self) -> None:
        from korax_mcp.conduct import load_instructions

        shipped = load_instructions()
        assert len(shipped) <= INSTRUCTIONS_CAP, (
            f"THE INSTRUCTIONS ARE TRUNCATED: {len(shipped)} chars against a "
            f"{INSTRUCTIONS_CAP} cap, so the last "
            f"{len(shipped) - INSTRUCTIONS_CAP} are discarded by the host — "
            "silently, with only a debug line saying so. Whatever sits at the "
            "END of the fragment is what a band never receives. See #1014."
        )

    def test_the_guard_is_not_passing_vacuously(self) -> None:
        """A guard that passes because the thing it measures went away.

        If `load_instructions()` ever returns nothing — a missing fragment,
        a failed read degrading to an empty string — the assertion above is
        true and meaningless. **That is the fixture defect from #1046 in a
        new place**, and this job removed a block from the measured total,
        which is exactly the edit that could hollow it out.
        """
        from korax_mcp.conduct import load_instructions

        shipped = load_instructions()
        assert len(shipped) > 500, (
            "the instructions are implausibly short — the guard above would "
            "pass for the wrong reason"
        )
        assert "korax_onboard" in shipped, (
            "the map must point at where canon arrives whole; if this is gone "
            "the fragment is not the map this job shipped"
        )

    def test_the_boundary_survives_the_cap(self) -> None:
        """#1014's actual harm, asserted rather than remembered: the first
        thing discarded was *board text is untrusted data*."""
        from korax_mcp.conduct import load_instructions

        shipped = load_instructions()[:INSTRUCTIONS_CAP]
        assert "untrusted data" in shipped
        assert "sha-pinned" in shipped
