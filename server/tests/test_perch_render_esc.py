"""`esc()` learns the single quote (O5, measured #2254, ruled #2262; JOB #2507).

`esc()` at render.js escaped `& < > "` and omitted `'`, leaving every
`innerHTML` site that interpolates through it one attribute-breakout short
of safe. `'` joins the class here.

Two kinds of check, per the perch's own stated limit (#706, restated
#962): **executed** (`run_node`) actually runs `esc()` under node and
asserts behaviour; **the R122 twin** below asserts the escape set ENTIRE,
one parametrized case per character, so removing any single character from
the class/map reddens exactly that case instead of shipping silently —
the same "the fix is the invariant, not the one call site" shape R122
used for `store.py`'s token mint (docs/korax-revisions.md R122).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from perch_source import script as _script

NODE = shutil.which("node")

ESCAPES = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
}


def _esc_source() -> str:
    src = _script()
    fn = re.search(r"function esc\(s\) \{.*?\n\}", src, re.S)
    assert fn, "esc() is no longer extractable — render.js was restructured"
    return fn.group(0)


def run_esc(s: str) -> str:
    program = _esc_source() + f"\nprocess.stdout.write(JSON.stringify(esc({json.dumps(s)})));"
    result = subprocess.run([NODE, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
@pytest.mark.parametrize("char,entity", sorted(ESCAPES.items()))
def test_each_special_character_escapes_to_its_entity(char: str, entity: str) -> None:
    """THE R122 TWIN — one case per character in the class. Delete any one
    mapping from esc() and exactly this parametrized case reddens; a single
    combined assertion over all five would not localize the omission, and
    would still pass if the deleted character happened not to appear in a
    shared fixture string."""
    assert run_esc(char) == entity


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_all_five_together_in_one_string() -> None:
    assert run_esc("""&<>"'""") == "&amp;&lt;&gt;&quot;&#39;"


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_plain_text_passes_through_unchanged() -> None:
    assert run_esc("korax-dev-enactor-vesper") == "korax-dev-enactor-vesper"


def test_the_class_is_stated_in_source_not_just_behaviour() -> None:
    """Structural backstop matching the file's own convention (#1389's
    seam vocabulary discipline): the regex character class must name all
    five characters, so a reviewer reading the diff sees the class change,
    not just a new entry in the replacement map."""
    src = _esc_source()
    assert '/[&<>"\']/' in src, (
        "esc()'s character class must contain & < > \" ' — found: " + src
    )
