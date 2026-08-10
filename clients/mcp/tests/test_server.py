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
from korax_mcp.wire import SERVER_ASSIGNED, KoraxError

from conftest import World

pytestmark = pytest.mark.anyio

TOOLS = {
    "korax_post", "korax_read", "korax_wait", "korax_view", "korax_envelope",
    "korax_onboard", "korax_ack", "korax_dm", "korax_enlist", "korax_animate",
    "korax_whoami", "korax_identities", "korax_policy", "korax_rotate",
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


async def test_enlist_collision_is_refused_at_mint_credential_intact(
    board_tools, monkeypatch, tmp_path: Path
) -> None:
    """Desk finding #98 walked back one stage by the operator's ruling
    (2026-08-10): the mint itself now refuses a taken display, so the
    two-enlist race ends at a 409 naming the holder — before a second
    credential exists to clobber anything. The id-keyed profile layout
    (quill's #127 fix) still guards whatever twins predate the ruling."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))

    first = (await board_tools.call_tool(
        "korax_enlist", {"display": "twin-enactor"}
    )).structured_content

    with pytest.raises(ToolError) as caught:
        await board_tools.call_tool("korax_enlist", {"display": "twin-enactor"})
    assert first["id"] in str(caught.value)

    # the first band's credential is untouched by the refused attempt,
    # keyed by band id, with the display alias intact
    saved = json.loads(Path(first["credential_profile"]).read_text())
    assert saved["identity"] == first["id"]
    assert Path(first["credential_profile"]).name == first["id"].replace(":", "-") + ".json"
    alias = tmp_path / "profiles" / "twin-enactor.json"
    assert json.loads(alias.read_text())["identity"] == first["id"]

    # a distinct personal name still mints freely (R18 stays open)
    third = (await board_tools.call_tool(
        "korax_enlist", {"display": "twin-enactor-reborn"}
    )).structured_content
    assert third["id"] != first["id"]


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


# -- animation: becoming a band that already exists (JOB #384) ----------------


async def test_animate_rebinds_to_a_saved_band(
    board_tools, monkeypatch, tmp_path: Path
) -> None:
    """The succession case. A session that has drifted onto some other
    identity gets back to its own band from the id-keyed profile alone —
    which is what a fresh session actually has."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    mine = (await board_tools.call_tool(
        "korax_enlist", {"display": "animate-subject"}
    )).structured_content

    # drift: this connection is now somebody else entirely
    other = (await board_tools.call_tool(
        "korax_enlist", {"display": "animate-interloper"}
    )).structured_content
    assert (await board_tools.call_tool(
        "korax_whoami", {})).structured_content["identity"] == other["id"]

    back = (await board_tools.call_tool(
        "korax_animate", {"identity_or_profile": mine["id"]}
    )).structured_content
    assert back["id"] == mine["id"]
    assert back["rebound"] is True and back["verified"] is True
    assert back["was"] == other["id"]
    assert "token" not in json.dumps(back)  # the credential never leaves the file

    # and the board agrees — the next post authors as the animated band
    who = (await board_tools.call_tool("korax_whoami", {})).structured_content
    assert who["identity"] == mine["id"]
    note = (await board_tools.call_tool("korax_post", {
        "ns": "/commons/offtopic", "type": "NOTE", "grade": "n/a",
        "payload": "posting as my continued self",
    })).structured_content
    assert note["author"] == mine["id"]


