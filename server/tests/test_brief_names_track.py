"""Briefs name their track, or say none — JOB #3768 (v2 R3).

The v1 map was sha-verified, cited by both seats all loop, never amended
— and never entered the briefs: its vocabulary reached 3 substantive of
27 briefs written during its life (#3759 §2 / #3760 §2a). A JOB is cut
from a brief; if the brief does not name a track, nothing downstream can,
and the ledger line inherits the silence. **The next postmortem should be
able to grep the briefs and find the map in them — or find `Track: none`
and know the work was deliberately off-map. Either is a record; silence
is what the last postmortem spent a sitting reconstructing.**

THREE THINGS THIS FILE REFUSES TO DO, each because the alternative is a
guard that cannot be reproduced:

  * **It does not carry a copy of the row list** (#2595). The rows are
    parsed out of `tooling-roadmap-v2.md` §2, which property 2 names as
    normative — NOT §3's manifest, which also carries `R4b`, `prior` and
    `—` rows that are not tracks a brief could claim.
  * **It does not hardcode the v2 sha.** The boundary is derived as the
    commit that ADDED the map. A literal here would be a second place to
    update and a silent way for the scope to drift from its own subject.
  * **It does not use dates.** Scope is `git merge-base --is-ancestor`,
    because a rebase or an out-of-order commit date would misjudge a
    clock comparison and ancestry is what the v2 commit actually bounds.
    This is also what preserves property 1's "exempt by date, not
    grandfathered by edit": birth is the ADD commit, so touching an old
    brief never pulls it into scope.
"""

from __future__ import annotations

# korax: needs-git-history — scope is derived from the ADD commit of each
# brief and of the map itself (`git log --diff-filter=A`), so a depth-1
# checkout would find no ADD commits, put every brief out of scope, and
# report a green sweep over an empty set. Caught by
# `test_shallow_declarations` at first full-suite run, which is the guard
# working: the failure mode is a vacuous pass, not an error.

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MAP = "briefs/tooling-roadmap-v2.md"

#: `- **R1c ...**`, `- **R2 ...**` — the letter is optional; this map's
#: own header for this very brief is `Track: v2 R3`, with no letter.
ROW = re.compile(r"^- \*\*(R\d+[a-z]?)\b")

#: `Track: v2 R1c (...)` or `Track: none — a reason`. The separator is
#: `[-—]` rather than the em-dash alone: a hyphen states the same thing
#: and a test that refused it would be enforcing typography.
TRACK_ROW = re.compile(r"^Track:\s*v2\s+(R\d+[a-z]?)\b")
TRACK_NONE = re.compile(r"^Track:\s*none\s*[-—]\s*(\S.*)$", re.I)

HEAD_LINES = 10


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def v2_sha() -> str | None:
    """The commit that added the map — the boundary, derived not copied.

    `None` where that commit is unreachable, which is the depth-1 case.
    """
    adds = git("log", "--diff-filter=A", "--format=%H", "--", MAP).split()
    return adds[-1] if adds else None


def require_history() -> str:
    """Skip BY NAME where the history this file declares is unreachable.

    THE SHALLOW-SAFE SHAPE (#2831, and `test_gate_ledger_disposition`'s
    own idiom). This file declares `needs-git-history`, so the shallow leg
    RUNS it inside a depth-1 clone to measure whether it survives there —
    the declaration is not an exemption. At depth 1 the map has no
    reachable ADD commit, so the boundary cannot be derived, every brief
    falls out of scope, and a sweep that simply proceeded would go GREEN
    OVER AN EMPTY SET. That vacuous pass is the failure mode worth more
    than the check: it would be indistinguishable in CI from a clean
    board. So the probe is explicit and the skip is named — the leg
    reports `declared, skipped by name`, which is evidence the guard
    fires rather than an absence."""
    # THE PROBE IS SHALLOWNESS ITSELF, not an absent ADD commit — and the
    # difference was found by RUNNING it in a depth-1 clone, not reasoned.
    # At depth 1 `--diff-filter=A` does NOT come back empty: the single
    # grafted commit looks like the add of every file in the tree. So the
    # boundary resolves to HEAD, every brief becomes its own descendant,
    # ALL 126 land in scope, and the pre-v2 ones red for lacking a line
    # they were never owed. A wrong answer, confidently — worse than the
    # vacuous pass this skip was first written to prevent.
    if git("rev-parse", "--is-shallow-repository") == "true":
        pytest.skip(
            "shallow clone: `--diff-filter=A` reports the grafted commit as "
            f"every file's birth, so the {MAP} boundary cannot be derived "
            "and scope cannot be computed. Declared `needs-git-history`; "
            "skipping BY NAME rather than answering from a fabricated scope"
        )
    sha = v2_sha()
    if sha is None:
        pytest.skip(f"no reachable ADD commit for {MAP}; boundary underivable")
    return sha


