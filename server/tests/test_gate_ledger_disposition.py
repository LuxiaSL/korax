"""`tools/gate.sh` leg 11 — the ledger-disposition guard. JOB #2682,
cut from the mill's own routing at #2680.

**WHY THIS SOURCES gate.sh RATHER THAN REIMPLEMENTING ITS LOGIC.** The
acceptance in #2682's brief is explicit: the leg must fire before it is
believed, "via real gate.sh invocations against fixture commits, not a
re-implementation of the leg's logic" (#2668's canary rule). The
disposition decision here is four cases over two signals, one of them a
contradiction — complex enough that a Python reimplementation could
silently agree with a bug in the real one. So every test below sources
`tools/gate.sh` (guarded so `main` does not fire — see the file's own
comment above that guard) and calls its three ledger-disposition
primitives directly, against real git history in a planted throwaway
repo. Nothing here restates the entry-added regex, the trailer regex,
or the owed predicate; the only Python-side logic is building fixture
commits.

**WHY THE PRIMITIVES AND NOT THE FULL LEG WRAPPER.** `run_ledger_disposition_leg`
reads `$REPO_ROOT`/`$TARGET_SHA`/`$BASE_REF`, which are this repo's own
globals — `REPO_ROOT` is `readonly`, fixed to wherever gate.sh actually
lives, so it cannot be redirected at a fixture repo without changing
gate.sh's own call sites for testability alone. The three primitives
this file exercises are parameterized precisely so they can be — the
same shape the existing `browser_is_owed`-adjacent tests already use
for the browser predicate, just carried one step further because that
predicate reimplements a single `git diff --name-only` while this one
cannot be reimplemented without reproducing the check.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "tools" / "gate.sh"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _mkrepo(root: Path) -> Path:
    """A throwaway repo with a real docs/korax-revisions.md and one
    non-docs file, so the leg's git plumbing runs against real history
    rather than a directory with no commits to diff."""
    repo = root / "ledger-repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "docs" / "korax-revisions.md").write_text(
        "# Revisions\n\n## R1 — the beginning\n\nsome text\n"
    )
    (repo / "src" / "app.py").write_text("baseline\n")
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "canary@example.invalid")
    _git(repo, "config", "user.name", "canary")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "baseline")
    return repo


def _run(func: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Source gate.sh (main does not fire — see the sourcing guard at
    the bottom of the file) and call one of its own functions, in a
    real bash process. This is the "real invocation" the brief asks
    for: the exact bytes shipping in gate.sh, not a restatement."""
    script = f'source "{GATE}"\n{func} "$@"\n'
    return subprocess.run(
        ["bash", "-c", script, func, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _owed(repo: Path, base: str, target: str) -> bool:
    return _run("ledger_disposition_is_owed", str(repo), base, target).returncode == 0


def _entry_added(repo: Path, base: str, target: str) -> bool:
    return (
        _run("ledger_disposition_entry_added", str(repo), base, target).returncode
        == 0
    )


def _trailer_present(repo: Path, base: str, target: str) -> bool:
    return (
        _run("ledger_disposition_trailer_present", str(repo), base, target).returncode
        == 0
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return _mkrepo(tmp_path)


# ── the sourcing guard itself ──────────────────────────────────────────


def test_gate_sh_can_be_sourced_without_running_main() -> None:
    """If this regresses, every test below hangs or runs the full
    battery instead of the one leg being tested."""
    proc = subprocess.run(
        ["bash", "-c", f'source "{GATE}"; echo SOURCED_OK'],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    assert "SOURCED_OK" in proc.stdout
    assert "running" not in proc.stderr, (
        "sourcing ran the battery — main() is not properly guarded"
    )


# ── the four fixture quadrants (#2682's acceptance) ────────────────────
# code+no entry+no trailer red; code+entry green; code+trailer green;
# code+both red. Watched here, not asserted from memory.


def test_owed_with_no_entry_and_no_trailer_is_the_214a776_shape(repo: Path) -> None:
    """Quadrant 1: RED. This is the live instance the leg exists for —
    `214a776` shipped code with zero ledger entries and nine green
    tests (#2671/#2673)."""
    base = _head(repo)
    (repo / "src" / "app.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "code change, no ledger entry")
    target = _head(repo)

    assert _owed(repo, base, target)
    assert not _entry_added(repo, base, target)
    assert not _trailer_present(repo, base, target)


def test_owed_with_an_added_entry_is_green(repo: Path) -> None:
    """Quadrant 2: GREEN. The normal case — a delivery that owes an
    entry and carries one."""
    base = _head(repo)
    (repo / "src" / "app.py").write_text("changed\n")
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R-NEXT — a fixture entry\n\nfixture\n")
    _git(repo, "commit", "-qam", "code change with ledger entry")
    target = _head(repo)

    assert _owed(repo, base, target)
    assert _entry_added(repo, base, target)
    assert not _trailer_present(repo, base, target)


def test_owed_with_a_ledger_none_trailer_is_green(repo: Path) -> None:
    """Quadrant 3: GREEN. The #2550 escape — a tightening repair that
    legitimately owes no entry states so in the artifact."""
    base = _head(repo)
    (repo / "src" / "app.py").write_text("changed\n")
    msg = "tightening repair\n\nLedger: none — pure tightening, #2550 criterion\n"
    _git(repo, "commit", "-qam", msg)
    target = _head(repo)

    assert _owed(repo, base, target)
    assert not _entry_added(repo, base, target)
    assert _trailer_present(repo, base, target)


def test_owed_with_both_entry_and_trailer_is_red_as_a_contradiction(
    repo: Path,
) -> None:
    """Quadrant 4: RED. Neither signal is itself the defect; a stated
    'none' alongside a real entry is a contradiction and reds
    identically to neither being present (#2682 ruling 3)."""
    base = _head(repo)
    (repo / "src" / "app.py").write_text("changed\n")
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R-NEXT — a fixture entry\n\nfixture\n")
    _git(repo, "add", "-A")
    msg = "contradictory delivery\n\nLedger: none — should not both be true\n"
    _git(repo, "commit", "-qm", msg)
    target = _head(repo)

    assert _owed(repo, base, target)
    assert _entry_added(repo, base, target)
    assert _trailer_present(repo, base, target)


# ── owed-ness itself, both directions (#112) ───────────────────────────


def test_a_doc_only_diff_is_not_owed(repo: Path) -> None:
    """A delivery touching nothing outside docs/ is not-owed — the leg
    must report SKIPPED, never run a disposition check that has nothing
    to be a disposition about."""
    base = _head(repo)
    (repo / "docs" / "korax-revisions.md").write_text("# Revisions\n\n## R1 — edited\n")
    _git(repo, "commit", "-qam", "docs only")
    target = _head(repo)

    assert not _owed(repo, base, target)


def test_an_empty_diff_is_not_owed(repo: Path) -> None:
    base = _head(repo)
    assert not _owed(repo, base, base)


# ── the entry must arrive, not be inherited (#2688's sharpening) ───────


def test_an_inherited_r_next_heading_does_not_count_as_added(repo: Path) -> None:
    """The desk's own sharpening on #2687's readback (#2688): "a branch
    that merely inherits main's existing headings has brought nothing" —
    the entry must ARRIVE in base..target, so a base that already
    carries the heading must not let an unrelated later change read it
    as its own disposition."""
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R-NEXT — inherited from a sibling\n\nnot mine\n")
    _git(repo, "commit", "-qam", "sibling lands an R-NEXT heading first")
    base = _head(repo)  # base ALREADY carries the heading

    (repo / "src" / "app.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "unrelated code change, inherits the heading")
    target = _head(repo)

    assert _owed(repo, base, target)
    assert not _entry_added(repo, base, target), (
        "an R-NEXT heading already present at base must not count as ADDED "
        "by a branch that never touched it — the FAIL this fixture would "
        "otherwise hide is exactly the 214a776 shape wearing a disguise"
    )


# ── the trailer pattern matches what it must, and only that ────────────


def test_the_trailer_pattern_requires_the_literal_key_and_value(repo: Path) -> None:
    """`Ledger: none` must anchor the line start — a prose sentence that
    happens to contain the words must not fire."""
    base = _head(repo)
    (repo / "src" / "app.py").write_text("changed\n")
    msg = "code change\n\nSaw the Ledger: none of this made sense to skip.\n"
    _git(repo, "commit", "-qam", msg)
    target = _head(repo)

    assert not _trailer_present(repo, base, target), (
        "a sentence mentioning 'Ledger: none' mid-prose is not a trailer "
        "declaration and must not be read as one"
    )


def test_the_trailer_fires_from_any_commit_in_the_range_not_only_head(
    repo: Path,
) -> None:
    """A multi-commit delivery's trailer can sit on an earlier commit
    than target — the range is scanned whole, not just HEAD's message."""
    base = _head(repo)
    _git(repo, "commit", "--allow-empty", "-qm",
         "Ledger: none — the escape, on an early commit")
    (repo / "src" / "app.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "the actual code change, no trailer here")
    target = _head(repo)

    assert _owed(repo, base, target)
    assert _trailer_present(repo, base, target)


# ── declaration-level bookkeeping (M moves, #2682 ruling 4) ────────────


def test_ledger_disposition_is_declared_as_the_eleventh_leg() -> None:
    text = GATE.read_text(encoding="utf-8")
    import re

    match = re.search(r"^readonly LEG_NAMES=\(\n(.*?)^\)$", text, re.M | re.S)
    assert match, "LEG_NAMES is not declared as a readonly array"
    legs = [
        line.strip()
        for line in match.group(1).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(legs) == 11, f"expected 11 declared legs, found {len(legs)}: {legs}"
    assert legs[-1] == "ledger-disposition", (
        "ledger-disposition should be the newly-added, eleventh leg"
    )


def test_ledger_disposition_leg_is_wired_into_the_battery() -> None:
    text = GATE.read_text(encoding="utf-8")
    assert "run_ledger_disposition_leg" in text
    assert text.count("run_ledger_disposition_leg") >= 2, (
        "the function must be both defined and called from run_battery"
    )


def test_the_skip_paths_are_distinguishable_from_not_owed() -> None:
    """No-base and unresolvable-base are a different failure mode than
    'diff touches only docs/' — a builder reading a skip reason should
    never have to guess which of the three applies."""
    text = GATE.read_text(encoding="utf-8")
    assert "no --base given" in text
    assert "not owed" in text


def test_the_report_names_ten_invocations() -> None:
    """The lane is one command for two legs (ruff+mypy); ledger-
    disposition is its own command — nine become ten."""
    report = GATE.read_text(encoding="utf-8").split("report()")[-1]
    assert "10 invocations" in report
