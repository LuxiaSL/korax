"""`<lane>_is` strings survive the MCP layer byte-for-byte — JOB #3774.

Brief property 5: clients pass the strings through untouched; no client
summarises one. That is a claim about a layer whose whole job is
reshaping, so it needs a test rather than a convention.

TWO SHAPES, NOT ONE. A dict-returning view carries a twin per key inside
`output`; a bare-list view carries `output_is` beside `output` in the
response envelope. Those are different emission paths on the server, so
a client can pass one through and drop the other — and the list path is
the fragile one, because it lives on the wrapper a client is most likely
to rebuild. Both are asserted here.

Byte-identical is checked against the SERVER'S OWN CONSTANT, imported,
never against a copy pasted into this file (#2595's rule, and the same
argument as `test_vocabulary_drift`): a copy tests that two strings in
this repo agree with each other, which is true the moment I write it and
stays true through the bug. The cross-tree guard (#2286/#2287) is what
makes the import legitimate — `korax` and `korax_mcp` always ship from
one checkout.
"""

from __future__ import annotations

import pytest

from korax.reductions import (
    DOCKET_ESCALATED_IS,
    DOCKET_UNGATED_IS,
    OF_RECORD_IS,
)

from korax_mcp.client import KoraxClient
from korax_mcp.server import build_server

from conftest import World

pytestmark = pytest.mark.anyio


@pytest.fixture()
async def board_tools(world: World):
    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        yield build_server(client)
    finally:
        await client.aclose()


async def test_dict_view_lane_strings_reach_the_agent_unmodified(
    board_tools,
) -> None:
    body = (
        await board_tools.call_tool("korax_view", {"name": "docket", "ns": "/korax-dev"})
    ).structured_content
    output = body["output"]

    assert output["escalated_is"] == DOCKET_ESCALATED_IS
    assert output["ungated_is"] == DOCKET_UNGATED_IS

    # Not merely present: not truncated, not re-wrapped, not summarised.
    # The MCP layer trims results elsewhere by design (#3428-era work), so
    # "it is there" and "it is whole" are genuinely different assertions.
    assert len(output["escalated_is"]) == len(DOCKET_ESCALATED_IS)
    assert "…" not in output["ungated_is"] and "..." not in output["ungated_is"]


async def test_list_view_output_is_survives_the_wrapper(board_tools) -> None:
    """The fragile half: `of-record` returns a bare list, so its string
    rides on the response envelope rather than inside the data. A client
    that rebuilds that envelope from named fields drops this silently and
    the view still looks correct."""
    body = (
        await board_tools.call_tool(
            "korax_view", {"name": "of-record", "project": "/korax-dev"}
        )
    ).structured_content

    assert "output_is" in body, (
        "`of-record` returns a bare list; its lane string rides beside "
        "`output` and the MCP layer dropped it"
    )
    assert body["output_is"] == OF_RECORD_IS