def map_rows() -> set[str]:
    """Row ids from §2 ONLY — property 2's normative surface."""
    text = (REPO / MAP).read_text()
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## §2"))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    rows = {m.group(1) for line in lines[start:end] if (m := ROW.match(line))}
    assert rows, "§2 parsed to zero rows — the parser lost its surface"
    return rows


#: The map is the SUBJECT of this rule, not a brief cut from it. Property 2
#: requires a named row to exist *in this file*, so demanding the map name a
#: row inside itself is a category error — and its own `Track: v2 (this
#: document)` is the correct self-reference. Excluded by path, deliberately,
#: reported at #4054 rather than buried.
NOT_A_BRIEF = {MAP}


def briefs_in_scope() -> list[str]:
    """Briefs whose ADD commit is at or after the v2 commit — plus briefs
    that have no ADD commit yet, which are NEW and therefore post-v2 by
    construction.

    THE WORKING TREE, NOT `ls-tree HEAD`. A brief being written right now
    is untracked, so a HEAD-only walk would skip exactly the file whose
    author most needs telling — the guard would fire one commit after the
    moment it is useful. Enumerating the working tree costs nothing and
    makes the check available before the commit rather than after it.
    """
    boundary = require_history()
    out = []
    for file in sorted((REPO / "briefs").glob("*.md")):
        path = f"briefs/{file.name}"
        adds = git("log", "--diff-filter=A", "--format=%H", "--", path).split()
        if not adds:
            # No ADD commit: this brief is new. New is post-v2, always.
            if path not in NOT_A_BRIEF:
                out.append(path)
            continue
        birth = adds[-1]
        rc = subprocess.run(
            ["git", "-C", str(REPO), "merge-base", "--is-ancestor", boundary, birth],
            capture_output=True,
        ).returncode
        if rc == 0 and path not in NOT_A_BRIEF:
            out.append(path)
    return out


def track_line(path: str) -> tuple[int, str] | None:
    """The `Track:` line and its 1-indexed line number, within the head."""
    for n, line in enumerate(
        (REPO / path).read_text().splitlines()[:HEAD_LINES], start=1
    ):
        if line.startswith("Track:"):
            return n, line
    return None


# -- the guard ---------------------------------------------------------------


def test_every_post_v2_brief_names_a_track_or_says_none() -> None:
    """Properties 1 and 3. The failure names the file AND the line, because
    a guard that says only "some brief is wrong" costs its reader the
    search this test exists to save."""
    rows = map_rows()
    problems: list[str] = []
    for path in briefs_in_scope():
        found = track_line(path)
        if found is None:
            problems.append(
                f"{path}: no `Track:` line in the first {HEAD_LINES} lines — add "
                f"`Track: v2 R<n>` naming a row in {MAP} §2, or "
                f"`Track: none — <reason>`"
            )
            continue
        lineno, line = found
        if (m := TRACK_ROW.match(line)) is not None:
            if m.group(1) not in rows:
                problems.append(
                    f"{path}:{lineno}: names row `{m.group(1)}`, which is not in "
                    f"{MAP} §2 (rows there: {', '.join(sorted(rows))})"
                )
        elif TRACK_NONE.match(line) is None:
            problems.append(
                f"{path}:{lineno}: `Track:` is neither `v2 R<n>` nor "
                f"`none — <non-empty reason>`: {line!r}"
            )
    assert not problems, "\n  ".join(["briefs do not name their track:", *problems])


def test_the_scope_is_ancestry_not_edit_history() -> None:
    """Property 1's second clause, tested rather than asserted.

    "Exempt by date, not grandfathered by edit" is the clause a naive
    `git log -1` implementation gets wrong: it would pull every pre-v2
    brief that has since been touched into scope. `gate-scope.md` is the
    brief the JOB names for this — it predates v2, carries no `Track:`
    line, and must stay out of scope however often it is edited."""
    scope = set(briefs_in_scope())
    assert "briefs/gate-scope.md" not in scope, (
        "a pre-v2 brief entered scope — birth is the ADD commit, not the "
        "last edit; check `briefs_in_scope` is not using `git log -1`"
    )
    assert track_line("briefs/gate-scope.md") is None, (
        "the exemption fixture now carries a Track: line and no longer "
        "tests the exemption — pick another pre-v2 brief"
    )


def test_the_sweep_is_not_vacuous() -> None:
    """Floors, not equalities: a scope that stopped finding briefs, or a
    §2 that stopped parsing, would make the guard above pass forever."""
    scope = briefs_in_scope()
    rows = map_rows()
    assert len(scope) >= 14, (
        f"only {len(scope)} briefs in scope — the v2 commit added 14 with "
        f"Track lines from birth, so this cannot be right"
    )
    assert len(rows) >= 10, f"§2 parsed to only {len(rows)} rows"


