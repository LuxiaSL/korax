"""The perch's ENTIRE executable script must parse — now across files.

Shipped after the desk committed a merge with conflict markers in the
monolithic `perch.html` (R74) that **540 green tests did not catch**:
structural tests assert strings are PRESENT, executed tests extract
single functions, and the browser was the first whole-script parser to
touch the page — in the operator's console. `node --check` closes that
class (R75).

The split (JOB #1389, design #1385 D4) widens the guard instead of
retiring it, per the mill's #1382: the js files are discovered by
GLOB WITH A NON-EMPTY ASSERTION, never a hand-kept list — a list-driven
guard means a new tab file ships unparsed under a green suite, which is
R74's shape with a new door into it. Each file must parse ALONE (a file
is the unit a merge conflicts in) AND the load-order concatenation must
parse (what the browser actually executes); the marker grep walks every
file in the directory; and the manifest test holds in BOTH directions,
because "green gate, served page 404s a module" is the split's own new
silent-failure class and it gets its guard in the same commit that
created the risk.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile

import pytest

from perch_source import INDEX, PERCH_DIR, markup, script

NODE = shutil.which("node")


def _js_files() -> list:
    files = sorted(PERCH_DIR.glob("js/**/*.js"))
    assert files, (
        "the glob found no js files — either the layout moved or this "
        "guard has gone vacuous, and a vacuous parser guard is R74's door"
    )
    return files


def _node_check(source: str, label: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(source)
        path = f.name
    done = subprocess.run([NODE, "--check", path], capture_output=True, text=True)
    assert done.returncode == 0, (
        f"{label} does not parse — a browser will refuse it silently at "
        f"load:\n{done.stderr[:500]}"
    )


@pytest.mark.skipif(NODE is None, reason="node absent; syntax cannot be checked")
def test_every_js_file_parses_alone() -> None:
    """A file is the unit a merge conflicts in, so each must parse by
    itself — a marker committed into one file must redden the suite even
    if concatenation happens to mask it."""
    for path in _js_files():
        _node_check(path.read_text(), str(path.relative_to(PERCH_DIR)))


@pytest.mark.skipif(NODE is None, reason="node absent; syntax cannot be checked")
def test_the_whole_script_parses_in_load_order() -> None:
    """What the browser executes: external files resolved and inline
    blocks kept, in DOM order (perch_source is the one implementation
    of that composition)."""
    _node_check(script(), "the perch's load-order script concatenation")


def test_no_conflict_markers_anywhere_in_the_split() -> None:
    """The marker grep walks EVERY file under perch/ — markup, css and
    js alike: markers in markup render as visible garbage, in css they
    silently kill every rule after them, and neither reaches node."""
    files = sorted(p for p in PERCH_DIR.rglob("*") if p.is_file())
    assert files, "the perch directory is empty — the guard has nothing to walk"
    for path in files:
        text = path.read_text()
        for marker in ("<<<<<<<", ">>>>>>>", "\n=======\n"):
            assert marker not in text, (
                f"merge conflict marker {marker!r} in {path.relative_to(PERCH_DIR)}"
            )


# -- the manifest, both directions (#1385 D4) ---------------------------


def _shell_refs() -> set:
    return set(re.findall(r"""(?:src|href)=["'](/perch/[^"']+)["']""", markup()))


def test_every_shell_reference_resolves_to_a_file() -> None:
    """Direction one: a `<script src>`/`<link href>` naming a file that
    does not exist is a page that 404s a module under a green suite."""
    for url in sorted(_shell_refs()):
        target = PERCH_DIR / url[len("/perch/"):]
        assert target.is_file(), f"the shell references {url} and no such file exists"


def test_every_asset_file_is_referenced_by_the_shell() -> None:
    """Direction two: a file on disk the shell never loads is dead code
    that LOOKS live — the next reader edits it, tests stay green, the
    page never changes, and the divergence is silent forever."""
    refs = {url[len("/perch/"):] for url in _shell_refs()}
    on_disk = {
        str(p.relative_to(PERCH_DIR))
        for p in PERCH_DIR.rglob("*")
        if p.is_file() and p.suffix in (".css", ".js")
    }
    unreferenced = on_disk - refs
    assert not unreferenced, (
        f"files under perch/ the shell never references: {sorted(unreferenced)}"
    )


def test_the_shell_exists_and_is_the_only_html() -> None:
    """The route serves index.html by name; a second html file under
    perch/ would be reachable yet composed by nothing."""
    assert INDEX.is_file()
    assert [p.name for p in PERCH_DIR.rglob("*.html")] == ["index.html"]
