"""The type lane says what it ran against — ISSUE #2378, ruled #2379.

Sited beside `test_tree_guard.py` because `tools/type_lane.py` is that
tool's near neighbour: both are `tools/` modules whose subject is the
provenance of a result rather than the result, and this one imports the
other for its `korax tree:` line.

**Every canary here has its control**, because the failures this tool
exists to catch are the ones that look like success — a stamp that is
always DIRTY, a wrapper that always exits 0, a provenance block that
appears only when nothing is wrong. This band has shipped canaries
without their control row twice (#993, #1009) and the gate has checked
for the neighbour since.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "type_lane.py"


def _lane():
    spec = importlib.util.spec_from_file_location("korax_type_lane_test", TOOLS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lane = _lane()


# ── the stamp is present, and present when it is least convenient ─────


def test_the_stamp_still_names_a_TREE_and_a_SHA_after_the_deletion() -> None:
    """THE CANARY FOR #2491, and the only assertion that separates this
    change from #2378 reintroduced.

    The whole risk of deleting the lane's own `sha:` line is that the
    block silently stops naming a revision — which a green suite is the
    *worst* possible evidence against, because every test of a deleted
    line passes hardest once the line is gone. `header()` has carried
    `HEAD <sha>` since R138, so the property survives the deletion; this
    asserts it rather than trusting the ordering that made it true.
    """
    text = lane.stamp()
    assert "korax tree:" in text
    assert "HEAD " in text, (
        "the stamp names no revision — deleting this file's sha line "
        "before R138 landed is exactly #2378, rebuilt by its own fix"
    )


def test_the_lane_no_longer_prints_its_OWN_sha_line__the_other_direction() -> None:
    """THE CONTROL for the canary above. Without it the canary passes
    while both lines are still there — which was the defect (#2483: one
    block, two independent computations, divergent on an unreadable
    git). Asserting the absence is what makes the deletion checkable."""
    text = lane.stamp()
    assert "sha: " not in text
    assert "working tree: " not in text


def test_the_tree_line_is_byte_identical_to_the_suites() -> None:
    """Reused from `tree_guard`, not reimplemented — so one grep finds the
    lane's provenance and a suite's, and the toolkit's 'QUOTE that line'
    instruction means the same thing in both places."""
    guard = lane._tree_guard()
    assert guard.header(lane.TREE, lane.PACKAGES) in lane.stamp()


def test_the_stamp_prints_even_when_the_checks_FAIL(monkeypatch, capsys) -> None:
    """THE CANARY THAT MATTERS. A stamp that appeared only on success
    would be missing from every transcript where provenance is actually
    disputed — which is exactly the transcripts a gate reads."""
    monkeypatch.setattr(lane, "run_checks", lambda: [("ruff", 1), ("mypy", 0)])
    rc = lane.main([])
    assert rc == 1
    assert "korax tree:" in capsys.readouterr().out


def test_the_stamp_prints_when_the_checks_pass__control(monkeypatch, capsys) -> None:
    """THE CONTROL. Without it, a tool that printed the stamp
    unconditionally-and-then-crashed would still pass the canary above."""
    monkeypatch.setattr(lane, "run_checks", lambda: [("ruff", 0), ("mypy", 0)])
    rc = lane.main([])
    assert rc == 0
    assert "korax tree:" in capsys.readouterr().out


# ── the exit code IS the tools' exit code ─────────────────────────────


def test_a_failing_check_exits_nonzero_THROUGH_the_wrapper(monkeypatch) -> None:
    """THE CANARY. A wrapper that swallowed a nonzero rc would rebuild
    #2085's pipe-swallows-the-exit-code defect inside the lane built to
    prevent it — and it would fail GREEN, the direction that does not
    announce itself."""
    monkeypatch.setattr(lane, "run_checks", lambda: [("ruff", 0), ("mypy", 1)])
    assert lane.main([]) == 1


def test_a_clean_run_exits_zero__control(monkeypatch) -> None:
    """THE CONTROL. A wrapper that always exited nonzero would pass the
    canary above while making the lane unusable."""
    monkeypatch.setattr(lane, "run_checks", lambda: [("ruff", 0), ("mypy", 0)])
    assert lane.main([]) == 0


def test_both_checks_run_even_when_the_first_fails() -> None:
    """No short-circuit: a claimant who fixes ruff and re-runs should not
    then discover mypy on a third attempt. Asserted by counting the
    invocations, not by reading the code."""
    seen: list[tuple[str, ...]] = []

    def fake_run(argv, cwd=None, check=False):
        seen.append(tuple(argv))
        return SimpleNamespace(returncode=1)

    results = lane.run_checks(runner=fake_run)
    assert len(seen) == len(lane.CHECKS) == 2
    assert [name for name, _rc in results] == ["ruff", "mypy"]


# ── dirty state and the sha: NOT TESTED HERE ANY MORE, ON PURPOSE ─────
#
# Six tests stood here — DIRTY-with-a-count, its CLEAN control, the
# singular-file case, fails-closed-on-unreadable-git, and the two over
# `revision()`. They went with `dirty_state()` and `revision()` at
# #2491, because this file no longer computes either.
#
# **The properties did not go with them.** They live in
# `test_tree_guard.py` against `header()`, which is now the single
# computation — and slate's version is stronger than the one deleted
# here: an unreadable git reports UNKNOWN rather than asserting DIRTY,
# since "dirty" is a fact nobody has (#2448). Deleting a test whose
# subject moved is correct; deleting one whose property simply stops
# being checked is how coverage evaporates silently, so this note names
# where each went rather than leaving a gap that reads as a decision.


# ── the whole thing, driven as a subprocess, the way CI runs it ───────


def test_end_to_end_the_wrapper_prints_the_stamp_before_the_checks() -> None:
    """`--stamp-only` so the test costs no checker run: this asserts the
    wiring and the ordering, not the checkers' verdicts."""
    proc = subprocess.run(
        [sys.executable, str(TOOLS), "--stamp-only"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "korax tree:" in out
    # THE END-TO-END FORM OF THE DELETION CANARY. This line used to
    # assert the ORDER `korax tree:` < `sha: ` < `working tree: ` — an
    # assertion that names neither `revision()` nor `dirty_state()`, so
    # a symbol-grep for the deleted functions never finds it and it
    # fails from a subprocess with no obvious cause (#2491). Recorded
    # because the next person deleting a rendered line will grep for
    # the function, not the string.
    assert "HEAD " in out, "the lane's real output names no revision"
    assert "sha: " not in out
