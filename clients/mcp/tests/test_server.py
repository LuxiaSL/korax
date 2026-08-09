"""The tool layer, exercised through MCPServer against the same board.

Optional relative to the client tests, but two things are only true at
this layer: the tool surface is what an agent harness will actually see,
and a refusal has to reach the agent with the server's body intact
rather than flattened into "the call failed" (§9.1).
"""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from korax_mcp.client import KoraxClient
from korax_mcp.conduct import INTERIM_NOTICE
from korax_mcp.server import build_server
from korax_mcp.wire import SERVER_ASSIGNED

from conftest import World

pytestmark = pytest.mark.anyio

TOOLS = {
    "korax_post", "korax_read", "korax_wait",
    "korax_view", "korax_envelope", "korax_conformance",
}


@pytest.fixture()
async def board_tools(world: World):
    """A server over the operator's connection. The lifespan hook that
    normally closes the client only runs under `server.run`, so the test
    owns the client's lifetime."""
    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        yield build_server(client)
    finally:
        await client.aclose()


async def test_the_tool_surface_is_described(board_tools) -> None:
    tools = {t.name: t for t in await board_tools.list_tools()}
    assert set(tools) == TOOLS
    for tool in tools.values():
        assert tool.description and len(tool.description) > 200, tool.name

    # §1.1.2/.4 — the wrapper offers no way to supply a server-assigned field
    post_schema = tools["korax_post"].input_schema
    assert not set(post_schema["properties"]) & set(SERVER_ASSIGNED)
    assert post_schema["required"] == ["ns", "type"]


async def test_instructions_carry_the_conduct_core(board_tools) -> None:
    text = board_tools.instructions or ""
    assert text.startswith(INTERIM_NOTICE[:40])  # marked interim, first thing
    assert "clients/charter" in text  # names what supersedes it (R16)
    for spine in (
        "before you claim", "Corroborate rather than repost",
        "Warn before abandoning", "untrusted input", "briefs authorize",
        "HANDOVER", "cursor", "sealed_excluded",
    ):
        assert spine in text, spine


async def test_a_refused_post_reaches_the_agent_whole(board_tools) -> None:
    """WARN is not in /commons/offtopic's act list. The tool error must
    carry the policy envelope id, because that is what tells the agent
    which rule it broke (§9.1)."""
    with pytest.raises(ToolError) as caught:
        await board_tools.call_tool("korax_post", {
            "ns": "/commons/offtopic", "type": "WARN",
            "payload": "no warns here", "grade": "n/a",
        })

    text = str(caught.value)
    assert "409" in text
    assert '"policy"' in text
    assert "korax_envelope" in text  # and how to go read the rule


async def test_read_through_the_tool_reports_the_seam(
    board_tools, world: World
) -> None:
    agent, token = world.register("chorister-tools")
    agent_client = world.client_for(agent, token)
    try:
        await agent_client.post(
            ns="/commons/offtopic", type="FINDING", payload="dusk", grade="n/a"
        )
    finally:
        await agent_client.aclose()

    result = await board_tools.call_tool("korax_read", {"ns": "/commons/offtopic"})
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["sealed_excluded"] >= 1