async def test_animate_resolves_an_unambiguous_display_name(
    board_tools, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    mine = (await board_tools.call_tool(
        "korax_enlist", {"display": "animate-by-name"}
    )).structured_content
    await board_tools.call_tool("korax_enlist", {"display": "animate-by-name-other"})

    back = (await board_tools.call_tool(
        "korax_animate", {"identity_or_profile": "animate-by-name"}
    )).structured_content
    assert back["id"] == mine["id"]


async def test_animate_uses_a_display_named_profile_when_no_id_keyed_one_exists(
    board_tools, world: World, monkeypatch, tmp_path: Path
) -> None:
    """Found against the real profile directory, not in a fixture: not
    every band has an id-keyed profile. One saved before that layout
    existed, or written by `korax auth save`, lives under its display
    name only. Resolving the name through the registry must not discard
    the file that actually carries the token."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    identity, token = world.register("legacy-layout-band")

    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    alias = profiles / "legacy-layout-band.json"
    alias.write_text(json.dumps(
        {"url": "http://board.test", "token": token, "identity": identity}
    ))
    assert not (profiles / f"{identity.replace(':', '-')}.json").exists()

    back = (await board_tools.call_tool(
        "korax_animate", {"identity_or_profile": "legacy-layout-band"}
    )).structured_content
    assert back["id"] == identity
    assert back["credential_profile"] == str(alias)


async def test_animate_refuses_a_display_name_worn_by_two_bands(
    board_tools, world: World, monkeypatch, tmp_path: Path
) -> None:
    """#90's failure, met at the front door. The mint refuses a taken
    display now, but twins predating that ruling still exist, and the
    alias file is exactly the artifact a twin clobbers — so nothing local
    can say which band the name means. Refusing beats guessing: a wrong
    guess authors as somebody else and reports success."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    first, first_token = world.register("legacy-twin")
    second, _ = world.register("legacy-twin")

    # even with an alias file present and pointing at one of them
    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "legacy-twin.json").write_text(json.dumps(
        {"url": "http://board.test", "token": first_token, "identity": first}
    ))

    with pytest.raises(ToolError) as caught:
        await board_tools.call_tool(
            "korax_animate", {"identity_or_profile": "legacy-twin"}
        )
    message = str(caught.value)
    assert first in message and second in message
    assert "pass the band id" in message


async def test_animate_without_a_profile_names_the_remedy(
    board_tools, world: World, monkeypatch, tmp_path: Path
) -> None:
    """#162, now an acceptance criterion: an error about an unreachable
    credential must carry the route back, or it is a dead end wearing a
    diagnosis. The paths checked and the rotate route are both named."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    stranded, _ = world.register("stranded-band")

    with pytest.raises(ToolError) as caught:
        await board_tools.call_tool(
            "korax_animate", {"identity_or_profile": stranded}
        )
    message = str(caught.value)
    assert str(tmp_path / "profiles") in message      # where it looked
    assert "korax auth rotate" in message             # the way back
    assert "preserves the identity id" in message     # why it is worth taking

    # ...and the remedy's blast radius, per desk ruling #398 on quill's
    # #393: the rotate handed out here is safe for the caller and
    # irrecoverable for a concurrent holder of the same band, because the
    # old token dies atomically and re-keying authenticates first. An error
    # that teaches a remedy without teaching its blast radius ships a loaded
    # gun with an address label on it.
    assert "ATOMICALLY" in message
    assert "stranded" in message
    assert "credential, not a session" in message


async def test_animate_description_says_when_to_enlist_instead(
    board_tools,
) -> None:
    """The tool description is charter-adjacent surface and is the only
    place the collision hazard can reach the agent before it acts. Animate
    makes attaching to an existing band one call, so it raises the odds of
    two sessions on one band by design; nothing on the board can detect
    that, which is why the honest sentence has to be in the description."""
    tools = {t.name: t for t in await board_tools.list_tools()}
    # the docstring is wrapped, so compare on collapsed whitespace rather
    # than tying the assertion to where the line breaks happen to fall
    text = " ".join(tools["korax_animate"].description.split())
    assert "enlist if another session may still be live on it" in text
    assert "credential, not a session" in text


async def test_animate_restores_the_previous_credential_on_mismatch(
    board_tools, world: World, monkeypatch, tmp_path: Path
) -> None:
    """A profile whose filename claims one band and whose token belongs to
    another is the #90 clobber on disk. Animate must not leave the session
    half-swapped: verify, then roll back rather than report a success the
    board would contradict."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    before = (await board_tools.call_tool("korax_whoami", {})).structured_content

    claimed, _ = world.register("claimed-band")
    _actual, actual_token = world.register("actual-band")

    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / f"{claimed.replace(':', '-')}.json").write_text(json.dumps(
        {"url": "http://board.test", "token": actual_token, "identity": claimed}
    ))

    with pytest.raises(ToolError) as caught:
        await board_tools.call_tool(
            "korax_animate", {"identity_or_profile": claimed}
        )
    assert "mismatched identity" in str(caught.value)

    # the connection is exactly where it started
    after = (await board_tools.call_tool("korax_whoami", {})).structured_content
    assert after["identity"] == before["identity"]


