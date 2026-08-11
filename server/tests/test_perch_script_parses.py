"""The perch's ENTIRE script must be syntactically valid JavaScript.

Shipped after the desk committed a merge with conflict markers in
`perch.html` (R74's resolver fixed the ledger conflict and `git add -A`
staged this file with `<<<<<<<` still in it). **540 tests were green over
it**: the structural tests assert strings are PRESENT (markers do not
remove strings), and the executed tests extract single functions by regex
(markers between functions never enter the extraction). The browser was
the first thing to parse the whole script, and it failed on line 531 in
front of the operator.

One check closes the class: `node --check` over the concatenated script
blocks. It catches conflict markers, truncated templates, and any other
whole-file syntax damage — everything a browser would refuse — at commit
time instead of at the operator's console.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

PERCH = Path(__file__).resolve().parents[1] / "korax" / "perch.html"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node absent; syntax cannot be checked")
def test_the_whole_perch_script_parses() -> None:
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", PERCH.read_text(), re.S)
    assert blocks, "the perch serves no script block"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write("\n".join(blocks))
        path = f.name
    done = subprocess.run([NODE, "--check", path], capture_output=True, text=True)
    assert done.returncode == 0, (
        "the perch's script does not parse — a browser will refuse the whole "
        f"page silently at load:\n{done.stderr[:500]}"
    )


def test_no_conflict_markers_anywhere_in_the_page() -> None:
    """Belt to the check above's braces: markers in MARKUP would render as
    visible garbage rather than failing to parse, and node cannot see them."""
    text = PERCH.read_text()
    for marker in ("<<<<<<<", ">>>>>>>", "\n=======\n"):
        assert marker not in text, f"merge conflict marker {marker!r} in perch.html"
