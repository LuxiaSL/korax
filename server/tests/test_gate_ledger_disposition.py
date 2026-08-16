"""`tools/gate.sh` leg 11 — the ledger-disposition guard. JOB #2682,
cut from the mill's own routing at #2680; repaired same-loop after
#2777's WARN (leg 11 reddened every correct merge target) and #2782's
finding (the first fix had its own base-staleness hole), ruled at
#2783.

**WHY THIS SOURCES gate.sh RATHER THAN REIMPLEMENTING ITS LOGIC.** The
acceptance in #2682's brief is explicit: the leg must fire before it is
believed, "via real gate.sh invocations against fixture commits, not a
re-implementation of the leg's logic" (#2668's canary rule). The
disposition decision here is four cases over two signals, one of them a
contradiction — complex enough that a Python reimplementation could
silently agree with a bug in the real one. So every test below sources
`tools/gate.sh` (guarded so `main` does not fire — see the file's own
comment above that guard) and calls its ledger-disposition primitives
directly, against real git history in a planted throwaway repo. Nothing
here restates the entry-added regex, the trailer regex, or the owed
predicate; the only Python-side logic is building fixture commits.

**WHY THE PRIMITIVES AND NOT THE FULL LEG WRAPPER.** `run_ledger_disposition_leg`
reads `$REPO_ROOT`/`$TARGET_SHA`/`$BASE_REF`, which are this repo's own
globals — `REPO_ROOT` is `readonly`, fixed to wherever gate.sh actually
lives, so it cannot be redirected at a fixture repo without changing
gate.sh's own call sites for testability alone. The primitives this
file exercises are parameterized precisely so they can be.

**WHY entry_added/trailer_present TAKE TARGET ONLY, NOT BASE.** #2782
found that base-relative diffing sweeps unrelated intervening revisions
into scope whenever the caller's `--base` is more than one revision
behind target — a delivery bringing no entry of its own could then read
"entry added" by inheriting somebody else's, which is the exact
vacuity leg 11 exists to prevent. The ruled fix (#2783) asks about
target's own first-parent diff instead, which is base-independent by
construction. `owed()` is unaffected and keeps taking base — its
failure direction (over-triggering from a stale base) is safe, matching
`browser_is_owed`'s existing convention, so it did not need to move.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# korax: needs-git-history — `test_entry_added_was_red_on_the_real_unfixed_
# gate_sh_where_history_exists` reads `52f0261` out of the real repository.
# It probes with `cat-file -e` first and SKIPS BY NAME where that sha is
# unreachable, which is the shallow-safe shape: running it inside the
# shallow leg's depth-1 clone is expected to produce that named skip, and
# the leg reports it as `declared, skipped by name` — evidence the guard
# fires, not an absence.
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
    # `-b main` EXPLICIT (#2817): `git init`'s default branch name comes
    # from `init.defaultBranch`, which is `main` on some hosts and
    # `master` on others (CI's runner is `master`) — a fixture that
    # relies on the ambient default is environment-dependent by
    # construction and was invisible to every band who develops on a
    # host configured `main`.
    _git(repo, "init", "-q", "-b", "main", ".")
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


def _entry_added(repo: Path, target: str) -> bool:
    return _run("ledger_disposition_entry_added", str(repo), target).returncode == 0


def _trailer_present(repo: Path, target: str) -> bool:
    return (
        _run("ledger_disposition_trailer_present", str(repo), target).returncode == 0
    )


def _parent_count(repo: Path, target: str) -> int:
    return int(_run("ledger_disposition_parent_count", str(repo), target).stdout.strip())


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
# code+both red. Each of these builds exactly ONE commit from base to
# target, so target^1 == base here and the fixtures exercise the same
# shape as a real single-commit delivery, merge or direct.


def test_owed_with_no_entry_and_no_trailer_is_the_214a776_shape(repo: Path) -> None:
    """Quadrant 1: RED. This is the live instance the leg exists for —
    `214a776` shipped code with zero ledger entries and nine green
    tests (#2671/#2673)."""
    base = _head(repo)
    (repo / "src" / "app.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "code change, no ledger entry")
    target = _head(repo)

    assert _owed(repo, base, target)
    assert not _entry_added(repo, target)
    assert not _trailer_present(repo, target)


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
    assert _entry_added(repo, target)
    assert not _trailer_present(repo, target)


def test_owed_with_a_ledger_none_trailer_is_green(repo: Path) -> None:
    """Quadrant 3: GREEN. The #2550 escape — a tightening repair that
    legitimately owes no entry states so in the artifact."""
    base = _head(repo)
    (repo / "src" / "app.py").write_text("changed\n")
    msg = "tightening repair\n\nLedger: none — pure tightening, #2550 criterion\n"
    _git(repo, "commit", "-qam", msg)
    target = _head(repo)

    assert _owed(repo, base, target)
    assert not _entry_added(repo, target)
    assert _trailer_present(repo, target)


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
    assert _entry_added(repo, target)
    assert _trailer_present(repo, target)


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
    the entry must ARRIVE in target^1..target, so a heading already
    present at target's own parent must not read as this delivery's."""
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R-NEXT — inherited from a sibling\n\nnot mine\n")
    _git(repo, "commit", "-qam", "sibling lands an R-NEXT heading first")

    (repo / "src" / "app.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "unrelated code change, inherits the heading")
    target = _head(repo)

    assert not _entry_added(repo, target), (
        "an R-NEXT heading already present at target^1 must not count as "
        "ADDED by a commit that never touched it — the FAIL this fixture "
        "would otherwise hide is exactly the 214a776 shape wearing a "
        "disguise"
    )


# ── both spellings of "an entry arrived" (#2777's WARN, ruled #2779) ───
# `entry_added` only recognised `## R-NEXT`, so it reddened every merge
# on this board: by the time a merge target exists the desk has already
# substituted the number, so the added line reads `## R150`, not
# `## R-NEXT`. Measured on four real merges the same night (R149-R152).


def test_entry_added_recognises_a_merge_target_numbered_heading(repo: Path) -> None:
    """The merge-target shape, constructed for real rather than assumed:
    target's own parent has no heading, target's diff adds `## R150`
    directly — exactly what a real desk merge's first-parent diff
    shows."""
    (repo / "src" / "app.py").write_text("changed\n")
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R150 — a fixture entry, already numbered\n\nfixture\n")
    _git(repo, "commit", "-qam", "simulates a desk merge: the heading arrives numbered")
    target = _head(repo)

    assert _entry_added(repo, target), (
        "a heading added as ## R<N> is exactly as much 'an entry arrived' "
        "as one added as ## R-NEXT — only the mode differs"
    )


# #2817's diagnosis, cause 1: `git show 52f0261:tools/gate.sh` needs
# 52f0261 reachable, which a depth-1 CI checkout does not have (#2409,
# again). The PRE-FIX function is planted here as a literal string — a
# fixture that keeps its meaning in a shallow clone, per the desk's
# ruled hybrid (#2818) — and the git-history read below is kept as an
# ADDITIONAL, declared-skip-on-absence assertion: the strongest form of
# red-first (reproduced from the actual shipped bytes) wherever history
# is available, never a silent gap where it is not.
_PRE_FIX_ENTRY_ADDED = '''
ledger_disposition_entry_added() {
  local repo="$1" base_sha="$2" target_sha="$3"
  git -C "$repo" diff "$base_sha" "$target_sha" -- docs/korax-revisions.md 2>/dev/null \\
    | grep -qE '^\\+##[[:space:]]+R-NEXT\\b'
}
'''


def test_entry_added_was_red_on_the_pre_fix_function(repo: Path) -> None:
    """Red-first against the pre-fix `entry_added`, planted as a fixture
    so this runs identically in a shallow CI clone: the R151 shape
    (`R-NEXT` only) must MISS a numbered heading, which is the exact
    defect #2777 found and this delivery fixes."""
    old_script = repo.parent / "pre-fix-entry-added.sh"
    old_script.write_text(_PRE_FIX_ENTRY_ADDED)

    base = _head(repo)
    (repo / "src" / "app.py").write_text("changed\n")
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R150 — a fixture entry, already numbered\n\nfixture\n")
    _git(repo, "commit", "-qam", "simulates a desk merge: the heading arrives numbered")
    target = _head(repo)

    proc = subprocess.run(
        ["bash", "-c",
         f'source "{old_script}"\nledger_disposition_entry_added "$@"',
         "ledger_disposition_entry_added", str(repo), base, target],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode != 0, (
        "the planted PRE-FIX function was expected to MISS a numbered "
        "heading — if it now matches, the planted fixture no longer "
        "represents the R151 shape this test documents"
    )


def test_entry_added_was_red_on_the_real_unfixed_gate_sh_where_history_exists(
    repo: Path,
) -> None:
    """The stronger form of the test above: reproduced from the ACTUAL
    shipped bytes at R151 (`52f0261`) via a real `git show`, not a
    hand-copied string — but only where that history is reachable.
    `actions/checkout@v4` clones at depth 1, so `52f0261` does not exist
    in CI's checkout (#2409); this declares a SKIP by name there rather
    than failing on an environment gap or silently passing on nothing
    (#2682's principle), and runs for real in any full clone, including
    every local dev run."""
    probe = subprocess.run(
        ["git", "cat-file", "-e", "52f0261"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    if probe.returncode != 0:
        pytest.skip(
            "52f0261 is not reachable in this checkout (shallow clone, "
            "e.g. CI's actions/checkout@v4 at depth 1, #2409) — see the "
            "planted-fixture form of this test for the shallow-safe "
            "coverage"
        )

    old_gate = subprocess.run(
        ["git", "show", "52f0261:tools/gate.sh"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    old_script = repo.parent / "old-gate.sh"
    old_script.write_text(old_gate)

    base = _head(repo)
    (repo / "src" / "app.py").write_text("changed\n")
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R150 — a fixture entry, already numbered\n\nfixture\n")
    _git(repo, "commit", "-qam", "simulates a desk merge: the heading arrives numbered")
    target = _head(repo)

    proc = subprocess.run(
        ["bash", "-c",
         f'source "{old_script}"\nledger_disposition_entry_added "$@"',
         "ledger_disposition_entry_added", str(repo), base, target],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode != 0, (
        "the OLD gate.sh (R151, 52f0261) was expected to MISS a numbered "
        "heading — if it now matches, either the fixture is wrong or "
        "52f0261 is no longer the pre-fix commit this test thinks it is"
    )


def test_a_branch_that_self_numbers_correctly_is_indistinguishable_from_a_merge(
    repo: Path,
) -> None:
    """The desk's third ask (#2779): does the widened regex let a branch
    dodge the R-NEXT convention by writing its own number? **Yes, and by
    design it cannot do otherwise** — target^1..target is a TREE diff,
    so 'the desk substituted R-NEXT to R150' and 'the claimant wrote
    ## R150 directly' produce the IDENTICAL diff. Correctness of the
    NUMBER ITSELF — collision with an existing heading, or a gap in the
    1..max sequence — is `test_revisions_ledger.py`'s job (label
    uniqueness, integer-set-complete), not this leg's. The seam: leg 11
    answers 'did an entry arrive', the ledger suite answers 'is the
    ledger internally consistent', and neither substitutes for the
    other."""
    (repo / "src" / "app.py").write_text("changed\n")
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R2 — a claimant-numbered heading, not desk-substituted\n\nfixture\n")
    _git(repo, "commit", "-qam", "a branch writes its own number instead of R-NEXT")
    target = _head(repo)

    assert _entry_added(repo, target), (
        "leg 11 reads this as 'an entry arrived', correctly — whether the "
        "number is right is a different guard's question"
    )


# ── base-independence: the vacuity #2782 found before it shipped ───────


def test_entry_added_ignores_an_unrelated_heading_two_revisions_back(
    repo: Path,
) -> None:
    """#2782's finding, reproduced on a planted fixture rather than only
    cited from real history: gate an R152-shaped target whose CALLER
    passes a base two merges back. A base-relative check would sweep in
    R151's heading too and read green for a delivery that added
    nothing. entry_added must answer only from target^1, never from
    whatever --base happened to be supplied."""
    stale_base = _head(repo)  # what a caller might mistakenly pass as --base

    # "R151": a prior, unrelated merge landing its own entry
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R151 — an unrelated prior merge\n\nfixture\n")
    _git(repo, "commit", "-qam", "R151 lands")

    # "R152": THIS delivery, code-only, no entry of its own
    (repo / "src" / "app.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "R152's own commit, no ledger entry")
    target = _head(repo)

    # the base-relative predicate WOULD see R151's heading in scope —
    # confirming the fixture actually recreates the hazard, not just
    # asserting the fix in isolation
    diff = _git(repo, "diff", stale_base, target, "--", "docs/korax-revisions.md").stdout
    assert "+## R151" in diff, "fixture setup failed to recreate the hazard"

    assert _owed(repo, stale_base, target)
    assert not _entry_added(repo, target), (
        "entry_added must be blind to the stale base's extra history — "
        "R152's own commit added nothing, and base-independence is what "
        "keeps that true regardless of what --base a caller supplies"
    )


# ── parent-count precondition (#2783 ruling 2) ──────────────────────────


def test_parent_count_reads_zero_two_and_three_correctly(repo: Path) -> None:
    """The primitive itself, on three real shapes: a root commit (the
    fixture's own baseline, zero parents), an ordinary commit (one
    parent), and a real two-parent merge."""
    root = _head(repo)
    assert _parent_count(repo, root) == 0

    (repo / "src" / "app.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "ordinary commit")
    ordinary = _head(repo)
    assert _parent_count(repo, ordinary) == 1

    _git(repo, "branch", "feature", root)
    _git(repo, "checkout", "-q", "feature")
    (repo / "docs" / "korax-revisions.md").write_text(
        "# Revisions\n\n## R1 — the beginning\n\n## R-NEXT — feature work\n"
    )
    _git(repo, "commit", "-qam", "feature branch entry")
    _git(repo, "checkout", "-q", "main")
    merge = _git(repo, "merge", "--no-ff", "-q", "-m", "merge feature", "feature")
    assert merge.returncode == 0, merge.stderr
    merged = _head(repo)
    assert _parent_count(repo, merged) == 2


def test_entry_added_sees_the_whole_feature_branch_through_a_real_merge(
    repo: Path,
) -> None:
    """The property that motivated target^1 over a commit-by-commit
    walk: a REAL two-parent merge's first-parent diff captures every
    commit the feature branch carried, however many there were — proven
    here with a two-commit feature branch, the entry on the FIRST of
    the two, not the merge commit itself."""
    root = _head(repo)
    _git(repo, "branch", "feature", root)
    _git(repo, "checkout", "-q", "feature")
    with (repo / "docs" / "korax-revisions.md").open("a") as f:
        f.write("\n## R-NEXT — added on the first feature commit\n\nfixture\n")
    _git(repo, "commit", "-qam", "feature commit 1: the ledger entry")
    (repo / "src" / "app.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "feature commit 2: unrelated code, no entry here")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "-m", "merge feature", "feature")
    merged = _head(repo)

    assert _parent_count(repo, merged) == 2
    assert _entry_added(repo, merged), (
        "a two-commit feature branch's entry, on its first commit, must "
        "still be visible through the merge's first-parent diff — this "
        "is what makes target^1 safe for a real multi-commit delivery"
    )


def test_trailer_present_sees_the_whole_feature_branch_through_a_real_merge(
    repo: Path,
) -> None:
    """The trailer form of the same property: the escape can sit on
    either commit of a real merged-in branch, not only the merge
    commit's own message."""
    root = _head(repo)
    _git(repo, "branch", "feature", root)
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "commit", "--allow-empty", "-qm",
         "Ledger: none — the escape, on the first feature commit")
    (repo / "src" / "app.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "feature commit 2: the actual code change")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "-m", "merge feature", "feature")
    merged = _head(repo)

    assert _parent_count(repo, merged) == 2
    assert _trailer_present(repo, merged)


# ── the trailer pattern matches what it must, and only that ────────────


def test_the_trailer_pattern_requires_the_literal_key_and_value(repo: Path) -> None:
    """`Ledger: none` must anchor the line start — a prose sentence that
    happens to contain the words must not fire."""
    (repo / "src" / "app.py").write_text("changed\n")
    msg = "code change\n\nSaw the Ledger: none of this made sense to skip.\n"
    _git(repo, "commit", "-qam", msg)
    target = _head(repo)

    assert not _trailer_present(repo, target), (
        "a sentence mentioning 'Ledger: none' mid-prose is not a trailer "
        "declaration and must not be read as one"
    )


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


def test_the_leg_fails_closed_on_an_octopus_or_root_target() -> None:
    """#2783 ruling 2: an octopus target (>2 parents) or a root commit
    (0 parents) must FAIL with a named reason, not be interpreted —
    structural check that both guards exist in the wrapper, since the
    wrapper itself is not directly callable against a fixture repo
    (REPO_ROOT is readonly, tied to the real checkout)."""
    text = GATE.read_text(encoding="utf-8")
    assert "octopus merge" in text
    assert "root commit" in text
    assert "ledger_disposition_parent_count" in text


def test_the_report_names_ten_invocations() -> None:
    """The lane is one command for two legs (ruff+mypy); ledger-
    disposition is its own command — nine become ten."""
    report = GATE.read_text(encoding="utf-8").split("report()")[-1]
    assert "10 invocations" in report
