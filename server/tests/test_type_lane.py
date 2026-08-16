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


def test_the_stamp_names_tree_sha_and_working_state() -> None:
    """The three things #2379 ruled it must print."""
    text = lane.stamp()
    assert "korax tree:" in text
    assert "sha: " in text
    assert "working tree: " in text


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


# ── dirty state tells the truth, in both directions ───────────────────


def test_a_dirty_tree_reports_DIRTY_with_a_count(monkeypatch) -> None:
    """THE CANARY. #2378's constraint, adopted as the acceptance floor:
    a stamp naming a clean sha over a dirty tree is a worse lie than no
    stamp."""
    monkeypatch.setattr(lane, "_git", lambda *a: (0, " M server/korax/api.py\n?? new.py"))
    is_dirty, count, rendered = lane.dirty_state()
    assert is_dirty is True
    assert count == 2
    assert rendered == "DIRTY (2 files)"


def test_a_clean_tree_reports_CLEAN__control(monkeypatch) -> None:
    """THE CONTROL. A detector that always said DIRTY would pass the
    canary above and destroy the signal — nobody would read a stamp that
    is always the same."""
    monkeypatch.setattr(lane, "_git", lambda *a: (0, ""))
    is_dirty, count, rendered = lane.dirty_state()
    assert is_dirty is False
    assert count == 0
    assert rendered == "CLEAN"


def test_one_dirty_file_is_singular(monkeypatch) -> None:
    monkeypatch.setattr(lane, "_git", lambda *a: (0, " M one.py"))
    assert lane.dirty_state()[2] == "DIRTY (1 file)"


def test_an_unreadable_tree_state_FAILS_CLOSED(monkeypatch) -> None:
    """A tree whose state cannot be read is reported dirty, never clean.
    Failing open would print CLEAN beside a sha on a tree nobody
    measured — the precise lie this tool exists to remove."""
    monkeypatch.setattr(lane, "_git", lambda *a: (128, ""))
    is_dirty, _count, rendered = lane.dirty_state()
    assert is_dirty is True
    assert "UNKNOWN" in rendered


# ── the sha never renders as a plausible blank ────────────────────────


def test_an_unavailable_sha_says_so_rather_than_emitting_nothing(monkeypatch) -> None:
    """`sha: ` with nothing after it reads as a stamp that was made and
    found nothing — #2183 family A, in the tool written against it."""
    monkeypatch.setattr(lane, "_git", lambda *a: (128, ""))
    assert "UNKNOWN" in lane.revision()


def test_a_real_sha_is_returned_when_git_answers__control(monkeypatch) -> None:
    monkeypatch.setattr(lane, "_git", lambda *a: (0, "e733856311d4"))
    assert lane.revision() == "e733856311d4"


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
    assert out.index("korax tree:") < out.index("sha: ") < out.index("working tree: ")
