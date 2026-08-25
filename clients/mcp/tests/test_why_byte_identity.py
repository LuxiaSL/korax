"""One answer, two clients, identical bytes — JOB #3765 acceptance 5.

`why` was implemented twice, so the two clients could drift and only a
reader holding both outputs would ever know. It is one reduction now,
and this is the test that says so.

**WHAT "BYTE-IDENTICAL" IS TESTED AS, stated because the desk fixed it
before delivery rather than after (#4007): the two DOCUMENTS are
serialised with one serialiser and compared as bytes — key order
included.** That is the claim the acceptance is making: two clients
render one answer indistinguishably. It is deliberately not a comparison
of raw stdout against a tool-result object, because the CLI applies
`indent=2` to every command it has ever had and the MCP returns a
structure for its harness to encode: that difference is presentation,
uniform across both clients' whole surfaces, and has nothing to do with
whether `why` answers the same thing twice. **Key order is not exempted
by that** — if the two ever produced differently-ordered documents this
fails, which is the half of #4007's ruling that does the work.
"""

from __future__ import annotations

import io
import json

import pytest

from korax_cli.cli import run as cli_run
from korax_mcp.client import KoraxClient
from korax_mcp.server import build_server

from conftest import World

pytestmark = pytest.mark.anyio

BOARD_URL = "http://board.invalid"


@pytest.fixture()
async def board_tools(world: World):
    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        yield build_server(client)
    finally:
        await client.aclose()


async def test_both_clients_render_one_answer_identically(
    board_tools, world: World
) -> None:
    import httpx

    subject = 1

    mcp_doc = (
        await board_tools.call_tool("korax_why", {"id": subject})
    ).structured_content

    out, err = io.StringIO(), io.StringIO()
    code = await cli_run(
        ["why", str(subject)],
        transport=httpx.ASGITransport(app=world.app),
        stdout=out,
        stderr=err,
        stdin=io.StringIO(""),
        env={"KORAX_URL": BOARD_URL, "KORAX_TOKEN": world.op_token},
    )
    assert code == 0, err.getvalue()
    cli_doc = json.loads(out.getvalue())

    mcp_bytes = json.dumps(mcp_doc, indent=2, default=str).encode()
    cli_bytes = json.dumps(cli_doc, indent=2, default=str).encode()

    assert mcp_bytes == cli_bytes, (
        "the two clients rendered different bytes for one answer:\n"
        f"  MCP keys: {list(mcp_doc)}\n  CLI keys: {list(cli_doc)}"
    )
    # Not vacuous: both must actually be the answer, not two empty dicts.
    assert cli_doc["view"] == "why"
    assert cli_doc["output"]["routes_declared"], "no routes — the comparison proved nothing"


async def test_neither_client_reshapes_the_reduction(board_tools, world: World) -> None:
    """The clients render; they compute nothing (property 1). If either
    started unwrapping `output` or dropping the §9.3 counters on its own
    schedule, the test above would still pass while the two drifted from
    the BOARD."""
    doc = (await board_tools.call_tool("korax_why", {"id": 1})).structured_content
    served = (
        await board_tools.call_tool(
            "korax_view", {"name": "why", "id": 1}
        )
    ).structured_content
    assert doc == served, (
        "`korax_why` no longer renders `/view/why` verbatim — a client that "
        "reshapes the reduction is the second implementation this JOB deleted"
    )
