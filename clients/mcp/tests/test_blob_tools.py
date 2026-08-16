"""`korax_attach` / `korax_fetch` — JOB #2325, artifact-store.md's B2
stage, MCP side. Sibling of `clients/cli/tests/test_blob_verbs.py`:
same behavior, independently exercised, no shared runtime code (the
`clients/mcp` boundary `test_backoff_contract.py` already enforces).
"""

from __future__ import annotations

import hashlib

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from korax import PROTO
from korax_mcp.server import build_server

ARTIFACTS_NS = "/korax-dev/artifacts"

pytestmark = pytest.mark.anyio


@pytest.fixture()
def govern_artifacts(world) -> None:
    """B1's activation step, done directly against the board (setup, not
    the thing under test)."""
    world.board.append(world.operator, {
        "proto": PROTO, "author": world.operator, "ns": ARTIFACTS_NS,
        "type": "POLICY", "grade": "n/a", "refs": [],
        "payload": {"acts": ["NOTE"], "grades": False,
                    "grants": [{"identity": "band:*", "band": "poster"}]},
        "ext": {},
    })


@pytest.fixture()
async def board_tools(world, govern_artifacts):
    client = world.client_for(world.operator, world.op_token)
    try:
        yield build_server(client)
    finally:
        await client.aclose()


async def test_attach_then_fetch_round_trips_the_exact_bytes(
    tmp_path, board_tools
) -> None:
    src = tmp_path / "evidence.txt"
    src.write_bytes(b"genuine gate evidence, not a fixture pretending to be one")

    up = await board_tools.call_tool("korax_attach", {
        "path": str(src), "caption": "a fixture blob", "media_type": "text/plain",
    })
    assert not up.is_error, up
    assert up.structured_content["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert up.structured_content["bytes"] == src.stat().st_size
    assert isinstance(up.structured_content["anchor"], int)

    dst = tmp_path / "out" / "fetched.txt"
    dst.parent.mkdir()
    down = await board_tools.call_tool("korax_fetch", {
        "sha256": up.structured_content["sha256"], "out_path": str(dst),
    })
    assert not down.is_error, down
    assert down.structured_content["path"] == str(dst)
    assert dst.read_bytes() == src.read_bytes()
    assert down.structured_content["media_type"].startswith("text/plain")


async def test_the_caption_lands_on_the_anchor_envelope(
    tmp_path, board_tools
) -> None:
    src = tmp_path / "f.bin"
    src.write_bytes(b"\x00\x01\x02anchored")

    up = await board_tools.call_tool("korax_attach", {
        "path": str(src), "caption": "measured at deadbeef",
    })
    assert not up.is_error, up

    anchor = await board_tools.call_tool(
        "korax_envelope", {"id": up.structured_content["anchor"]}
    )
    assert not anchor.is_error, anchor
    assert anchor.structured_content["ns"] == ARTIFACTS_NS
    assert anchor.structured_content["type"] == "NOTE"
    assert anchor.structured_content["payload"] == "measured at deadbeef"
    assert anchor.structured_content["pointer"]["sha256"] == up.structured_content["sha256"]


async def test_attach_of_a_missing_file_raises_a_tool_error(
    tmp_path, board_tools
) -> None:
    missing = tmp_path / "does-not-exist.txt"
    with pytest.raises(ToolError):
        await board_tools.call_tool(
            "korax_attach", {"path": str(missing), "caption": "c"}
        )


async def test_fetch_of_an_unknown_sha_surfaces_the_servers_404(
    board_tools,
) -> None:
    with pytest.raises(ToolError) as caught:
        await board_tools.call_tool(
            "korax_fetch", {"sha256": "f" * 64, "out_path": "/tmp/should-not-be-written.bin"}
        )
    assert "404" in str(caught.value)


async def test_a_second_upload_of_known_bytes_gets_its_own_anchor(
    tmp_path, board_tools, world
) -> None:
    """#1948 clause 1, exercised through the tool surface: attribution
    holds even when the caller is the same connection twice."""
    body = b"shared across two attach calls"
    a = tmp_path / "a.bin"
    a.write_bytes(body)
    b = tmp_path / "b.bin"
    b.write_bytes(body)

    first = await board_tools.call_tool(
        "korax_attach", {"path": str(a), "caption": "first upload"}
    )
    second = await board_tools.call_tool(
        "korax_attach", {"path": str(b), "caption": "second upload"}
    )
    assert first.structured_content["sha256"] == second.structured_content["sha256"]
    assert first.structured_content["anchor"] != second.structured_content["anchor"]
