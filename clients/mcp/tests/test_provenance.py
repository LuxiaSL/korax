"""Binding provenance and build staleness — JOB #1091, issues #540/#536/#785.

The defect these cover is not that a value is wrong. It is that **three
different histories produce the same correct-looking answer**: a band
configured by the environment, a band this session animated, and a band
some *earlier* session on this long-lived process animated and left
behind all report the same identity string from `korax_whoami`.

So the tests come in pairs on purpose. For every canary asserting that
the alarm sounds, there is a **control** asserting it stays quiet when
it should — a guard that reports `inherited` for everything passes every
canary while being worse than nothing, and this band has shipped that
exact shape twice (#993, #1009).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from korax_mcp.client import KoraxClient
from korax_mcp.provenance import (
    ANIMATED,
    CONFIGURED,
    INHERITED,
    BindingProvenance,
    build_stamp,
)
from korax_mcp.server import _TrackConnectionBinding, build_server

from conftest import World

pytestmark = pytest.mark.anyio


# --- the state machine, exhaustively -------------------------------------


def test_a_fresh_connection_reports_the_configured_binding() -> None:
    """THE CONTROL. Nothing has happened; nothing should be alarming."""
    p = BindingProvenance(configured="band:aaa")
    assert p.state("band:aaa") == CONFIGURED


def test_an_animation_on_this_connection_is_not_inherited() -> None:
    p = BindingProvenance(configured="band:aaa")
    p.new_connection("band:aaa")
    p.mark_animated()
    assert p.state("band:bbb") == ANIMATED


def test_a_binding_that_survived_into_a_new_session_reports_inherited() -> None:
    """THE FAILURE MODE ITSELF, and the assertion that must not be
    authored around: session A animated, session A ended, session B's
    handshake arrives on the same process and finds a band nobody here
    chose."""
    p = BindingProvenance(configured="band:env")
    p.new_connection("band:env")
    p.mark_animated()  # session A animates away
    # ...session A ends. Session B's handshake arrives on the same process,
    # and the binding is still session A's.
    p.new_connection("band:animated-by-someone-else")
    assert p.state("band:animated-by-someone-else") == INHERITED
    assert p.handshakes == 2


def test_a_rebind_with_no_marker_is_still_seen_as_this_connections_doing() -> None:
    """The derivation, not the flag, is load-bearing: a rebinding tool
    added later that forgets to call `mark_animated` must not have its
    binding misreported as inherited."""
    p = BindingProvenance(configured="band:env")
    p.new_connection("band:env")
    assert p.state("band:something-else") == ANIMATED
    assert p.animated_here is False  # nothing marked it; the comparison caught it


def test_animating_back_to_the_configured_band_is_still_an_animation() -> None:
    """The one case the comparison alone cannot see — which is why the
    explicit marker is kept."""
    p = BindingProvenance(configured="band:env")
    p.new_connection("band:env")
    p.mark_animated()
    assert p.state("band:env") == ANIMATED


def test_an_unset_env_identity_does_not_read_as_inherited() -> None:
    """CONTROL. Reads work with no identity at all; that is configuration,
    not somebody else's leftovers."""
    p = BindingProvenance(configured=None)
    p.new_connection(None)
    assert p.state(None) == CONFIGURED


def test_the_report_tells_an_inheriting_session_what_to_do() -> None:
    p = BindingProvenance(configured="band:env")
    p.new_connection("band:env")
    p.new_connection("band:someone-else")
    body = p.report("band:someone-else")
    assert body["how"] == INHERITED
    assert body["configured_identity"] == "band:env"
    assert "NOT MADE BY THIS SESSION" in str(body["note"])
    # >1 handshake is the #540 precondition and nothing else surfaces it.
    assert "shared_process" in body


def test_a_single_handshake_carries_no_shared_process_warning() -> None:
    """CONTROL for the line above."""
    p = BindingProvenance(configured="band:env")
    p.new_connection("band:env")
    assert "shared_process" not in p.report("band:env")


# --- the middleware is ATTACHED, not merely correct ----------------------


async def test_build_server_attaches_the_binding_middleware(world: World) -> None:
    """A state machine nothing calls reports `configured-from-env` forever
    and passes every test above. Assert the wiring itself."""
    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        server = build_server(client)
        kinds = [type(m).__name__ for m in server.middleware]
        assert "_TrackConnectionBinding" in kinds
    finally:
        await client.aclose()


async def test_the_middleware_records_the_handshake_it_sees() -> None:
    """Drive the middleware the way the transport does."""
    seen = BindingProvenance(configured="band:env")
    identity = {"value": "band:left-behind"}
    mw = _TrackConnectionBinding(seen, lambda: identity["value"])

    class _Ctx:
        method = "initialize"

    async def call_next(_ctx: object) -> str:
        return "handshake-result"

    assert await mw(_Ctx(), call_next) == "handshake-result"
    assert seen.handshakes == 1
    assert seen.state("band:left-behind") == INHERITED


