"""`tools/gate.sh` `cleanup()` — ISSUE #2756: the one run whose evidence
you need is the only run that discarded it.

The first cut of `cleanup()` deleted the whole SCRATCH tree (worktree
AND logs) unconditionally on every exit, pass or fail. On a red leg
the claimant is left with a one-line count and no name for which test
failed — the only recovery was re-running the whole ten-leg battery
with `--keep` and hoping the flake reproduced.

**WHY THIS SOURCES gate.sh RATHER THAN REIMPLEMENTING `cleanup()`'s
LOGIC.** Same reasoning as `test_gate_ledger_disposition.py`: the
retention decision reads `$?` at a specific point in a specific order
relative to `reap_legs`, which is exactly the kind of ordering defect
a Python reimplementation could silently agree with. Every test below
sources `tools/gate.sh` (guarded so `main` does not fire) and calls
`cleanup` directly against a planted SCRATCH tree, in a real bash
process — the exact bytes shipping in gate.sh, not a restatement.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# korax: needs-git-history — test_the_worktree_goes_regardless_of_outcome
# below runs `git worktree add/remove/prune` against the real repository
# root (`cwd=REPO`), not a planted fixture repo (#2831, part a).

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "tools" / "gate.sh"


def _run_cleanup(scratch: Path, exit_before: str, keep: str = "0") -> subprocess.CompletedProcess[str]:
    """Source gate.sh, plant SCRATCH/WT/LOGDIR/KEEP exactly as
    `cleanup()` reads them, run one command to set `$?` to a chosen
    value, then call `cleanup` — precisely what the EXIT trap hands it.
    `WT` is left pointing at a path that does not exist, so the git
    worktree-removal branch is a no-op and this stays scoped to the
    retention decision alone."""
    script = f'''
source "{GATE}"
SCRATCH="{scratch}"
WT="{scratch}/wt-does-not-exist"
LOGDIR="{scratch}/logs"
KEEP={keep}
{exit_before}
cleanup
'''
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, check=False,
    )


@pytest.fixture()
def scratch(tmp_path: Path) -> Path:
    root = tmp_path / "korax-gate-fixture"
    (root / "logs").mkdir(parents=True)
    (root / "logs" / "browser.log").write_text(
        "FAIL (rc=1)\n1 failed, 7 passed, 895 deselected\n"
        "FAILED tests/test_perch_forum_s4_browser.py::test_home_profile_and_the_gate\n"
    )
    return root


# ── the defect, red-first ────────────────────────────────────────────


def test_a_failed_gate_retains_its_logs(scratch: Path) -> None:
    """The instance #2756 was filed over: a red leg's log must survive
    the same run that produced it."""
    result = _run_cleanup(scratch, "false")  # $? = 1 entering cleanup

    assert scratch.exists(), (
        "cleanup() deleted SCRATCH after a non-zero exit — the exact "
        f"defect #2756 reports (stderr: {result.stderr!r})"
    )
    assert (scratch / "logs" / "browser.log").exists()
    assert "retained" in result.stderr, (
        "the retained path must be named in the output — an unreported "
        "retained directory is a leak (#2756's own framing)"
    )
    assert str(scratch) in result.stderr


def test_a_clean_gate_still_deletes_its_scratch(scratch: Path) -> None:
    """The other direction matters as much as the first: retention that
    fires on every run is not retention, it is the 122 MB leak #2727
    measured, wearing the fix's clothes."""
    result = _run_cleanup(scratch, "true")  # $? = 0 entering cleanup

    assert not scratch.exists(), (
        f"cleanup() retained SCRATCH after a clean exit (stderr: {result.stderr!r})"
    )


def test_missing_leg_status_also_retains(scratch: Path) -> None:
    """`main`'s own tail returns 1 for FAIL **or** MISSING — a leg that
    never ran is not distinguishable from success by `$?`, and this
    reuses that exact predicate rather than re-deriving it, so a
    MISSING leg's non-zero exit retains the logs too."""
    result = _run_cleanup(scratch, "( exit 1 )")

    assert scratch.exists()
    assert "retained" in result.stderr


def test_keep_flag_still_retains_everything_unconditionally(scratch: Path) -> None:
    """`--keep` is the pre-existing, unconditional escape and must not
    regress: it retains SCRATCH on a CLEAN exit too, which the new
    non-zero-exit predicate alone would not."""
    result = _run_cleanup(scratch, "true", keep="1")

    assert scratch.exists(), f"--keep no longer retains on a clean exit (stderr: {result.stderr!r})"


def test_the_worktree_goes_regardless_of_outcome(tmp_path: Path) -> None:
    """The worktree is reconstructible from a sha and is not the thing
    #2756 is about — it must still be removed on a red run, only the
    logs are retained."""
    scratch = tmp_path / "korax-gate-fixture"
    (scratch / "logs").mkdir(parents=True)
    wt = scratch / "wt"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt), "HEAD"],
        cwd=REPO, check=True, capture_output=True,
    )
    try:
        script = f'''
source "{GATE}"
SCRATCH="{scratch}"
WT="{wt}"
LOGDIR="{scratch}/logs"
KEEP=0
false
cleanup
'''
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=False,
        )
        assert not wt.exists(), (
            f"the worktree survived a FAILed cleanup — it should always be "
            f"removed, only the logs are retained (stderr: {result.stderr!r})"
        )
        assert scratch.exists(), "the logs must still be retained alongside the worktree removal"
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt)],
            cwd=REPO, check=False, capture_output=True,
        )
        subprocess.run(["git", "worktree", "prune"], cwd=REPO, check=False, capture_output=True)
