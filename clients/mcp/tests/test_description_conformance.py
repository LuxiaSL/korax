"""The RENDERED tool descriptions must not advertise a shorter menu than
the board serves — JOB #3766 (v2 R2b), acceptance 3.

WHY THIS IS NOT test_vocabulary_drift AGAIN. R170 pinned the CONSTANTS
(`KNOWN_ACTS` and friends) to the board's served sets. An agent never
reads a constant. It reads the sentence those constants are joined into
and shipped inside a tool's parameter description — a separate artifact,
produced by a separate step (`server.py:56-60`'s joins, then an f-string
per `Field`), and until this file nothing checked that step's output
against anything.

The distinction is not academic: the join could drop a row, a
description could interpolate the wrong constant, or a new parameter
could hard-code a list. In every one of those the constants stay correct,
R170's suite stays green, and the reader is told a menu shorter than the
kitchen — which is #3437's original complaint stated about the surface it
was actually about.

WHAT IS PARSED, AND OUT OF WHAT. The vocabulary is read back OUT OF THE
RENDERED DESCRIPTION and compared to what `korax_conformance` serves.
Neither side is a copy held in this file (#2595): the left side is the
artifact under test as an agent receives it, the right side is the board.
"""

from __future__ import annotations

import pytest

from korax_mcp.client import KoraxClient
from korax_mcp.server import build_server

from conftest import World

pytestmark = pytest.mark.anyio


#: marker in the rendered text -> key in korax_conformance's answer.
#: Property 1's "the test enumerates the vocabularies it covers by name":
#: this mapping IS that enumeration, and
#: `test_every_rendered_vocabulary_site_is_covered` reddens when a site
#: appears carrying a marker nobody registered here.
MARKERS = {
    "Known acts:": "acts",
    "Known edges:": "edges",
    "Defined by the protocol:": "views",
}

#: `One of:` introduces both grades and evidence values, and evidence is
#: not served by conformance — so the marker alone cannot say which
#: vocabulary a site carries. Keyed by (tool, parameter) instead, which is
#: why this is a separate table rather than another MARKERS row.
ONE_OF_SITES = {("korax_post", "grade"): "grades"}


@pytest.fixture()
async def board_tools(world: World):
    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        yield build_server(client)
    finally:
        await client.aclose()


def _advertised(description: str, marker: str) -> set[str]:
    """The vocabulary an agent reads out of this sentence.

    The rendered form is `<marker> a, b, c.` — the join is `", "` and the
    sentence ends at the first period, which no act, edge, view or grade
    contains.
    """
    tail = description.split(marker, 1)[1]
    return {token.strip() for token in tail.split(".", 1)[0].split(",") if token.strip()}


async def _sites(board_tools) -> list[tuple[str, str, str, str]]:
    """Every (tool, param, marker, description) carrying a vocabulary."""
    found = []
    for tool in await board_tools.list_tools():
        for param, spec in (tool.input_schema.get("properties") or {}).items():
            description = spec.get("description") or ""
            for marker in (*MARKERS, "One of:"):
                if marker in description:
                    found.append((tool.name, param, marker, description))
    return found


async def _served(board_tools) -> dict[str, set[str]]:
    body = (await board_tools.call_tool("korax_conformance", {})).structured_content
    return {key: set(body[key]) for key in ("acts", "edges", "views", "grades")}


# -- acceptance 3 -------------------------------------------------------------


@pytest.mark.parametrize("key", ["acts", "edges", "views", "grades"])
async def test_rendered_descriptions_advertise_what_the_board_serves(
    board_tools, key: str,
) -> None:
    """EQUALITY, both directions, ONE PARAMETRIZED CASE PER VOCABULARY.

    Per-vocabulary rather than one sweep, because acceptance 2 wants a
    mutation in one vocabulary to redden exactly that vocabulary — a
    single test over all four names every site on any fault and tells the
    reader nothing about which list moved.

    Equality, not subset: `advertised <= served` is TRUE in exactly the
    broken state this JOB was cut against (#3459 §1, measured), so a
    subset check greens on the bug. A missing entry tells the reader the
    board refuses what it accepts; a phantom one tells them to post what
    will bounce.
    """
    served = (await _served(board_tools))[key]
    mismatches = []
    for name, param, marker, description in await _sites(board_tools):
        site_key = MARKERS.get(marker) or ONE_OF_SITES.get((name, param))
        if site_key != key:
            continue
        advertised = _advertised(description, marker)
        if advertised != served:
            mismatches.append(
                f"{name}.{param}: served-but-not-advertised "
                f"{sorted(served - advertised)}, advertised-but-not-served "
                f"{sorted(advertised - served)}"
            )
    assert not mismatches, "\n  ".join(
        [f"rendered descriptions disagree with the board on `{key}`:", *mismatches]
    )


async def test_every_rendered_vocabulary_site_is_covered(board_tools) -> None:
    """The registration guard — property 1's last clause.

    A parameter added later carrying a vocabulary marker nobody mapped
    would sail past the test above via its `continue`. That is the same
    silent-skip this JOB exists to abolish, so the uncovered set is
    asserted empty and the failure names where to register the newcomer.
    """
    uncovered = [
        f"{name}.{param} carries `{marker}`"
        for name, param, marker, _ in await _sites(board_tools)
        if MARKERS.get(marker) is None and ONE_OF_SITES.get((name, param)) is None
        and (name, param) != ("korax_post", "evidence")
    ]
    assert not uncovered, (
        "rendered vocabulary sites with no registered conformance key — add "
        "them to MARKERS or ONE_OF_SITES in this file:\n  " + "\n  ".join(uncovered)
    )


async def test_the_sweep_reaches_the_sites_it_claims_to(board_tools) -> None:
    """Vacuity control. A parser that silently matched nothing would make
    both tests above pass forever, which is the shape they exist to catch
    one level down."""
    sites = await _sites(board_tools)
    covered = [s for s in sites if MARKERS.get(s[2]) or ONE_OF_SITES.get((s[0], s[1]))]
    assert len(covered) >= 5, (
        f"only {len(covered)} rendered vocabulary sites reached across "
        f"{len(sites)} markers found — the parser or list_tools stopped working"
    )
