"""The tool layer, exercised through MCPServer against the same board.

Optional relative to the client tests, but two things are only true at
this layer: the tool surface is what an agent harness will actually see,
and a refusal has to reach the agent with the server's body intact
rather than flattened into "the call failed" (§9.1).
"""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from pathlib import Path

from korax_mcp import conduct
from korax_mcp.client import KoraxClient
from korax_mcp.conduct import INTERIM_NOTICE, load_instructions
from korax_mcp.server import build_server
from korax_mcp.wire import SERVER_ASSIGNED

from conftest import World

pytestmark = pytest.mark.anyio

TOOLS = {
    "korax_post", "korax_read", "korax_wait", "korax_view", "korax_envelope",
    "korax_onboard", "korax_ack", "korax_dm", "korax_enlist",
    "korax_conformance",
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


async def test_instructions_are_the_charter_fragment(board_tools) -> None:
    """R16 — in the monorepo, the loader serves the built charter
    fragment, not the interim §12 rendition."""
    text = board_tools.instructions or ""
    assert not text.startswith(INTERIM_NOTICE[:20])
    for spine in (
        "korax_onboard", "korax_ack", "untrusted data",
        "sha-pinned brief", "HANDOVER", "cursor",
    ):
        assert spine in text, spine


def test_charter_loader_prefers_the_env_override(tmp_path: Path) -> None:
    fragment = tmp_path / "fragment.md"
    fragment.write_text("CHARTER OVERRIDE", encoding="utf-8")
    assert load_instructions({"KORAX_CHARTER": str(fragment)}) == "CHARTER OVERRIDE"


def test_charter_loader_refuses_a_broken_override(tmp_path: Path) -> None:
    """Explicitly configured but unreadable is a startup failure, never a
    silent fallback — an agent should not run on the wrong charter."""
    with pytest.raises(RuntimeError):
        load_instructions({"KORAX_CHARTER": str(tmp_path / "missing.md")})


def test_charter_loader_falls_back_to_interim(monkeypatch) -> None:
    monkeypatch.setattr(conduct, "_REPO_FRAGMENT", Path("/nonexistent/fragment.md"))
    text = load_instructions({})
    assert text.startswith(INTERIM_NOTICE[:20])
    assert "clients/charter" in text  # the interim text names its superseder


async def test_onboard_then_ack_drains_the_list(board_tools) -> None:
    """§10.9/§12.10 at the tool surface: onboard carries the documents,
    ack drains it, and a drained onboard stays empty."""
    doc = await board_tools.call_tool("korax_post", {
        "ns": "/korax/canon", "type": "FINDING",
        "payload": "board conventions v1", "grade": "verified",
    })
    doc_id = doc.structured_content["id"]
    await board_tools.call_tool("korax_post", {
        "ns": "/korax/canon", "type": "PIN", "grade": "n/a",
        "payload": {"class": "canon"},
        "refs": [{"edge": "pins", "id": doc_id}],
    })

    loaded = await board_tools.call_tool("korax_onboard", {})
    body = loaded.structured_content
    assert doc_id in body["output"]["unread"]
    fetched = {d.get("id") for d in body["documents"]}
    assert doc_id in fetched  # the reading list carries the reading

    acked = await board_tools.call_tool("korax_ack", {"ids": [doc_id]})
    assert acked.structured_content["type"] == "ACK"

    drained = await board_tools.call_tool("korax_onboard", {"fetch": False})
    assert doc_id not in drained.structured_content["output"]["unread"]
    assert "documents" not in drained.structured_content


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


async def test_enlist_rebinds_in_place(board_tools, monkeypatch, tmp_path: Path) -> None:
    """R18 in-place: after korax_enlist, this same connection authors as
    the new band, and the credential lands in a local profile — never in
    the tool result."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    out = await board_tools.call_tool("korax_enlist", {
        "display": "korax-dev-enactor-test",
        "grants": ["claimant:/korax-dev/**"],
    })
    body = out.structured_content
    assert body["rebound"] is True
    assert "token" not in body
    profile = Path(body["credential_profile"])
    assert profile.exists() and profile.parent == tmp_path / "profiles"

    # the request was authored by the new band, and so is the next post
    req = await board_tools.call_tool("korax_envelope", {"id": body["request"]})
    assert req.structured_content["author"] == body["id"]
    note = await board_tools.call_tool("korax_post", {
        "ns": "/commons/offtopic", "type": "NOTE", "grade": "n/a",
        "payload": "posting as my new self",
    })
    assert note.structured_content["author"] == body["id"]
