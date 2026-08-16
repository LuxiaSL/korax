"""The MCP annotates a board response; it never overwrites it — #2392.

**Both call sites are unreachable today**, because the board sends
neither `binding` nor `serving`. That is the whole reason this file has
to construct the collision by hand: a suite exercising only the happy
path passes **identically before and after the fix**, so it would prove
nothing and read as coverage. Said out loud at #2408 before the work
was claimed, so the standard could not be invented afterwards.

The pairing throughout is #112's: the canary makes the collision
happen, and the control beside it proves the ordinary path still
reports this client's own facts. A guard that renamed unconditionally
would pass every canary here and silently move a field every existing
caller reads.
"""

from __future__ import annotations

from korax_mcp.server import _annotate


# ── the ordinary path: nothing collides, nothing changes ──────────────


def test_it_adds_its_own_key_when_the_board_sent_none() -> None:
    """THE CONTROL, and it is the case every caller alive today hits."""
    body = {"identity": "band:aaaa", "head": 7}
    out = _annotate(body, "binding", {"how": "animated-this-connection"})

    assert out["binding"] == {"how": "animated-this-connection"}
    assert out["identity"] == "band:aaaa"
    assert out["head"] == 7
    assert "korax_binding" not in out, (
        "with no collision the client's report belongs under its documented "
        "key — renaming unconditionally would move a field every caller reads"
    )


def test_it_does_not_mutate_the_response_it_was_handed() -> None:
    """`dict(body, ...)` rather than `body[key] = ...`. The caller's object
    is not this function's to edit, and a mutation would outlive the
    return."""
    body = {"identity": "band:aaaa"}
    _annotate(body, "serving", {"built_from": "abc"})
    assert body == {"identity": "band:aaaa"}


# ── the collision: the case that does not exist yet ───────────────────


def test_a_board_sent_key_SURVIVES(capsys) -> None:
    """THE CANARY. The board's value is the one that must not move.

    This is the whole defect: `out["serving"] = serving` deleted whatever
    the board put there, and the deletion would have been silent — the
    response still has a `serving` key, still well-formed, describing the
    wrong process.
    """
    body = {"proto": "korax/0.1", "serving": {"boot_id": "board-side-value"}}
    out = _annotate(body, "serving", {"built_from": "client-side-value"})

    assert out["serving"] == {"boot_id": "board-side-value"}, (
        "the board's field was overwritten — #2392 exactly"
    )
    assert out["korax_serving"] == {"built_from": "client-side-value"}
    assert "board sent its own `serving`" in out["korax_serving_note"]


def test_the_collision_is_announced_on_stderr_not_stdout(capsys) -> None:
    """stdout is the MCP protocol channel and must carry nothing but
    protocol. A rename nobody is told about is a quieter version of the
    same defect, so it goes to stderr AND rides the result where the
    agent reading the response can see it."""
    body = {"binding": {"how": "board-side"}}
    out = _annotate(body, "binding", {"how": "client-side"})

    captured = capsys.readouterr()
    assert "korax-mcp:" in captured.err
    assert captured.out == "", "nothing may be written to the protocol channel"
    assert "korax_binding_note" in out


def test_no_announcement_when_nothing_collided__control(capsys) -> None:
    """THE CONTROL for the stderr canary. A warner that fired on every
    call would pass the test above while making the signal worthless."""
    _annotate({"identity": "band:aaaa"}, "binding", {"how": "x"})
    assert capsys.readouterr().err == ""


# ── both live call sites are covered, asserted structurally ───────────


def test_both_known_sites_route_through_the_guard() -> None:
    """The class, not the instance.

    #2392 named one site; the second was eighty-two lines away in the
    same file and would have been left armed by a fix aimed at the
    filing. This asserts against the SOURCE so a third site added later
    without the guard reddens here rather than shipping — the same
    control-by-construction argument as the route table in `why`.
    """
    import inspect

    from korax_mcp import server as mcp_server

    source = inspect.getsource(mcp_server)

    for forbidden in ('who["binding"] =', 'out["serving"] ='):
        assert forbidden not in source, (
            f"{forbidden} writes a client key onto the board's response "
            "without the §13 check — that is #2392, reintroduced"
        )
    assert source.count("_annotate(") >= 3, (
        "expected the definition plus both call sites; a site that stopped "
        "using the guard would drop this below three"
    )
