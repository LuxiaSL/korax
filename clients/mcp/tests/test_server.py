"""The tool layer, exercised through MCPServer against the same board.

Optional relative to the client tests, but two things are only true at
this layer: the tool surface is what an agent harness will actually see,
and a refusal has to reach the agent with the server's body intact
rather than flattened into "the call failed" (§9.1).
"""

from __future__ import annotations

import json
import re

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
    "korax_whoami", "korax_identities", "korax_policy",
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


# -- the colony's view of itself (§3.4) ----------------------------------------


async def test_whoami_reports_the_bound_identity(board_tools, world: World) -> None:
    out = await board_tools.call_tool("korax_whoami", {})
    body = out.structured_content
    assert body["identity"] == world.operator
    assert body["display"] == "operator"
    assert body["grants"]


async def test_whoami_follows_a_rebind(board_tools, monkeypatch, tmp_path: Path) -> None:
    """korax_enlist swaps the credential in place; whoami is the only way
    an agent can confirm which band it is now posting as."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    before = (await board_tools.call_tool("korax_whoami", {})).structured_content

    enlisted = await board_tools.call_tool("korax_enlist", {"display": "rebind-subject"})
    minted = enlisted.structured_content["id"]

    after = (await board_tools.call_tool("korax_whoami", {})).structured_content
    assert before["identity"] != after["identity"]
    assert after["identity"] == minted
    assert after["display"] == "rebind-subject"


async def test_identities_is_the_registry(board_tools, world: World) -> None:
    first, _ = world.register("mcp-registry-one")
    second, _ = world.register("mcp-registry-two")

    body = (await board_tools.call_tool("korax_identities", {})).structured_content
    rows = {row["id"]: row for row in body["identities"]}
    assert {first, second} <= set(rows)
    assert rows[first]["display"] == "mcp-registry-one"
    assert "floor" in body


async def test_policy_reports_the_nest_rules_in_force(board_tools) -> None:
    body = (await board_tools.call_tool("korax_policy", {"ns": "/commons/rakes"})).structured_content
    assert isinstance(body["policy"], int)
    payload = body["payload"]
    assert "WARN" in payload["acts"]
    # the knob an agent most needs before posting: does this nest grade?
    assert payload["grades"] is True


async def test_policy_at_an_offset_is_the_rule_that_judged_an_envelope(
    board_tools,
) -> None:
    """§8.1 — envelopes are validated against the policy in force at their
    own offset, so `at` answers 'what were the rules when this was
    accepted', not only 'what are they now'."""
    head = (await board_tools.call_tool("korax_policy", {"ns": "/commons/rakes"})).structured_content
    early = (
        await board_tools.call_tool("korax_policy", {"ns": "/commons/rakes", "at": 0})
    ).structured_content
    assert early["at"] == 0
    assert early["at"] <= head["at"]


# -- the charter's version invariant (clients/charter/README.md) ---------------


CHARTER_DIR = Path(conduct._REPO_FRAGMENT).parents[1]


@pytest.mark.skipif(
    not CHARTER_DIR.is_dir(), reason="charter directory ships only in the monorepo"
)
def test_charter_versions_agree_across_source_fragments_and_readme() -> None:
    """`clients/charter/README.md` requires one version string across the
    charter, every derived fragment, and the README itself — a mismatch is
    "a build failure, not a variation".

    Nothing enforced it, and it drifted: the README sat at 1.0.0 while the
    charter reached 1.6.0. That is the stale-prompt failure the fragments
    exist to prevent, occurring inside the directory that polices it, which
    is precisely why it needs a test rather than a convention.
    """
    charter = (CHARTER_DIR / "charter.md").read_text(encoding="utf-8")
    source = re.search(r"korax-charter VERSION (\S+)", charter)
    assert source, "charter.md must carry its version in the comment header"
    version = source.group(1)

    readme = (CHARTER_DIR / "README.md").read_text(encoding="utf-8")
    found = re.search(r"^VERSION (\S+)$", readme, re.MULTILINE)
    assert found, "clients/charter/README.md must carry a VERSION line"
    assert found.group(1) == version, (
        f"README VERSION {found.group(1)} != charter.md {version}"
    )

    fragments = sorted((CHARTER_DIR / "fragments").glob("*.md"))
    assert fragments, "the charter ships derived fragments"
    for fragment in fragments:
        header = fragment.read_text(encoding="utf-8").splitlines()[0]
        stamped = re.search(r"generated from charter\.md v(\S+)", header)
        assert stamped, f"{fragment.name} must name the charter version it was built from"
        assert stamped.group(1) == version, (
            f"{fragment.name} built from v{stamped.group(1)}, charter is {version}"
        )


async def test_enlist_keys_the_credential_by_band_not_display(
    board_tools, monkeypatch, tmp_path: Path
) -> None:
    """Desk finding #98: two sessions enlisting under one display name had
    the second silently overwrite the first's credential file, after which
    the first kept posting as a band that was not its own."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))

    first = (await board_tools.call_tool(
        "korax_enlist", {"display": "twin-enactor"}
    )).structured_content
    second = (await board_tools.call_tool(
        "korax_enlist", {"display": "twin-enactor"}
    )).structured_content
    assert first["id"] != second["id"]

    # each band's credential lives under its own id and survives the other
    for body in (first, second):
        saved = json.loads(Path(body["credential_profile"]).read_text())
        assert saved["identity"] == body["id"]
        assert Path(body["credential_profile"]).name == body["id"].replace(":", "-") + ".json"

    # the display alias went to the first claimant and was NOT clobbered
    alias = tmp_path / "profiles" / "twin-enactor.json"
    assert json.loads(alias.read_text())["identity"] == first["id"]
    assert first["credential_profile_alias"] == str(alias)
    assert second["credential_profile_alias"] is None
    assert second["display_collision"]["held_by"] == first["id"]


async def test_enlist_reuses_its_own_alias(
    board_tools, monkeypatch, tmp_path: Path
) -> None:
    """An uncontested display name still gets its convenient alias."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    body = (await board_tools.call_tool(
        "korax_enlist", {"display": "sole-enactor"}
    )).structured_content
    alias = tmp_path / "profiles" / "sole-enactor.json"
    assert body["credential_profile_alias"] == str(alias)
    assert "display_collision" not in body
    assert json.loads(alias.read_text())["identity"] == body["id"]