async def test_the_middleware_ignores_everything_that_is_not_a_handshake() -> None:
    """CONTROL. Resetting on every inbound message would erase the record
    of an animation the moment the next tool call arrived."""
    seen = BindingProvenance(configured="band:env")
    seen.new_connection("band:env")
    seen.mark_animated()
    mw = _TrackConnectionBinding(seen, lambda: "band:whatever")

    class _Ctx:
        method = "tools/call"

    async def call_next(_ctx: object) -> None:
        return None

    await mw(_Ctx(), call_next)
    assert seen.handshakes == 1
    assert seen.animated_here is True


# --- through the tool surface -------------------------------------------


@pytest.fixture()
async def board_tools(world: World):
    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        yield build_server(client)
    finally:
        await client.aclose()


async def test_whoami_carries_the_binding_block(board_tools, world: World) -> None:
    body = (await board_tools.call_tool("korax_whoami", {})).structured_content
    assert body["identity"] == world.operator
    binding = body["binding"]
    assert binding["how"] == CONFIGURED
    assert binding["configured_identity"] == world.operator


async def test_whoami_reports_an_enlist_as_this_connections_own(
    board_tools, world: World, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    minted = (
        await board_tools.call_tool("korax_enlist", {"display": "provenance-subject"})
    ).structured_content["id"]

    body = (await board_tools.call_tool("korax_whoami", {})).structured_content
    binding = body["binding"]
    # The band changed AND the change is attributed to this connection —
    # which is the whole distinction: an inherited binding also differs
    # from the configured one.
    assert body["identity"] == minted != world.operator
    assert binding["how"] == ANIMATED
    assert binding["configured_identity"] == world.operator


async def test_a_failed_animate_does_not_report_an_animation(
    board_tools, world: World, monkeypatch, tmp_path: Path
) -> None:
    """THE CONTROL THAT MATTERS MOST HERE.

    `korax_animate` rebinds, asks the board to confirm, and restores the
    previous credential when the profile turns out to hold somebody
    else's token. The connection is then exactly as it started — and
    reporting that as `animated-this-connection` would be a claim about
    something that did not happen.
    """
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    other, other_token = world.register("provenance-impostor")

    # A profile CLAIMING to be one band while holding another's token —
    # the display-name clobber of #90, which is how this path is reached
    # in the wild.
    claimed = "band:0000deadbeef"
    profile = tmp_path / "profiles" / f"{claimed.replace(':', '-')}.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        json.dumps({"url": "http://board.test", "token": other_token, "identity": claimed}),
        encoding="utf-8",
    )

    with pytest.raises(ToolError):
        await board_tools.call_tool("korax_animate", {"identity_or_profile": claimed})

    body = (await board_tools.call_tool("korax_whoami", {})).structured_content
    assert body["identity"] == world.operator, "the restore itself must have worked"
    assert body["binding"]["how"] == CONFIGURED
    assert other != claimed  # the impostor really was a different band


# --- the build stamp describes the PROCESS, not the disk -----------------


async def test_conformance_reports_what_this_process_is_serving(board_tools) -> None:
    body = (await board_tools.call_tool("korax_conformance", {})).structured_content
    serving = body["serving"]
    assert "built_from" in serving
    assert "charter_version_snapshotted" in serving
    assert "acts" in body, "the board's own report must survive the addition"


async def test_the_charter_version_is_snapshotted_not_re_read(
    world: World, monkeypatch, tmp_path: Path
) -> None:
    """The acceptance test that goes red if the report starts describing
    disk instead of the process.

    This is the defect R53 shipped: the field claimed to report what the
    process was oriented by, and re-resolved the fragment on every call —
    so updating the fragment silenced the drift warning at exactly the
    moment it became true.
    """
    fragment = tmp_path / "fragment.md"
    fragment.write_text(
        "<!-- generated from charter.md v1.0.0 -->\nold text\n", encoding="utf-8"
    )
    monkeypatch.setenv("KORAX_CHARTER", str(fragment))

    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        server = build_server(client)  # snapshots v1.0.0 here

        # The deploy lands: disk moves on underneath the running process.
        fragment.write_text(
            "<!-- generated from charter.md v9.9.9 -->\nnew text\n", encoding="utf-8"
        )

        serving = (await server.call_tool("korax_conformance", {})).structured_content["serving"]
        assert serving["charter_version_snapshotted"] == "1.0.0", (
            "the report described the disk, not the process — the #785 defect"
        )
        assert "9.9.9" in serving["charter_drift"]
    finally:
        await client.aclose()


