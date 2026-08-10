"""Harness conventions — the mechanism half of the #672 split.

The obligations live in the charter, because they are true on any
harness. The mechanisms live here, because they are true of this host
this week, and they ship *inside* the package so they travel with the
code and stale at its clock. A sibling file would not: `pyproject.toml`
declares `packages = ["korax_cli"]`, so only what is under the package
directory reaches the wheel.

This module is the single reader of `conventions.md`. `korax
conventions` serves what it parses and the suite checks what it parses,
so the served document and the tested document cannot drift apart —
which is the failure the whole file is about, one level down.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CONVENTIONS_PATH = Path(__file__).resolve().parent / "conventions.md"

# `### <mechanism>` followed, on the next non-blank line, by `expires: #<id>`.
# The id is mandatory by #671 and the parser refuses an entry without one
# rather than admitting it with a null — an entry with no expiry is the
# thing the admission rule exists to keep out, and a lenient parser would
# quietly re-admit it.
_ENTRY = re.compile(
    r"^### +(?P<mechanism>.+?)\s*\n+expires: +#(?P<expires>\d+)\s*$",
    re.MULTILINE,
)
_HEADING = re.compile(r"^### +(?P<mechanism>.+?)\s*$", re.MULTILINE)


def load_text() -> str:
    """The conventions document as shipped."""
    return CONVENTIONS_PATH.read_text(encoding="utf-8")


def parse_entries(text: str) -> list[dict[str, Any]]:
    """Every `(mechanism, expiry issue id)` pair in the document.

    Refuses rather than skips: a `###` heading with no `expires:` line is
    an inadmissible entry (§#671), and returning the admissible subset
    would report a clean list for a document that had just admitted
    folklore.
    """
    entries = [
        {"mechanism": m.group("mechanism"), "expires": int(m.group("expires"))}
        for m in _ENTRY.finditer(text)
    ]
    headings = [m.group("mechanism") for m in _HEADING.finditer(text)]
    if len(headings) != len(entries):
        named = {e["mechanism"] for e in entries}
        missing = [h for h in headings if h not in named]
        raise ValueError(
            "conventions entries without an `expires: #<id>` line, which "
            f"#671 makes inadmissible: {missing}"
        )
    return entries
