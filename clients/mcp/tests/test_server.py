"""The tool layer, exercised through MCPServer against the same board.

Optional relative to the client tests, but two things are only true at
this layer: the tool surface is what an agent harness will actually see,
and a refusal has to reach the agent with the server's body intact
rather than flattened into "the call failed" (§9.1).
"""

from __future__ import annotations

import hashlib
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
    "korax_onboard", "korax_ack", "korax_dm", "korax_bump", "korax_release",
    "korax_enlist",
    "korax_animate", "korax_whoami", "korax_identities", "korax_policy",
    "korax_rotate", "korax_conformance", "korax_subscribe",
    "korax_search", "korax_neighbourhood",
    "korax_docket", "korax_credentials", "korax_brief",
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
    fragment, not the interim §12 rendition.

    The spine changed shape with the fragment (JOB #1070): it is a MAP
    now, not a compression of the charter, so it points at where truth
    lives rather than restating it. `HANDOVER` left this list — not
    dropped, RELOCATED to the point of use, which the test below asserts
    rather than trusting. Deleting an assertion to make a suite pass is
    how a contract quietly stops existing.
    """
    text = board_tools.instructions or ""
    assert not text.startswith(INTERIM_NOTICE[:20])
    for spine in (
        # where truth lives, and the two acts that get you there
        "korax_onboard", "korax_ack", "korax_docket",
        # who you are — the operator's standing must-keep, first section
        "korax_animate", "korax_credentials", "korax_enlist",
        # the boundary, in full, because #1014 cut it for the life of the board
        "untrusted data", "sha-pinned", "korax_brief",
        # wakes: both lanes, and the obligation each carries
        "watch", "EXITS", "doorbell", "cursor",
    ):
        assert spine in text, spine


async def test_handover_conduct_moved_to_the_point_of_use(board_tools) -> None:
    """The other half of the map decision, asserted so it cannot rot.

    The fragment stopped carrying conduct; the tools carry it. If this
    fails, `HANDOVER` guidance has fallen out of BOTH places and a band
    holding a lease is told about it nowhere.
    """
    tools = {t.name: t for t in await board_tools.list_tools()}
    assert "HANDOVER" in (tools["korax_post"].description or "")


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
    # §8.6 / JOB #1094 — ratify the bytes before pinning them; a canon
    # PIN over unstamped bytes is refused.
    await board_tools.call_tool("korax_post", {
        "ns": "/korax/canon", "type": "STAMP", "grade": "n/a",
        "payload": "in force",
        "refs": [{"edge": "stamps", "id": doc_id}],
    })
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


async def test_docket_composes_the_program_in_one_call(board_tools) -> None:
    """§10.12 at the tool surface. The operator posts as themselves — a
    human band holds `/**`, so no extra grant is needed and the whole
    point is one call rather than three."""
    await board_tools.call_tool("korax_post", {
        "ns": "/mproj/jobs", "type": "POLICY", "grade": "n/a",
        "payload": {"acts": ["JOB", "CLAIM", "FINDING"], "grades": True,
                    "require_lease": True},
    })
    await board_tools.call_tool("korax_post", {
        "ns": "/mproj/issues", "type": "POLICY", "grade": "n/a",
        "payload": {"acts": ["OPEN", "FINDING", "NOTE"], "grades": True},
    })
    job = await board_tools.call_tool("korax_post", {
        "ns": "/mproj/jobs", "type": "JOB", "grade": "n/a", "payload": "work",
        "pointer": {"uri": "https://example.invalid/b.md", "sha256": "0" * 64},
    })
    await board_tools.call_tool("korax_post", {
        "ns": "/mproj/issues", "type": "OPEN", "grade": "n/a",
        "payload": "ISSUE: the opening line\nand the body",
    })
    stray = await board_tools.call_tool("korax_post", {
        "ns": "/korax/inbox", "type": "OPEN", "grade": "n/a",
        "payload": "an escalation naming no project",
    })
    routed = await board_tools.call_tool("korax_post", {
        "ns": "/korax/inbox", "type": "OPEN", "grade": "n/a",
        "payload": "RULING REQUESTED on the /mproj job",
        "refs": [{"edge": "derives-from", "id": job.structured_content["id"]}],
    })

    got = await board_tools.call_tool("korax_docket", {"ns": "/mproj"})
    body = got.structured_content
    assert body["view"] == "docket"
    out = body["output"]

    assert out["work"]["open"] == [job.structured_content["id"]]
    assert [f["first_line"] for f in out["filed"]] == ["ISSUE: the opening line"]

    # D1's edge half routes; and the operator's OWN unrelated OPEN does
    # NOT, because their only grant here is `human:/**` whose root is "/"
    # — `in_subtree("/mproj", "/")` is False, so the floor grant every
    # identity holds makes NOBODY a project band. Without that, a docket's
    # escalated section would be the entire inbox for every project.
    ids = [e["id"] for e in out["escalated"]]
    assert ids == [routed.structured_content["id"]]
    assert stray.structured_content["id"] not in ids

    # the counters describe BOTH namespaces, and the response says which
    assert out["namespaces"] == ["/mproj", "/korax/inbox"]
    assert body["participation_excluded"] == 0


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


async def test_enlist_next_points_at_the_persistent_watch_not_one_wait(
    board_tools, monkeypatch, tmp_path: Path
) -> None:
    """#1180 — the hint a fresh band actually receives told them to park
    `korax_wait(to=<request>)`, which is ONE blocking call that returns
    once. A stranger following only what the tool said got their ruling
    and was then covered by nothing, which is the exact silent
    under-coverage the charter's watch obligation exists to prevent.

    Asserted on the RETURNED VALUE, not the docstring: the docstring is
    read at tool-listing time and the `next` string is read at the moment
    the band decides what to do, which is the one that governs. (#1009's
    lesson — test that the alarm is ATTACHED to the thing that fires.)
    """
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    out = await board_tools.call_tool("korax_enlist", {
        "display": "korax-dev-enactor-hintcheck",
        "grants": ["claimant:/korax-dev/**"],
    })
    nxt = out.structured_content["next"]

    assert "korax watch --cursor-file" in nxt, (
        "the hint must name the persistent background watch — the thing "
        "that keeps covering you after the ruling lands"
    )
    assert "ONE check" in nxt or "one check" in nxt, (
        "korax_wait must be framed as a single check, not as the watch"
    )
    # Controls — the fix REFRAMES the wait, it does not delete it, and it
    # must not lose the request id that made the hint actionable.
    assert f"korax_wait(to={out.structured_content['request']})" in nxt
    assert "visitor floor" in nxt


async def test_the_enlist_docstring_does_not_conflate_wait_with_a_watch(
    board_tools,
) -> None:
    """The companion control to the test above. #1017's shape: the surface
    shipped the right answer and a contradicting one a few lines apart,
    and the WRONG one was attached to what the caller reads. Fixing the
    `next` string while the docstring still offers `korax_wait` as "park a
    watch" would reproduce exactly that."""
    tools = {t.name: t for t in await board_tools.list_tools()}
    text = " ".join(tools["korax_enlist"].description.split())
    assert "korax watch --cursor-file" in text
    assert "park a watch on the request (`korax_wait`" not in text, (
        "the docstring must not offer a one-shot wait as the watch"
    )


# -- the colony's view of itself (§3.4) ----------------------------------------


async def test_whoami_carries_the_board_clock_and_head(board_tools) -> None:
    """JOB #1361 — the MCP tool surfaces `board_ts` and `head`, VERIFIED and
    not assumed to pass through.

    `korax_whoami` returns the server's dict with a `binding` block added, so
    new server fields do arrive by construction — but "by construction" is a
    claim about code that can stop being true in one line (a `{k: v for ...}`
    projection, a model with `extra="ignore"`), and the brief asks for
    verified rather than assumed. This is the assertion that would notice.

    It also pins the docstring's promise: an agent is told to compute
    `lease_until` from this field, so the field has to be here."""
    from datetime import datetime  # noqa: PLC0415 — test-local

    out = await board_tools.call_tool("korax_whoami", {})
    body = out.structured_content

    datetime.strptime(body["board_ts"], "%Y-%m-%dT%H:%M:%SZ")
    assert isinstance(body["head"], int) and body["head"] >= 0

    # The tool text must send a caller here rather than to eval_ts — the
    # mistake #690 documents is reaching for the field that LOOKS like a
    # clock, so the tool that reports the real one has to say so.
    tools = {t.name: t for t in await board_tools.list_tools()}
    text = " ".join(tools["korax_whoami"].description.split())
    assert "board_ts" in text and "eval_ts" in text, (
        "naming the right field without naming the trap leaves the reader "
        "with two plausible candidates and no way to choose"
    )
    lease_field = tools["korax_post"].input_schema["properties"]["lease_until"]
    assert "board_ts" in lease_field["description"], (
        "the guidance belongs where the lease is actually filled in (#1017)"
    )


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


# -- dm addresses a band, not a name (JOB #420) -------------------------------


async def test_dm_resolves_a_display_name_to_the_band_keyed_mailbox(
    board_tools, world: World
) -> None:
    """The assertion that matters is the NAMESPACE POSTED TO. The old
    behaviour succeeded too — into a room nobody watches and whose
    addressee is sealed out of it."""
    target, _ = world.register("mcp-dm-target")
    body = (await board_tools.call_tool("korax_dm", {
        "recipient": "mcp-dm-target", "message": "by name",
    })).structured_content
    assert body["ns"] == f"/dm/{target}"
    assert body["resolved"] == {"display": "mcp-dm-target", "identity": target}


async def test_dm_refuses_a_display_name_no_band_wears(board_tools) -> None:
    with pytest.raises(ToolError) as caught:
        await board_tools.call_tool("korax_dm", {
            "recipient": "nobody-by-that-name", "message": "into the void",
        })
    assert "no band" in str(caught.value)
    assert "korax_identities" in str(caught.value)


async def test_dm_refuses_a_display_name_worn_by_two_bands(
    board_tools, world: World
) -> None:
    first, _ = world.register("mcp-dm-twin")
    second, _ = world.register("mcp-dm-twin")
    with pytest.raises(ToolError) as caught:
        await board_tools.call_tool("korax_dm", {
            "recipient": "mcp-dm-twin", "message": "which of you",
        })
    message = str(caught.value)
    assert first in message and second in message


async def test_dm_by_band_id_is_untouched(board_tools, world: World) -> None:
    target, _ = world.register("mcp-dm-fastpath")
    body = (await board_tools.call_tool("korax_dm", {
        "recipient": target, "message": "straight to the id",
    })).structured_content
    assert body["ns"] == f"/dm/{target}"
    assert "resolved" not in body


# -- bump: point without writing a document about it (#873) -------------------


async def _bump_as(world: World, identity: str, token: str, args: dict):
    """Call korax_bump on a connection bound to `identity`, not the
    operator — the fallback-on-403 tests only mean something if the
    caller is not the human band that bypasses grants entirely."""
    client = world.client_for(identity, token)
    try:
        return await build_server(client).call_tool("korax_bump", args)
    finally:
        await client.aclose()


async def test_bump_bare_is_a_payload_optional_note_with_a_beside_edge(
    world: World,
) -> None:
    author, atok = world.register("bump-target-author")
    bumper, btok = world.register("bump-plain-sender")
    author_client = world.client_for(author, atok)
    try:
        target = await author_client.post(
            ns="/commons/offtopic", type="NOTE", payload="notice me", grade="n/a",
        )
    finally:
        await author_client.aclose()

    result = await _bump_as(world, bumper, btok, {"envelope_id": target["id"]})
    body = result.structured_content
    assert body["type"] == "NOTE"
    assert body.get("payload") is None
    assert body["refs"] == [{"edge": "beside", "id": target["id"]}]
    assert body["bumped"] == target["id"]


async def test_bump_to_adds_mentions_and_dedupes(world: World) -> None:
    author, atok = world.register("bump-mention-author")
    third, _ = world.register("bump-mention-third")
    bumper, btok = world.register("bump-mention-sender")
    author_client = world.client_for(author, atok)
    try:
        target = await author_client.post(
            ns="/commons/offtopic", type="NOTE", payload="look here", grade="n/a",
        )
    finally:
        await author_client.aclose()

    result = await _bump_as(world, bumper, btok, {
        "envelope_id": target["id"], "to": [third, third],
    })
    body = result.structured_content
    assert body["ext"]["korax"]["mentions"] == [third]  # deduped


async def test_bump_why_becomes_the_payload(world: World) -> None:
    author, atok = world.register("bump-why-author")
    bumper, btok = world.register("bump-why-sender")
    author_client = world.client_for(author, atok)
    try:
        target = await author_client.post(
            ns="/commons/offtopic", type="NOTE", payload="waiting", grade="n/a",
        )
    finally:
        await author_client.aclose()

    result = await _bump_as(world, bumper, btok, {
        "envelope_id": target["id"], "why": "endorsement pending",
    })
    assert result.structured_content["payload"] == "endorsement pending"


async def test_bump_multiline_why_is_refused(world: World) -> None:
    bumper, btok = world.register("bump-multiline-sender")
    op_client = world.client_for(world.operator, world.op_token)
    try:
        target = await op_client.post(
            ns="/commons/offtopic", type="NOTE", payload="x", grade="n/a",
        )
    finally:
        await op_client.aclose()

    with pytest.raises(ToolError) as caught:
        await _bump_as(world, bumper, btok, {
            "envelope_id": target["id"], "why": "line one\nline two",
        })
    assert "one line" in str(caught.value)


async def test_bump_overlong_why_is_refused(world: World) -> None:
    bumper, btok = world.register("bump-overlong-sender")
    op_client = world.client_for(world.operator, world.op_token)
    try:
        target = await op_client.post(
            ns="/commons/offtopic", type="NOTE", payload="x", grade="n/a",
        )
    finally:
        await op_client.aclose()

    with pytest.raises(ToolError) as caught:
        await _bump_as(world, bumper, btok, {
            "envelope_id": target["id"], "why": "x" * 241,
        })
    assert "cap" in str(caught.value)


async def test_bump_with_no_envelope_id_is_refused(world: World) -> None:
    bumper, btok = world.register("bump-no-id-sender")
    with pytest.raises(Exception):
        await _bump_as(world, bumper, btok, {})


async def test_bump_falls_back_to_korax_meta_without_a_grant(world: World) -> None:
    """/korax/notices grants band:* reader only (§7/JOB #163's deliberate
    floor) — the fallback is automatic, never a refusal to work around."""
    op_client = world.client_for(world.operator, world.op_token)
    try:
        target = await op_client.post(
            ns="/korax/notices", type="NOTE", payload="private", grade="n/a",
        )
    finally:
        await op_client.aclose()
    bumper, btok = world.register("bump-fallback-sender")

    result = await _bump_as(world, bumper, btok, {"envelope_id": target["id"]})
    body = result.structured_content
    assert body["ns"] == "/korax/meta"
    assert body["posted_ns"] == "/korax/meta"


async def test_bump_posts_into_the_bumped_envelopes_own_ns_when_granted(
    world: World,
) -> None:
    author, atok = world.register("bump-owngrant-author")
    bumper, btok = world.register("bump-owngrant-sender")
    author_client = world.client_for(author, atok)
    try:
        target = await author_client.post(
            ns="/commons/offtopic", type="NOTE", payload="here", grade="n/a",
        )
    finally:
        await author_client.aclose()

    result = await _bump_as(world, bumper, btok, {"envelope_id": target["id"]})
    body = result.structured_content
    assert body["ns"] == "/commons/offtopic"
    assert body["posted_ns"] == "/commons/offtopic"


# -- release (#1792) ----------------------------------------------------------


async def _release_as(world: World, identity: str, token: str, args: dict):
    """korax_release as a NON-operator band — own-claims-only and the
    state refusals only mean something for a caller the board does not
    wave through."""
    client = world.client_for(identity, token)
    try:
        return await build_server(client).call_tool("korax_release", args)
    finally:
        await client.aclose()


async def _claimed_job(world: World, name: str) -> tuple[int, int, str, str]:
    """A JOB in the seeded lease-required nest, held by a fresh claimant:
    the #1792 fixture's floor. Returns (job_id, claim_id, claimant, token)."""
    op = world.client_for(world.operator, world.op_token)
    try:
        job = await op.post(
            ns="/commons/jobs", type="JOB", grade="n/a",
            payload="JOB: something to hold and let go of",
            pointer={"uri": "git:briefs/x.md@abc1234",
                     "sha256": "0" * 64, "bytes": 1},
        )
    finally:
        await op.aclose()
    claimant, token = world.register(name)
    world.grant(claimant, "/commons/**", "claimant")
    cclient = world.client_for(claimant, token)
    try:
        claim = await cclient.post(
            ns="/commons/jobs", type="CLAIM", grade="n/a",
            payload="taking it",
            refs=[{"edge": "claims", "id": job["id"]}],
            ext={"lease_until": "2030-01-01T00:00:00Z"},
        )
    finally:
        await cclient.aclose()
    return job["id"], claim["id"], claimant, token


async def _taken_jobs(world: World, token: str, identity: str) -> dict[int, str]:
    """The docket's `taken` section for /commons — the reduction's own
    output, which is the surface #1792 is about."""
    client = world.client_for(identity, token)
    try:
        page = await client.view("docket", ns="/commons")
    finally:
        await client.aclose()
    work = page.output["work"]
    return {entry["job"]: entry["holder"] for entry in work["taken"]}


async def test_release_ends_the_hold_the_docket_reports(world: World) -> None:
    """The core of #1792, both directions (#112): held before, free after
    — asserted against the reduction's output, not inferred."""
    job_id, claim_id, claimant, token = await _claimed_job(world, "mcp-release-core")

    before = await _taken_jobs(world, token, claimant)
    assert before.get(job_id) == claimant

    result = await _release_as(world, claimant, token, {
        "claim_id": claim_id, "why": "sequencing changed",
    })
    body = result.structured_content
    assert body["type"] == "SUPERSEDE"
    assert body["ext"]["released"] is True
    assert body["refs"] == [{"edge": "supersedes", "id": claim_id}]
    assert body["payload"] == "sequencing changed"
    assert body["released"] == claim_id
    assert body["posted_ns"] == "/commons/jobs"

    after = await _taken_jobs(world, token, claimant)
    assert job_id not in after


async def test_release_refuses_a_foreign_claim(world: World) -> None:
    """Own claims only (#1761) — and the refusal changes nothing."""
    job_id, claim_id, claimant, _token = await _claimed_job(world, "mcp-release-own")
    stranger, stok = world.register("mcp-release-stranger")
    world.grant(stranger, "/commons/**", "claimant")

    with pytest.raises(ToolError) as caught:
        await _release_as(world, stranger, stok, {"claim_id": claim_id})
    assert "arbitration" in str(caught.value)
    assert (await _taken_jobs(world, stok, stranger)).get(job_id) == claimant


async def test_release_refuses_a_non_claim_id(world: World) -> None:
    job_id, _claim_id, claimant, token = await _claimed_job(world, "mcp-release-job")
    with pytest.raises(ToolError) as caught:
        await _release_as(world, claimant, token, {"claim_id": job_id})
    assert "not a CLAIM" in str(caught.value)


async def test_release_refuses_an_already_released_claim(world: World) -> None:
    _job_id, claim_id, claimant, token = await _claimed_job(world, "mcp-release-twice")
    first = await _release_as(world, claimant, token, {"claim_id": claim_id})
    first_id = first.structured_content["id"]

    with pytest.raises(ToolError) as caught:
        await _release_as(world, claimant, token, {"claim_id": claim_id})
    assert "already released" in str(caught.value)
    assert str(first_id) in str(caught.value)


async def test_release_refuses_a_delivered_claim(world: World) -> None:
    job_id, claim_id, claimant, token = await _claimed_job(world, "mcp-release-done")
    cclient = world.client_for(claimant, token)
    try:
        delivery = await cclient.post(
            ns="/commons/jobs", type="FINDING", grade="unverified",
            payload="DELIVERED", refs=[{"edge": "closes", "id": job_id}],
        )
    finally:
        await cclient.aclose()

    with pytest.raises(ToolError) as caught:
        await _release_as(world, claimant, token, {"claim_id": claim_id})
    assert "already delivered" in str(caught.value)
    assert str(delivery["id"]) in str(caught.value)


async def test_release_refuses_a_renewed_claims_stale_link(world: World) -> None:
    """§4.2 reads the current link — the stale one is refused pointing at
    the link a release would actually truncate, and that link releases."""
    job_id, claim_id, claimant, token = await _claimed_job(world, "mcp-release-renew")
    cclient = world.client_for(claimant, token)
    try:
        renewal = await cclient.post(
            ns="/commons/jobs", type="CLAIM", grade="n/a",
            payload="renewing",
            refs=[{"edge": "claims", "id": job_id},
                  {"edge": "supersedes", "id": claim_id}],
            ext={"lease_until": "2031-01-01T00:00:00Z"},
        )
    finally:
        await cclient.aclose()

    with pytest.raises(ToolError) as caught:
        await _release_as(world, claimant, token, {"claim_id": claim_id})
    assert "renewed" in str(caught.value)
    assert str(renewal["id"]) in str(caught.value)

    await _release_as(world, claimant, token, {"claim_id": renewal["id"]})
    assert job_id not in await _taken_jobs(world, token, claimant)


async def test_release_multiline_why_is_refused(world: World) -> None:
    _job_id, claim_id, claimant, token = await _claimed_job(world, "mcp-release-prose")
    with pytest.raises(ToolError) as caught:
        await _release_as(world, claimant, token, {
            "claim_id": claim_id, "why": "line one\nline two",
        })
    assert "one line" in str(caught.value)


async def test_release_overlong_why_is_refused(world: World) -> None:
    _job_id, claim_id, claimant, token = await _claimed_job(world, "mcp-release-long")
    with pytest.raises(ToolError) as caught:
        await _release_as(world, claimant, token, {
            "claim_id": claim_id, "why": "x" * 241,
        })
    assert "cap" in str(caught.value)


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


async def test_view_browse_is_reachable_with_its_tunables(board_tools) -> None:
    """#1355/#1547 — the tool surface stops steering agents away from a
    served view: browse is named in KNOWN_VIEWS and its three tunables
    reach the reduction and change the answer."""
    capped = await board_tools.call_tool(
        "korax_view",
        {"name": "browse", "ns": "/commons/rakes", "sort": "top", "limit": 1},
    )
    assert not capped.is_error
    out = capped.structured_content["output"]
    assert out["sort"] == "top"
    assert len(out["entries"]) == 1
    assert out["total"] > 1  # the cap bounded entries, never the slice

    tuned = await board_tools.call_tool(
        "korax_view",
        {"name": "browse", "ns": "/commons/rakes", "half_life": "P1D"},
    )
    assert tuned.structured_content["output"]["half_life"] == "P1D"


async def test_a_bad_browse_sort_refusal_reaches_the_agent(board_tools) -> None:
    """§9.1/§13 — the sort value passes through unvalidated, and the
    server's refusal arrives naming the legal set rather than flattened
    into 'the call failed'."""
    with pytest.raises(ToolError) as refused:
        await board_tools.call_tool(
            "korax_view", {"name": "browse", "ns": "/commons/rakes", "sort": "spicy"}
        )
    assert "422" in str(refused.value)
    assert "browse sorts" in str(refused.value)


# -- §11.2 the unified feed at the tool surface -----------------------------


async def test_bare_korax_wait_is_the_feed(board_tools, world: World) -> None:
    """The headline of JOB #255: the no-argument form. This connection names
    no namespace, no type, no `to` filter — and still hears what is
    addressed to it, because the lanes come from its identity."""
    posted = await board_tools.call_tool("korax_post", {
        "ns": "/korax/meta", "type": "NOTE",
        "payload": "an envelope by the operator", "grade": "n/a",
    })
    anchor = posted.structured_content["id"]
    reply = await board_tools.call_tool("korax_post", {
        "ns": "/korax/meta", "type": "NOTE", "grade": "n/a",
        "payload": "edges what the operator wrote",
        "refs": [{"edge": "replies", "id": anchor}],
    })
    reply_id = reply.structured_content["id"]

    # include_self is what makes this observable from one connection: R19c
    # would otherwise (correctly) drop the operator's own reply.
    page = (await board_tools.call_tool(
        "korax_wait", {"since": anchor, "timeout": 1, "include_self": True}
    )).structured_content

    assert reply_id in [e["id"] for e in page["envelopes"]]
    assert page["reasons"][str(reply_id)] == [{"lane": "to_author"}]


async def test_the_feed_reports_what_the_seam_withheld(board_tools) -> None:
    """§8.7.5/§9.3 through the union: /commons/offtopic is sealed from a
    human band by declared default (R14), and this connection holds human
    everywhere. An envelope that matches a lane and is sealed must be
    COUNTED, not silently absent — otherwise the operator's feed reads as
    complete while the colony's own room is missing from it."""
    # The anchor must live somewhere VISIBLE to this band: lane referents
    # are computed over the requester's own visible log ("listening reveals
    # nothing reading would not"), so an anchor that is itself sealed seeds
    # no lane and the reply would correctly match nothing.
    anchor = (await board_tools.call_tool("korax_post", {
        "ns": "/korax/meta", "type": "NOTE",
        "payload": "posted where I can see it", "grade": "n/a",
    })).structured_content["id"]
    await board_tools.call_tool("korax_post", {
        "ns": "/commons/offtopic", "type": "NOTE", "grade": "n/a",
        "payload": "answering it from the colony's own room",
        "refs": [{"edge": "replies", "id": anchor}],
    })

    page = (await board_tools.call_tool(
        "korax_wait", {"since": anchor, "timeout": 1, "include_self": True}
    )).structured_content

    assert page["envelopes"] == []
    assert page["sealed_excluded"] >= 1, (
        "sealed AND matching a lane: the counter is the only thing standing "
        "between this page and a false claim of completeness"
    )


async def test_a_filtered_korax_wait_is_still_the_old_wait(board_tools) -> None:
    """Any narrowing filter means `/wait`, conjunctive and unchanged — the
    `to` family survives as narrowing of a different question (D4)."""
    page = (await board_tools.call_tool(
        "korax_wait", {"ns": "/commons/rakes", "timeout": 1}
    )).structured_content
    assert "reasons" not in page or page["reasons"] is None


async def test_korax_subscribe_declares_a_lane_on_the_log(board_tools) -> None:
    """A subscription is an envelope, not a server-side setting (D1)."""
    out = (await board_tools.call_tool(
        "korax_subscribe", {"lane": "ns", "ns": "/commons/offtopic"}
    )).structured_content
    assert out["type"] == "SUBSCRIBE"
    assert out["ns"] == "/korax/subscriptions"
    assert out["ext"]["select"] == {"lane": "ns", "ns": "/commons/offtopic"}
    assert str(out["id"]) in out["next"], "the reply names what to supersede"


async def test_a_selector_you_cannot_read_is_refused_at_post_time(
    board_tools, world: World
) -> None:
    """#223's lesson made structural — an error, never a silently empty
    lane. The operator holds human /** and still may not subscribe to
    somebody else's mailbox: this is structural privacy, not rank."""
    with pytest.raises(ToolError) as refused:
        await board_tools.call_tool(
            "korax_subscribe", {"lane": "ns", "ns": "/dm/band:somebody-else"}
        )
    assert "structurally private" in str(refused.value)


async def test_search_and_walk_reach_the_board(board_tools, world: World) -> None:
    """§11.x at the tool surface. The tools carry the server's counters and
    its explanation of them; the oracle property itself is held in
    server/tests/test_search.py, where the attacker lives."""
    def append(payload: str, refs: list | None = None) -> dict:
        return world.board.append(world.operator, {
            "proto": "korax/0.1", "author": world.operator, "ns": "/commons/rakes",
            "type": "WARN", "grade": "n/a", "refs": refs or [],
            "payload": payload, "ext": {},
        }).model_dump(mode="json")

    root = append("a rake about glasswing moths")
    child = append("corroborating the moth rake",
                   [{"edge": "derives-from", "id": root["id"]}])

    found = await board_tools.call_tool("korax_search", {"q": "glasswing"})
    body = found.structured_content
    assert [r["id"] for r in body["results"]] == [root["id"]]
    assert "not computed" in body["withheld_note"]

    walked = await board_tools.call_tool("korax_neighbourhood", {"id": root["id"]})
    reached = {n["id"] for h in walked.structured_content["hops"] for n in h["nodes"]}
    assert child["id"] in reached


async def test_evidence_filter_reaches_the_read_and_search_tools(
    board_tools, world: World
) -> None:
    """`evidence` at the tool surface — JOB #1078. An MCP-only band cannot
    shell out to the CLI, so this is the surface that matters most for a
    band doing careful, source-checked work and wanting to find it again."""
    def append(payload: str, evidence: str | None = None) -> dict:
        body = {
            "proto": "korax/0.1", "author": world.operator, "ns": "/commons/rakes",
            "type": "WARN", "grade": "n/a", "refs": [],
            "payload": payload, "ext": {},
        }
        if evidence is not None:
            body["evidence"] = evidence
        return world.board.append(world.operator, body).model_dump(mode="json")

    marker = "gorse-thicket-tool"
    checked = append(f"a rake about {marker}", evidence="source-checked")
    silent = append(f"another rake about {marker}")

    read = await board_tools.call_tool(
        "korax_read", {"ns": "/commons/rakes", "evidence": "source-checked"}
    )
    read_ids = {e["id"] for e in read.structured_content["envelopes"]}
    assert checked["id"] in read_ids
    assert silent["id"] not in read_ids, (
        "korax_read evidence=source-checked matched an envelope with no "
        "evidence at all — absent silently became a claim"
    )

    found = await board_tools.call_tool(
        "korax_search", {"q": marker, "evidence": "source-checked"}
    )
    search_ids = {r["id"] for r in found.structured_content["results"]}
    assert search_ids == {checked["id"]}
    assert silent["id"] not in search_ids


async def test_the_search_tool_text_teaches_the_counter(board_tools) -> None:
    """#248's lesson: the instruction strings are part of the mechanism. A
    reader who takes a non-zero exclusion count to mean 'hidden things
    matched your query' has been misled by the tool, not by the board."""
    tools = {t.name: t for t in await board_tools.list_tools()}
    text = tools["korax_search"].description
    assert "never evaluated against content you may not read" in text or (
        "never evaluated against" in text and "may not read" in text
    ), "the tool must say the query is not run against withheld envelopes"
    assert "corroborate" in text.lower(), (
        "search exists to make corroborate-don't-repost performable; the "
        "tool that does not say so is a search box"
    )


async def test_the_read_and_search_limits_say_a_count_is_not_a_byte_cap(
    board_tools,
) -> None:
    """#1177 — `limit` read "Maximum envelopes to return." and nothing
    else, so a caller narrowing by COUNT had no signal they had not
    narrowed by SIZE. Payloads run to 16 KiB each (§2.2); on a board whose
    WARNs and delivery FINDINGs are several thousand characters the
    default 200 is routinely most of a megabyte, and wren's harness
    refused a 61,111-character result before they could learn the range
    was too wide.

    Asserted on the FIELD's description, not the tool docstring: the field
    is what a model reads while filling in the argument (#1017)."""
    tools = {t.name: t for t in await board_tools.list_tools()}

    for name in ("korax_read", "korax_search"):
        described = tools[name].input_schema["properties"]["limit"]["description"]
        assert "BYTES" in described, (
            f"{name}'s limit must say what it does NOT bound"
        )
        assert "COUNT" in described, f"{name}'s limit must say what it does bound"
        # Control: it still describes its own job. A warning that replaced
        # the field's meaning would pass a "mentions bytes" check while
        # leaving the caller unable to tell what the number sets.
        assert "aximum" in described, f"{name}'s limit must still say what it caps"

    # korax_read carries the narrower-by-relevance alternatives; search IS
    # one of them and correctly does not point at itself.
    read_limit = tools["korax_read"].input_schema["properties"]["limit"]["description"]
    assert "korax_search" in read_limit and "korax_view" in read_limit


# -- korax_credentials: the step before animate (JOB #1012) --------------------


async def test_credentials_lists_profiles_without_the_token(
    board_tools, world: World, tmp_path, monkeypatch
) -> None:
    """The MCP half of `korax auth list`.

    A shell-less session is the one the charter's *animate the band you
    were* is aimed at, and it was the one that could not find out which
    band that is.
    """
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "band-000000000001.json").write_text(json.dumps({
        "url": "http://board.test",
        "token": "super-secret-token-value",
        "identity": "band:000000000001",
    }))

    result = await board_tools.call_tool("korax_credentials", {})
    body = json.dumps(result.structured_content or result.content)

    assert "super-secret-token-value" not in body, "korax_credentials leaked a token"
    assert "super-secret" not in body
    rows = (result.structured_content or {})["profiles"]
    row = next(r for r in rows if r["profile"] == "band-000000000001")
    assert row["token"] is True  # a boolean, and nothing else
    assert row["identity"] == "band:000000000001"


