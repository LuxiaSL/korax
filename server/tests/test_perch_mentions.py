"""The perch's mention picker (JOB #962).

WHAT THESE GUARDS ARE WORTH, said up front because the honest answer is
"less than you would like". `perch.html` has no JS test infrastructure and
this job did not build any — the same limit I named on #706 and it has not
moved. So there are two kinds of check here and they are not equal:

  - **Executed** (`mentionRefusal`): the function is extracted and RUN under
    node, so these assert behaviour. They skip where node is absent rather
    than pretending to pass.
  - **Structural** (the emission path): string checks over the served page.
    They catch DELETION and rename, not correctness — #111's shape. A build
    that emitted display names through a differently-spelled path would slip
    past them, which is exactly why the executed half exists at all.

The mutation table in the delivery demonstrates that split rather than
asserting it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from perch_source import PERCH_DIR, markup as _markup, script as _script
NODE = shutil.which("node")


def page() -> str:
    return _markup()


def script() -> str:
    return _script()


# -- executed: the refusal, actually run ---------------------------------------


def run_node(expression: str) -> object:
    """Evaluate one expression against the perch's own extracted source."""
    source = script()
    # `mentionRefusal` is pure and depends only on PRIVATE_ROOTS, so it can be
    # lifted out whole. Everything else in the file touches the DOM.
    fn = re.search(r"(const PRIVATE_ROOTS = .*?\n\})", source, re.S)
    assert fn, "mentionRefusal is no longer extractable — the picker was restructured"
    program = fn.group(1) + f"\nprocess.stdout.write(JSON.stringify({expression}));"
    result = subprocess.run([NODE, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_public_nest_refuses_nobody() -> None:
    assert run_node('mentionRefusal("/korax-dev/board", "band:abc")') is None


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_mentioning_into_someone_elses_mailbox_is_refused() -> None:
    """feed.py:404, ruled #324 D5. The server is the boundary; this only
    moves the discovery earlier."""
    why = run_node('mentionRefusal("/dm/band:aaa", "band:bbb")')
    assert why and "structurally private" in why


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_band_may_be_mentioned_in_their_own_room() -> None:
    """THE CASE THAT MAKES THE RULE A RULE rather than a blanket ban —
    `mention_refusal` lets it through (`their own room; they read it by
    participation`), so a picker that refused it would be stricter than the
    board and wrong in the direction that looks safe."""
    assert run_node('mentionRefusal("/dm/band:aaa", "band:aaa")') is None


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_scratch_is_private_too() -> None:
    """CANARY (#10). `_PRIVATE_ROOTS` is ("/dm", "/scratch") and a picker
    that only knew about /dm would pass every test above."""
    assert run_node('mentionRefusal("/scratch/x", "band:bbb")')


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_nest_merely_starting_with_the_root_name_is_not_private() -> None:
    """`/dmz/board` is not `/dm`. Prefix matching without a separator is how
    a public nest gets treated as a mailbox."""
    assert run_node('mentionRefusal("/dmz/board", "band:bbb")') is None


# -- structural: the emission path ---------------------------------------------


def test_the_selection_is_keyed_on_the_band_id() -> None:
    """THE ONE THAT MATTERS, and the brief names it: a display name is
    accepted by the board, rides in a well-formed envelope, and reaches
    nobody, because the lane matches on id (#223's family). Two bands on
    this board share the display `korax-dev-enactor-vesper`, so the name is
    not even unique enough to disambiguate with."""
    source = script()
    assert 'data-id="${esc(i.id)}"' in source, (
        "the picker row no longer carries the band id as its key"
    )
    assert "MENTIONS.add(r.dataset.id)" in source
    assert "mentions: [...MENTIONS]" in source, (
        "the emitted mentions list is no longer the selected id set"
    )
    assert 'mentions: [...MENTIONS.values()].map' not in source, (
        "a mapping step over the emitted set is where a display name gets in"
    )


def test_every_row_shows_its_id_not_only_a_name() -> None:
    """Two bands share a display here, so a row showing only the name asks
    the human to pick between two identical options."""
    # both halves live in renderMentions, which JOB #1927 moved to
    # js/tabs/speak.js — read the composed script, not the shell alone.
    assert 'class="mid"' in script()
    assert "${esc(i.id)}</span>" in script()


def test_other_ext_keys_survive_the_picker() -> None:
    """MERGE, never overwrite (#880). Asserted structurally: the ext object
    is spread rather than replaced."""
    assert "ext.korax = { ...(ext.korax || {}), mentions:" in script()


def test_the_picker_is_actually_IN_THE_MARKUP() -> None:
    """#111's shape, named: this catches DELETION of the picker, not that it
    works. It is the weakest guard here and worth saying so rather than
    letting a passing count imply coverage.

    AND IT ASSERTS THE MARKUP, NOT THE NAME. The first version searched the
    whole page for `mentionList`, which the SCRIPT also contains as
    `$("#mentionList")` — so deleting the element from the DOM left the
    string behind and the guard passed on a page with no picker in it. My
    own mutation pass caught that, and it is rake #478: one signal with two
    sources cannot tell you which one spoke. The `id=` attribute only
    appears in the markup.
    """
    markup = page().split("<script")[0]
    for element in ("mentionList", "mentionFilter", "mentionAll",
                    "mentionNone", "mentionWarn", "mentionCount"):
        assert f'id="{element}"' in markup, (
            f"the picker element {element} is not in the served markup"
        )
    assert "korax.mentions" in script(), "nothing emits the mention field"
