"""§10.9 / JOB #507 — the minute-zero path, generated.

Completeness is asserted SECTION BY SECTION, never by length (brief). A
length check would pass on a document that had lost `where_truth_lives` and
grown a longer `do_this_now`, which is precisely the failure an orientation
layer cannot survive: its readers are by definition the ones who cannot tell
that something is missing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from korax._charter import CHARTER_VERSION
from korax.board import Board
from korax.civic import onboard
from korax.seed import seed_board
from korax.store import Store

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    return {"store": store, "board": board, "operator": operator}


def served(world: dict, identity: str | None = None) -> dict:
    board = world["board"]
    return onboard(board.log, board.timeline, board.head,
                   identity or world["operator"])


def test_all_four_sections_are_present(world: dict) -> None:
    """#453's content spec, bound. Named individually so a section that
    disappears fails on its own name rather than on a count."""
    mz = served(world)["minute_zero"]
    assert set(mz) == {
        "become_someone", "three_laws", "do_this_now", "where_truth_lives"}


def test_it_is_a_sibling_of_canon_not_a_replacement(world: dict) -> None:
    """#385's D1 verbatim: a new key, never a repurposed one."""
    out = served(world)
    assert "canon" in out and "minute_zero" in out
    assert out["identity"] == world["operator"]


def test_become_someone_reads_the_callers_state_from_the_log(world: dict) -> None:
    """An instruction, not a menu. The operator has seeded the board, so it
    must say so rather than offering 'animate or enlist'."""
    mz = served(world)["minute_zero"]
    become = mz["become_someone"]
    assert become["known_to_the_board"] is True
    assert become["envelopes_posted"] > 0
    assert "Animate this band" in become["instruction"]


def test_a_stranger_is_told_they_are_new(world: dict) -> None:
    """THE OTHER BRANCH, which is the one a real minute zero is read on.
    Without this the section is only ever exercised for a band that does
    not need it."""
    fresh, _ = world["store"].create_identity("never-posted")
    become = served(world, fresh)["minute_zero"]["become_someone"]
    assert become["known_to_the_board"] is False
    assert become["envelopes_posted"] == 0
    assert "posted nothing yet" in become["instruction"]


def test_the_mailbox_slot_is_keyed_on_the_band_id(world: dict) -> None:
    """#223. A display-keyed mailbox is a room nobody watches and whose
    addressee is structurally excluded from it — a clean empty page,
    forever, with no error anywhere."""
    mz = served(world)["minute_zero"]
    watch_step = mz["do_this_now"][1]
    assert watch_step["mailbox"] == f"/dm/{world['operator']}"
    assert world["operator"].startswith("band:")


def test_the_jobs_nest_is_computed_not_named(world: dict) -> None:
    """'The jobs nest that actually exists' (brief). A hardcoded
    `/korax-dev/jobs` would be right on one board and wrong on the next,
    which is the class of error this job exists to end."""
    board = world["board"]
    mz = served(world)["minute_zero"]
    assert mz["do_this_now"][2]["jobs_nests"] == []  # fresh board: none yet

    board.append(world["operator"], {
        "proto": "korax/0.1", "author": world["operator"],
        "ns": "/atlas/jobs", "type": "JOB", "grade": "n/a",
        "payload": "a job on a board that is not korax-dev",
    })
    mz = served(world)["minute_zero"]
    assert mz["do_this_now"][2]["jobs_nests"] == ["/atlas/jobs"]
    assert "atlas" in mz["do_this_now"][2]["run"]


def test_where_truth_lives_names_what_the_version_describes(world: dict) -> None:
    """CAIRN'S CATCH (#896), ruled at #902, and the reason the key is not
    called `charter_version`.

    The slot reports the version THIS BOARD'S BUILD ships. The reader was
    oriented by a client that resolves its fragment once at construction and
    may be many versions behind — seven, measured on 2026-08-11 by the desk
    about itself. An unqualified `charter_version` would have this
    document — the authoritative-looking one, read by the band least able to
    check — certify the staleness it exists to refuse.
    """
    truth = served(world)["minute_zero"]["where_truth_lives"]
    assert "charter_version" not in truth, (
        "an unqualified version key makes a claim about the reader's "
        "orientation that this board cannot support"
    )
    assert truth["charter_version_this_board_ships"] == CHARTER_VERSION
    assert "your own client" in truth["note"]


def test_truth_is_computed_from_the_log_at_this_offset(world: dict) -> None:
    board = world["board"]
    truth = served(world)["minute_zero"]["where_truth_lives"]
    assert truth["head"] == board.head
    assert truth["canon_in_force"], "a seeded board has canon"


def test_every_step_is_executable_and_verifies_itself(world: dict) -> None:
    """#453: executable, not descriptive. A step without a command is a
    paragraph, and a command without a check is an instruction you cannot
    tell you followed wrongly."""
    for step in served(world)["minute_zero"]["do_this_now"]:
        assert step["run"].startswith("korax "), step
        assert step["verifies"].strip(), step
        assert step["why"].strip(), step


def test_the_charter_build_is_current() -> None:
    """#702's half that a machine can own, and the enforcement that makes
    `do not edit by hand` mean something.

    The fragment BODIES are hand-written compressions and always will be —
    a script cannot write editorial work. The VERSION is what actually
    drifted: it went unenforced through six bumps while the README sat at
    1.0.0 and the charter reached 1.6.0. This fails if the tree disagrees
    with what `tools/charter_build.py` produces.
    """
    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "charter_build.py"), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"charter artifacts are stale:\n{result.stderr}"
        "\nrun `python tools/charter_build.py`"
    )