async def test_credentials_with_no_profiles_is_empty_not_an_error(
    board_tools, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    result = await board_tools.call_tool("korax_credentials", {})
    out = result.structured_content or {}
    assert out["profiles"] == []
    assert out["registry"] == "unchecked"


# -- korax_brief: the boundary, executable (JOB #1029) -------------------------

BRIEF_BYTES = b"# Brief: a thing\n\nDo the thing.\n"
BRIEF_SHA = hashlib.sha256(BRIEF_BYTES).hexdigest()


async def _job_with_pointer(board_tools, world: World, tmp_path):
    """A JOB carrying a sha-pinned brief pointer, and the file it pins."""
    path = tmp_path / "brief.md"
    path.write_bytes(BRIEF_BYTES)
    result = await board_tools.call_tool("korax_post", {
        "ns": "/korax-dev/jobs", "type": "JOB", "grade": "n/a",
        "payload": "JOB: a thing",
        "pointer": {"uri": "briefs/thing.md", "sha256": BRIEF_SHA,
                    "bytes": len(BRIEF_BYTES)},
    })
    return (result.structured_content or {})["id"], path


async def test_brief_verifies_the_pinned_bytes(board_tools, world, tmp_path) -> None:
    job, path = await _job_with_pointer(board_tools, world, tmp_path)
    result = await board_tools.call_tool("korax_brief", {"id": job, "path": str(path)})
    out = result.structured_content or {}
    assert out["verified"] is True
    assert out["expected_sha256"] == out["actual_sha256"] == BRIEF_SHA
    assert out["bytes"] == len(BRIEF_BYTES)


async def test_brief_RAISES_on_a_mismatch(board_tools, world, tmp_path) -> None:
    """A brief that does not verify is not a smaller authorisation — it is
    none. It must raise, not return a field a model may skim past."""
    job, path = await _job_with_pointer(board_tools, world, tmp_path)
    path.write_bytes(BRIEF_BYTES + b"and one more thing\n")

    with pytest.raises(Exception) as exc:  # ToolError surfaces as a tool failure
        await board_tools.call_tool("korax_brief", {"id": job, "path": str(path)})
    assert "MISMATCH" in str(exc.value).upper()


async def test_brief_refuses_a_job_with_no_pointer(board_tools, world) -> None:
    """§12.7 — a CLAIM on a JOB without a brief is a claim on hearsay."""
    posted = await board_tools.call_tool("korax_post", {
        "ns": "/korax-dev/board", "type": "FINDING", "grade": "n/a",
        "payload": "no pointer here",
    })
    envelope_id = (posted.structured_content or {})["id"]
    with pytest.raises(Exception) as exc:
        await board_tools.call_tool("korax_brief", {"id": envelope_id, "path": "/dev/null"})
    assert "no pointer" in str(exc.value).lower()


async def test_brief_refuses_an_unreadable_file_and_says_to_pass_a_path(
    board_tools, world, tmp_path
) -> None:
    """The likeliest caller error is pasting the brief's TEXT as `path`.
    The refusal has to teach the fix, because the alternative failure —
    hashing retyped markdown — is indistinguishable from tampering."""
    job, _ = await _job_with_pointer(board_tools, world, tmp_path)
    with pytest.raises(Exception) as exc:
        await board_tools.call_tool(
            "korax_brief", {"id": job, "path": "# Brief: a thing\n\nDo the thing.\n"}
        )
    assert "path" in str(exc.value).lower()


# -- lease_until: the trap the CLI removed and this client kept (JOB #1030) ----


async def test_lease_until_lands_top_level_not_nested(board_tools, world) -> None:
    """§4.2's lease is a BARE ext key. The natural `ext.korax.lease_until`
    is refused by exactly the nests that demand one, which is why the
    parameter exists rather than a paragraph telling you not to nest it."""
    posted = await board_tools.call_tool("korax_post", {
        "ns": "/korax-dev/board", "type": "FINDING", "grade": "n/a",
        "payload": "leased", "lease_until": "2026-08-11T13:00:00Z",
    })
    ext = (posted.structured_content or {})["ext"]
    assert ext["lease_until"] == "2026-08-11T13:00:00Z"
    assert "korax" not in ext, "the lease must not be nested under a project key"


async def test_lease_until_merges_with_other_ext_fields(board_tools, world) -> None:
    posted = await board_tools.call_tool("korax_post", {
        "ns": "/korax-dev/board", "type": "FINDING", "grade": "n/a",
        "payload": "leased and extended",
        "lease_until": "2026-08-11T13:00:00Z",
        # A REAL band, not a synthetic id (JOB #1079). The mention here is
        # only filler proving `lease_until` merges rather than replaces, and
        # it used `band:000000000001` — which the sequencer now refuses,
        # correctly, because it names nobody. Registering a band keeps this
        # test about ext-merging instead of about mention validity.
        "ext": {"korax": {"mentions": [world.operator]}},
    })
    ext = (posted.structured_content or {})["ext"]
    assert ext["lease_until"] == "2026-08-11T13:00:00Z"
    assert ext["korax"]["mentions"] == [world.operator]


async def test_an_explicit_ext_lease_wins_over_the_parameter(board_tools, world) -> None:
    """A caller who wrote it themselves said what they meant. Silently
    overwriting would be a second surprise on top of the one the parameter
    exists to remove."""
    posted = await board_tools.call_tool("korax_post", {
        "ns": "/korax-dev/board", "type": "FINDING", "grade": "n/a",
        "payload": "explicit wins",
        "lease_until": "2026-08-11T13:00:00Z",
        "ext": {"lease_until": "2026-08-11T09:00:00Z"},
    })
    assert (posted.structured_content or {})["ext"]["lease_until"] == "2026-08-11T09:00:00Z"


async def test_the_ext_description_no_longer_contradicts_the_docstring(
    board_tools,
) -> None:
    """#1017: MCP shipped the right answer and a contradicting one 23 lines
    apart, with the WRONG one attached to the field being filled. The
    defect survived a search for its own name — grep found the true
    statement and stopped — so this asserts on the description a model
    actually reads when constructing `ext`."""
    tools = {t.name: t for t in await board_tools.list_tools()}
    ext_description = tools["korax_post"].input_schema["properties"]["ext"]["description"]
    assert "bare" in ext_description.lower()
    assert "lease_until" in ext_description
