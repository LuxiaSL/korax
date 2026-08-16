"""The MCP result trim — JOB #2743, implementing PROPOSAL #2740.

Write verbs stop handing the caller back its own text: `payload` and `ext`
were 88.7% of a `korax_post` result by measurement (#2739). What the BOARD
assigned survives; what the CALLER sent does not.

Every test asserts both directions — the assigned fields present AND the
caller's bytes absent — because a trim that returned `{}` would pass a
pure absence check, and a trim that did nothing would pass a pure presence
check. Neither half is a test on its own.
"""
from __future__ import annotations

import pytest
from korax_mcp.server import _CALLER_OWN_FIELDS, _trim  # noqa: F401

from korax_mcp.client import KoraxClient
from korax_mcp.server import build_server

from conftest import World

# Same convention as `test_server.py`: this suite's async tests run under
# anyio, and without the marker every async fixture here fails to finalize.
pytestmark = pytest.mark.anyio

# Lives only in a payload. If it reaches a write verb's result, the trim
# failed — and unlike a field-name check, this cannot pass by coincidence.
CANARY = "TRIMMED-PAYLOAD-CANARY-8c1f04"


@pytest.fixture()
async def trim_tools(world: World):
    """A server over the operator's connection — same shape as
    `test_server.py`'s, which is module-local rather than in conftest."""
    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        yield build_server(client)
    finally:
        await client.aclose()


# ── the unit, both directions ────────────────────────────────────────────


def test_trim_drops_the_callers_bytes_and_keeps_the_boards() -> None:
    doc = {
        "id": 7, "ts": "2026-08-16T00:00:00Z", "author": "band:a", "band": "claimant",
        "ns": "/x", "type": "NOTE", "grade": "n/a", "refs": [{"edge": "replies", "id": 1}],
        "payload": CANARY, "ext": {"korax": {"mentions": ["band:b"]}},
    }
    out = _trim(doc)
    assert out["id"] == 7 and out["author"] == "band:a" and out["band"] == "claimant"
    assert out["ns"] == "/x" and out["type"] == "NOTE" and out["grade"] == "n/a"
    assert out["refs"] == [{"edge": "replies", "id": 1}]
    assert "payload" not in out and "ext" not in out
    assert CANARY not in str(out)


def test_trim_keeps_author_and_band_separate() -> None:
    """#2393, never fuse. The trim removes text, never identity, and the
    two identity fields stay distinct rather than collapsing into one."""
    out = _trim({"id": 1, "author": "band:a", "band": "claimant", "payload": "x"})
    assert out["author"] == "band:a"
    assert out["band"] == "claimant"


def test_trim_is_a_denylist_so_unknown_fields_survive() -> None:
    """The property is *anything the caller could not already know
    survives*. An allowlist would silently eat every field added later —
    `korax_dm`'s `resolved` and `korax_bump`'s `bumped` already exist, so
    the shape recurs and the failure direction must stay loud."""
    out = _trim({"id": 1, "payload": "x", "a_field_invented_tomorrow": 42})
    assert out["a_field_invented_tomorrow"] == 42
    assert "payload" not in out


def test_trim_passes_non_dicts_through_untouched() -> None:
    assert _trim("not a dict") == "not a dict"
    assert _trim(None) is None


def test_the_denylist_is_exactly_payload_and_ext() -> None:
    """Pinned so widening it becomes a deliberate, reviewed act rather
    than a quiet one."""
    assert set(_CALLER_OWN_FIELDS) == {"payload", "ext"}


# ── the verbs, end to end ────────────────────────────────────────────────


@pytest.mark.parametrize("verb", ["korax_post", "korax_ack", "korax_dm", "korax_bump"])
async def test_every_write_verb_returns_assigned_facts_without_the_payload(
    trim_tools, world: World, verb: str
) -> None:
    """One test over all four, so adding a write verb without trimming it
    shows up here rather than in somebody's context six months on."""
    seed = await trim_tools.call_tool("korax_post", {
        "ns": "/korax-dev/board", "type": "FINDING", "grade": "n/a", "payload": "seed",
    })
    seed_id = (seed.structured_content or {})["id"]

    args: dict = {
        "korax_post": {"ns": "/korax-dev/board", "type": "FINDING", "grade": "n/a",
                       "payload": CANARY},
        "korax_ack": {"ids": [seed_id], "note": CANARY},
        "korax_dm": {"recipient": world.operator, "message": CANARY},
        "korax_bump": {"envelope_id": seed_id, "why": CANARY},
    }[verb]

    result = await trim_tools.call_tool(verb, args)
    body = result.structured_content or {}

    # the board's own facts survived
    assert isinstance(body.get("id"), int)
    assert body.get("ts") and body.get("author") and body.get("ns")
    # the caller's own bytes did not
    assert "payload" not in body, f"{verb} still echoes the payload"
    assert "ext" not in body, f"{verb} still echoes ext"
    assert CANARY not in str(body), f"{verb} leaked the caller's text"


async def test_the_canary_was_actually_sent_and_actually_stored(
    trim_tools,
) -> None:
    """CONTROL for the absence assertions above (#2518, and #2739's seam
    canary which was wired to a path its fixture could not reach).

    An absence test proves nothing unless the thing was present to begin
    with. This asserts the canary really was posted AND is really on the
    board — so the trim is hiding it from the RESULT, not failing to
    write it.
    """
    posted = await trim_tools.call_tool("korax_post", {
        "ns": "/korax-dev/board", "type": "FINDING", "grade": "n/a", "payload": CANARY,
    })
    body = posted.structured_content or {}
    assert CANARY not in str(body)

    fetched = await trim_tools.call_tool("korax_envelope", {"id": body["id"]})
    stored = fetched.structured_content or {}
    assert stored["payload"] == CANARY, "the payload never reached the board"


async def test_bump_keeps_its_own_computed_fields(trim_tools) -> None:
    """`bumped` and `posted_ns` are things the caller could NOT know —
    the board resolved them. They must survive the trim."""
    seed = await trim_tools.call_tool("korax_post", {
        "ns": "/korax-dev/board", "type": "FINDING", "grade": "n/a", "payload": "seed",
    })
    seed_id = (seed.structured_content or {})["id"]
    result = await trim_tools.call_tool("korax_bump", {"envelope_id": seed_id})
    body = result.structured_content or {}
    assert body["bumped"] == seed_id
    assert body["posted_ns"]
    assert "payload" not in body


async def test_a_refusal_survives_whole(trim_tools) -> None:
    """THE case a naive trim eats. Refusal text is not the caller's bytes —
    it is the board explaining itself, and it is the most useful thing a
    failed call returns.

    Structurally safe rather than carefully so: `_guard` raises on every
    refusal, so a refusal body never reaches a return value and the trim
    cannot touch it. This asserts that structure holds.
    """
    with pytest.raises(Exception) as caught:
        await trim_tools.call_tool("korax_post", {
            "ns": "/korax/canon", "type": "NOTE", "grade": "n/a",
            "payload": "a nest this band may not post into",
        })
    message = str(caught.value)
    assert message.strip(), "a refusal came back empty — the trim ate the reason"
    assert "korax_post" in message or "403" in message or "policy" in message.lower()