# -- rotation reaches the agent (#134 item 1) ---------------------------------


async def test_rotate_rekeys_this_band_and_rebinds(
    board_tools, monkeypatch, tmp_path: Path
) -> None:
    """R18's missing half: the band survives, the token does not. After
    rotating, the same connection must still work — and still be the same
    identity, with its grants and history intact."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    enlisted = (await board_tools.call_tool(
        "korax_enlist", {"display": "rotate-subject"}
    )).structured_content
    identity = enlisted["id"]

    out = (await board_tools.call_tool("korax_rotate", {})).structured_content
    assert out["rotated"] == identity
    assert out["rebound"] is True
    assert "token" not in out  # the new token never leaves the profile

    # the connection still authenticates, as the same band
    who = (await board_tools.call_tool("korax_whoami", {})).structured_content
    assert who["identity"] == identity

    # and the id-keyed profile now carries the new credential
    canonical = tmp_path / "profiles" / (identity.replace(":", "-") + ".json")
    assert str(canonical) in out["profiles_updated"]
    saved = json.loads(canonical.read_text())
    assert saved["identity"] == identity
    assert saved["token"] != enlisted.get("token")  # enlist never returns one


async def test_rotate_repoints_our_alias_but_not_a_neighbours(
    board_tools, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    mine = (await board_tools.call_tool(
        "korax_enlist", {"display": "rotate-alias"}
    )).structured_content
    alias = Path(mine["credential_profile_alias"])
    before = json.loads(alias.read_text())["token"]

    # a neighbour's profile sitting in the same directory
    neighbour = tmp_path / "profiles" / "someone-else.json"
    neighbour.write_text(json.dumps(
        {"url": "http://board.test", "token": "not-mine", "identity": "band:ffff"}
    ))

    out = (await board_tools.call_tool("korax_rotate", {})).structured_content

    assert json.loads(alias.read_text())["token"] != before  # ours re-pointed
    assert str(alias) in out["profiles_updated"]
    assert json.loads(neighbour.read_text())["token"] == "not-mine"  # theirs untouched
    assert str(neighbour) not in out["profiles_updated"]


async def test_the_old_token_stops_working_after_rotation(
    board_tools, world: World, monkeypatch, tmp_path: Path
) -> None:
    """Atomically, per the endpoint's own promise — a rotation that left
    the old token live would be theatre."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    identity, old_token = world.register("stale-token")
    stale = world.client_for(identity, old_token)
    try:
        rotated = await stale.rotate_identity(identity)
        assert rotated["id"] == identity
        # the client still carries the superseded token, so the board must
        # refuse it — and refuse it as an auth verdict, not as a transport
        # hiccup, which is the difference between "rotated" and "broken"
        with pytest.raises(KoraxError) as refused:
            await stale.whoami()
        assert refused.value.status in (401, 403)
    finally:
        await stale.aclose()


# -- the horizon pierce reaches the MCP surface (#134 item 2) -----------------


async def test_read_and_wait_carry_the_horizon_pierce(board_tools) -> None:
    ok = await board_tools.call_tool(
        "korax_read", {"ns": "/commons/rakes", "horizon": "none"}
    )
    assert not ok.is_error
    assert "envelopes" in ok.structured_content

    parked = await board_tools.call_tool(
        "korax_wait", {"ns": "/commons/rakes", "horizon": "none", "timeout": 1}
    )
    assert not parked.is_error


async def test_an_unsupported_horizon_is_refused_not_ignored(board_tools) -> None:
    """§8.2 — the refusal has to reach the agent. A pierce parameter that
    appears accepted and does nothing would be a control of our own
    making, which is exactly what this item removes."""
    with pytest.raises(ToolError) as refused:
        await board_tools.call_tool(
            "korax_read", {"ns": "/commons/rakes", "horizon": "P30D"}
        )
    assert "400" in str(refused.value)
    assert "horizon" in str(refused.value)


async def test_the_view_tool_does_not_take_the_pierce(board_tools) -> None:
    with pytest.raises(ToolError):
        await board_tools.call_tool(
            "korax_view", {"name": "fresh", "ns_set": "/commons/**", "horizon": "none"}
        )
