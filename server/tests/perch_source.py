"""The perch's source, as ONE thing the tests read (JOB #1389).

Before the split every perch test opened `perch.html` and regexed its
script blocks independently. After the split the page is a SHELL plus
static files, and "the script" means *everything the browser will
execute, in the order it will execute it* — external `<script src>`
files resolved from disk, inline blocks kept in place. Getting that
order wrong in one test's private helper would test a page no browser
loads, silently; so the composition lives here, once.

Not a test file: no `test_` functions. Imported by the perch suites.
"""

from __future__ import annotations

import re
from pathlib import Path

PERCH_DIR = Path(__file__).resolve().parents[1] / "korax" / "perch"
INDEX = PERCH_DIR / "index.html"

_SCRIPT_TAG = re.compile(r"<script([^>]*)>(.*?)</script>", re.S)
_SRC_ATTR = re.compile(r"""src=["']([^"']+)["']""")


def markup() -> str:
    return INDEX.read_text()


def asset_path(url: str) -> Path:
    """A shell-relative asset URL (`/perch/js/x.js`) to its file."""
    assert url.startswith("/perch/"), f"not a perch asset url: {url}"
    return PERCH_DIR / url[len("/perch/"):]


def script_units() -> list[tuple[str, str]]:
    """(name, source) for every script the page runs, in load order."""
    units: list[tuple[str, str]] = []
    for attrs, body in _SCRIPT_TAG.findall(markup()):
        src = _SRC_ATTR.search(attrs)
        if src:
            units.append((src.group(1), asset_path(src.group(1)).read_text()))
        elif body.strip():
            units.append(("<inline>", body))
    assert units, "the shell serves no script at all"
    return units


def script() -> str:
    """The whole executable script, concatenated in load order — what
    `node --check` and the structural greps run against."""
    return "\n".join(source for _, source in script_units())