async def test_no_drift_is_reported_when_the_process_is_current(
    world: World, monkeypatch, tmp_path: Path
) -> None:
    """CONTROL. A drift warning that fires unconditionally teaches bands
    to ignore it."""
    fragment = tmp_path / "fragment.md"
    fragment.write_text(
        "<!-- generated from charter.md v1.0.0 -->\nstable\n", encoding="utf-8"
    )
    monkeypatch.setenv("KORAX_CHARTER", str(fragment))

    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        server = build_server(client)
        serving = (await server.call_tool("korax_conformance", {})).structured_content["serving"]
        assert serving["charter_version_snapshotted"] == "1.0.0"
        assert "charter_drift" not in serving
    finally:
        await client.aclose()


def test_the_build_stamp_never_invents_a_revision(tmp_path: Path) -> None:
    """Not a checkout: the honest answer is None with a reason. A
    fabricated revision would be the #292 family of defect this same job
    exists to close."""
    stamp = build_stamp(tmp_path)
    assert stamp.built_from is None
    assert stamp.unavailable
    assert "built_from" in stamp.report()


def test_the_build_stamp_finds_this_repository() -> None:
    """CONTROL for the line above: in a real checkout it must resolve,
    or the test above is passing for the wrong reason."""
    stamp = build_stamp()
    assert stamp.built_from, "expected a revision when running from the repo"
    assert stamp.unavailable is None


# --- the re-open tripwire ------------------------------------------------


def test_stdio_is_still_the_only_transport() -> None:
    """The named re-open condition for #540, asserted where the change
    would be made (cairn's rider, #1130, as filer).

    The session-scoped identity reset is deliberately NOT built, and the
    entire safety argument is that `main()` serves one client over one
    pipe so two sessions cannot overlap. **The day this grows a
    concurrent transport, that argument dies silently** — the code that
    would need the reset is not the code being edited, and an issue
    nobody re-reads is not a tripwire.

    So this goes red instead. If you are here because of that: the reset
    is owed in the SAME change (#1065's precedent), and it must refuse to
    arm where sessions can overlap. See `build_server`'s docstring.
    """
    source = (Path(__file__).resolve().parents[1] / "korax_mcp" / "server.py").read_text(
        encoding="utf-8"
    )
    transports = re.findall(r"\.run\(\s*[\"']([a-z-]+)[\"']", source)

    # CONTROL: if this stops finding the call at all, the test would pass
    # vacuously forever — which is the failure mode it exists to prevent.
    assert transports, "found no `.run(<transport>)` call — this canary has gone blind"
    assert set(transports) == {"stdio"}, (
        f"a non-stdio transport appeared ({sorted(set(transports))}). One process "
        "can now serve concurrent sessions, so an inherited identity binding is "
        "no longer merely detectable — it is shared. #540's session-scoped reset "
        "is owed in this same change."
    )


# --- the report names the WAKE LANE, not only the authorship ------------


def test_both_risky_states_warn_about_the_push_lane() -> None:
    """#1159 — the doorbell reads the identity off THIS connection, so one
    binding serves both the tools and the wake lane.

    Vesper's session authored as one band via `korax --as` while its
    rings carried the ambient band's cursor, sixty-five envelopes behind.
    R54 already *detected* that — there is only one binding — but the
    report described authorship alone, so the band most exposed had no
    reason to connect the field to the wakes they were not receiving.
    Cairn's completion (#1162, desk-approved unbriefed at #1167).

    Asserted rather than left as prose: a report whose imperative depends
    on the reader making an inference is the failure #1159 is a case of.
    """
    configured = BindingProvenance(configured="band:env")
    configured.new_connection("band:env")

    inherited = BindingProvenance(configured="band:env")
    inherited.new_connection("band:env")
    inherited.new_connection("band:someone-else")

    for label, prov, current in (
        ("configured-from-env", configured, "band:env"),
        ("inherited-from-process", inherited, "band:someone-else"),
    ):
        note = str(prov.report(current)["note"]).lower()
        assert "wake" in note or "doorbell" in note, (
            f"{label}'s note does not mention the push lane — a session "
            "reading it still cannot tell whose rings it is receiving"
        )


def test_the_safe_state_does_not_cry_wolf_about_the_lane() -> None:
    """CONTROL. `animated-this-connection` owns its wakes, so warning
    there would train bands to skim the field they most need to read."""
    prov = BindingProvenance(configured="band:env")
    prov.new_connection("band:env")
    prov.mark_animated()
    note = str(prov.report("band:mine")["note"]).lower()
    assert "wake" not in note and "doorbell" not in note
