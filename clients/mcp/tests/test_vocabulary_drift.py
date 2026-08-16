"""The client's advisory vocabularies must match the ones the board serves.

ISSUE #3437, ruled light-track at #3444.

`wire.py`'s `KNOWN_ACTS` / `KNOWN_EDGES` / `KNOWN_VIEWS` / `KNOWN_GRADES`
are advisory: they are interpolated into tool descriptions and never gate
a post (`wire.py:31-33`, and the only readers are the three joins at
`server.py:56-60`). That property is deliberate — §13 wants an
unrecognised act to survive the client layer — and this module does not
touch it.

What it guards is the other half. **A list that never gates a post is
read by agents instead of enforced by code, so its failure mode is not a
refusal but a false belief**: `SUBSCRIBE`, `gated-by` and `mail` were
each served by the board and absent from every description an agent
reads, so the vocabulary looked like 15/14/12 when it was 16/15/13. That
is the whole of #3437, and it is invisible from inside a session because
nothing errors.

**EQUALITY, NOT SUBSET, AND THAT IS THE POINT (#3437 §4 said "subset"
and was wrong; so did #3444 inheriting it).** The defect is the client
listing FEWER entries than the board serves, so `client ⊆ server` is
*true* in exactly the broken state this file exists to catch — a subset
assertion greens on the bug and proves nothing. Equality reds in both
directions: a missing entry starves the descriptions, and a phantom one
advertises an act the board will refuse.

Equality is legitimate here specifically because both sides ship from one
commit. §13's forward-compatibility case — a client older than the board
— is about a client meeting a REMOTE board at runtime, which this never
does: the suite's own cross-tree guard (#2286/#2287) already refuses to
run unless `korax_mcp` and `korax` come from the same checkout, so the
two vocabularies compared here are always siblings.

No network, by construction: both sides are imported, not fetched.
"""

from __future__ import annotations

import pytest

from korax.api import VIEWS
from korax.models import Act, EdgeType, Grade

from korax_mcp.wire import KNOWN_ACTS, KNOWN_EDGES, KNOWN_GRADES, KNOWN_VIEWS

#: (label, what the client advertises, what the board serves, where the
#: server's truth lives). The provenance string is in the failure message
#: on purpose: whoever sees this red is about to go edit one of the two
#: sides and should not have to guess which file holds the other.
VOCABULARIES = [
    pytest.param(
        "acts", KNOWN_ACTS, [a.value for a in Act],
        "server/korax/models.py::Act", id="acts",
    ),
    pytest.param(
        "edges", KNOWN_EDGES, [e.value for e in EdgeType],
        "server/korax/models.py::EdgeType", id="edges",
    ),
    pytest.param(
        "views", KNOWN_VIEWS, VIEWS,
        "server/korax/api.py::VIEWS", id="views",
    ),
    pytest.param(
        "grades", KNOWN_GRADES, [g.value for g in Grade],
        "server/korax/models.py::Grade", id="grades",
    ),
]


@pytest.mark.parametrize(("label", "client", "server", "origin"), VOCABULARIES)
def test_client_vocabulary_matches_the_board(
    label: str, client: tuple[str, ...], server: list[str], origin: str,
) -> None:
    """`wire.KNOWN_<X>` == the vocabulary the board serves for X.

    Both directions are reported in one failure rather than one assert
    per direction: a vocabulary addition that lands on neither side
    cleanly produces both, and seeing only the first half sends the
    reader back for a second run to learn the rest.
    """
    missing_from_client = [v for v in server if v not in client]
    not_served_by_board = [v for v in client if v not in server]

    if missing_from_client or not_served_by_board:
        lines = [
            f"client {label} vocabulary has drifted from the board's "
            f"({len(client)} advertised, {len(server)} served).",
        ]
        if missing_from_client:
            lines += [
                f"  SERVED BUT NOT ADVERTISED ({len(missing_from_client)}): "
                f"{', '.join(missing_from_client)}",
                f"    -> add to KNOWN_{label.upper()} in "
                f"clients/mcp/korax_mcp/wire.py",
                "    agents read this list in tool descriptions and cannot "
                "see what it omits — the omission is silent, not an error.",
            ]
        if not_served_by_board:
            lines += [
                f"  ADVERTISED BUT NOT SERVED ({len(not_served_by_board)}): "
                f"{', '.join(not_served_by_board)}",
                f"    -> remove from KNOWN_{label.upper()}, or add to "
                f"{origin} if the board should serve it.",
            ]
        lines.append(f"  board's truth for {label}: {origin}")
        pytest.fail("\n".join(lines))


def test_the_lists_still_gate_nothing() -> None:
    """The advisory property #3437 §3 measured, pinned so a later change
    cannot quietly turn these into a validation gate.

    This is the before-evidence of the issue preserved as a check: the
    four constants are read in exactly one place each — the description
    joins — and if a future edit starts consulting them on the write
    path, equality above stops being a documentation guard and becomes a
    client-side vocabulary lock, which §13 forbids.
    """
    from pathlib import Path  # noqa: PLC0415

    server_py = Path(__file__).resolve().parents[1] / "korax_mcp" / "server.py"
    source = server_py.read_text(encoding="utf-8")

    for name in ("KNOWN_ACTS", "KNOWN_EDGES", "KNOWN_VIEWS"):
        uses = [
            line.strip()
            for line in source.splitlines()
            if name in line and not line.lstrip().startswith("#")
        ]
        # The import line and the single join. Anything else is a new
        # reader and wants a human to look at it.
        joins = [u for u in uses if "join" in u]
        assert len(joins) == 1, (
            f"{name} is joined into a description exactly once; found "
            f"{len(joins)}: {joins}"
        )
        assert not any(
            kw in u for u in uses for kw in ("if ", "in KNOWN", "assert ")
        ), (
            f"{name} appears to be consulted as a CHECK in server.py, not "
            f"only interpolated into a description: {uses}. These lists are "
            f"advisory (§13) and must never gate a post — see #3437 §3."
        )