def test_rows_come_from_section_2_and_not_the_manifest() -> None:
    """Property 2 names §2, and §3 is a DIFFERENT list — it carries `R4b`
    with no brief, plus `prior` and `—` rows. Parsing the manifest would
    silently widen what a brief may claim, so the surface is pinned."""
    rows = map_rows()
    manifest = (REPO / MAP).read_text().split("## §3")[1]
    assert "prior" in manifest, "the manifest no longer looks as assumed"
    assert not any(r.lower() == "prior" for r in rows)
    assert "R3" in rows and "R1c" in rows, "§2's own rows are missing"


# -- acceptances 1, 2, 4: the guard must go RED, and for the right file ------


@pytest.fixture()
def planted():
    """A brief that exists only for the duration of one test.

    Restored in a `finally` rather than by the test body: a planted file
    surviving a failure would leave every later test in this suite red
    for a reason that has nothing to do with them, and the next reader
    would debug the wrong thing."""
    made: list[Path] = []

    def plant(name: str, body: str) -> str:
        path = REPO / "briefs" / name
        assert not path.exists(), f"{name} already exists; pick another fixture name"
        path.write_text(body)
        made.append(path)
        return f"briefs/{name}"

    try:
        yield plant
    finally:
        for path in made:
            path.unlink(missing_ok=True)


def _problems() -> list[str]:
    """Run the guard and return its complaint list rather than its raising."""
    try:
        test_every_post_v2_brief_names_a_track_or_says_none()
    except AssertionError as exc:
        return str(exc).splitlines()
    return []


def test_a_brief_with_no_track_line_reddens_with_its_path(planted) -> None:
    """Acceptance 1. The path is the point: a guard that says only "a brief
    is wrong" costs its reader the search this test exists to save."""
    path = planted("zz-planted-no-track.md", "# a planted brief\n\nNo track here.\n")
    problems = _problems()
    assert any(path in p and "no `Track:` line" in p for p in problems), (
        f"a brief with no Track: line did not redden with its path; got {problems}"
    )


def test_removing_the_planted_brief_returns_the_guard_to_its_prior_state() -> None:
    """Acceptance 1's second half — THE CONTROL. A guard that reddened
    unconditionally would pass the test above while being useless."""
    problems = _problems()
    assert not any("zz-planted" in p for p in problems), (
        "a planted fixture outlived its test — the fixture teardown is broken"
    )


def test_a_track_naming_a_row_that_does_not_exist_reddens(planted) -> None:
    """Acceptance 2, first half. `R99` is not in §2 and never was."""
    path = planted("zz-planted-bad-row.md", "# planted\n\nTrack: v2 R99 (nope)\n")
    problems = _problems()
    assert any(path in p and "R99" in p for p in problems), (
        f"a Track naming a nonexistent row did not redden; got {problems}"
    )


def test_track_none_with_a_reason_is_green(planted) -> None:
    """Acceptance 2, second half — THE CONTROL for the test above. If
    `none` reddened too, the first assertion would pass for the wrong
    reason and the guard would forbid off-map work entirely."""
    path = planted("zz-planted-none.md", "# planted\n\nTrack: none — spike\n")
    assert not any(path in p for p in _problems()), (
        "`Track: none — spike` reddened; property 3 makes `none` a legal answer"
    )


def test_track_none_without_a_reason_reddens(planted) -> None:
    """Property 3: `none` is a reason, not an exemption. Bare `none` is
    the shape that would let the rule be satisfied without the choice
    being made where a reader can see it."""
    path = planted("zz-planted-bare-none.md", "# planted\n\nTrack: none\n")
    assert any(path in p for p in _problems()), (
        "bare `Track: none` was accepted; the reason is what property 3 is for"
    )


def test_renaming_a_row_in_the_map_reddens_the_brief_that_names_it() -> None:
    """Acceptance 4 — the row list is the MAP's, not a copy in this file.

    Mutating §2 and nothing else must redden the brief naming the old row.
    If this passes with the map mutated, the test is reading a duplicate
    list somewhere and #2595's rule has been broken silently.
    """
    map_path = REPO / MAP
    original = map_path.read_text()
    assert "- **R1c " in original, "the §2 row shape changed; re-aim this mutation"
    try:
        map_path.write_text(original.replace("- **R1c ", "- **R1zz ", 1))
        problems = _problems()
        assert any("lane-is-strings.md" in p and "R1c" in p for p in problems), (
            "renaming R1c in §2 did not redden the brief that names it — the "
            f"row list is not being read from the map. got: {problems}"
        )
    finally:
        map_path.write_text(original)
    assert not any("R1c" in p for p in _problems()), "the map was not restored"
