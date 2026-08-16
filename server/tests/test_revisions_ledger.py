"""JOB #715 — revision numbers are allocated where the serialization already is.

The ledger's numbers are chosen in a branch, and a branch cannot see what
else is in flight. Two enactors both wrote `R32` and the desk fixed it by
hand at the merge (#565) — and the ledger records **two earlier instances
of the same collision** in its own body, at `R23` and `R24`, each with a
parenthetical saying it was renumbered at merge. Three occurrences, two of
them written into the file this guard protects.

The remedy is that a delivery writes the literal token `R-NEXT` and the
desk substitutes the number at merge, where ordering is finally known.
That is a convention, and a documented invariant with nothing asserting it
is not an invariant (#111). This file is the assertion.

WHAT IS ASSERTED, AND WHY EACH IS THE SHAPE IT IS
-------------------------------------------------

  * **Labels are unique.** This is the one that catches the actual failure
    the remedy exists to prevent: two entries silently sharing `R32` after
    a bad resolution. It is checked over every label, `R-NEXT` included.

  * **The integer set is complete** — 1..max with nothing missing.

  * **File order is NOT asserted, deliberately** (design #747, endorsed at
    #753). The ledger reads `R1…R21, R19c, R22, R24, R23, R25…R36`: two
    file-order violations, both intentional and both self-documenting.
    `R19c` also proves the label space is not the integers, so a
    file-order assertion would need a total order over a set that has
    none — and an implementation that invented one by skipping what it
    cannot parse is #223's shape, a check that passes because it found
    nothing to check. Asserting file order would also delete the only
    surviving record that the collision is structural: a guard that
    erases its own motivating evidence is a tidy-up, not a guard (#175,
    run backwards).

  * **Every revision-shaped heading parses.** The direct defence against
    that same #223 failure: a label this file cannot read is a loud
    error, never a silent skip.

  * **At most one `R-NEXT`, and if present it is the last heading.** This
    is the always-on half of the token check, and it is load-bearing.
    A flat "no `R-NEXT`" assertion would fail every in-flight branch for
    doing exactly what the convention requires — starting with the branch
    that introduced this file. This form never fails legitimately, and it
    catches two failures the strict check cannot see at all: **two**
    `R-NEXT` entries (the R32 collision reappearing one layer up, now
    caught on the claimant's branch rather than at the gate) and an entry
    parked mid-file where the desk will not find it.

  * **Zero `R-NEXT` on the merge target**, gated on `KORAX_MERGE_TARGET`.
    Gated on an explicit context signal and NOT on branch name: the desk
    merges in a detached-HEAD worktree, where `git branch --show-current`
    returns empty and the check would silently pass — a false pass in the
    one value a reader takes as success (#680's family).

WHAT EACH CARRIER IS WORTH (#718 — name it, do not assume it)
-------------------------------------------------------------
The env var catches the mistake *before* the merge, the only point at
which catching it is free; its weakness is that it depends on the desk
remembering to export it, and a guard resting on one seat's discipline is
one bad shift from silently not running. CI on push-to-main depends on
nobody — no ritual, no memory, no seat — but catches it only *after* the
push, so the fix is a follow-up commit rather than a clean merge. The
first is the fast check, the second the reliable one. Neither is
sufficient alone, which is why both carriers ship.

This is a repo invariant with no home. It sits in the server suite
because that suite runs in CI, always, with no client coupling — not
because it is a server invariant. When #163's ops lane builds a
repo-level stage, moving it should be a `git mv` and nothing else, which
is why the repo root is found by marker rather than by counting parents.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

#: A revision heading: ``## R32 — Title``, ``## R19c — Title``, or the
#: pre-merge token ``## R-NEXT — Title``. The em-dash separator is what the
#: ledger has always used; the trailing group is deliberately loose so a
#: retitled entry never reads as an unparseable label.
_HEADING = re.compile(r"^##\s+(R-NEXT|R(\d+)([a-z]*))\s*—")

#: Anything that *looks* like it wants to be a revision heading. A line that
#: matches this but not `_HEADING` is a parse failure and is reported as one,
#: rather than being skipped into a false pass (#223).
_HEADING_SHAPED = re.compile(r"^##\s+R", re.IGNORECASE)

_LEDGER_RELATIVE = Path("docs") / "korax-revisions.md"

_MERGE_TARGET_ENV = "KORAX_MERGE_TARGET"

_NEXT = "R-NEXT"


def _repo_root() -> Path:
    """Walk up until the directory holding the ledger is found.

    Resolved by marker rather than by counting `parents[n]` so that moving
    this file to a repo-level stage stays a `git mv` and nothing else.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / _LEDGER_RELATIVE).is_file():
            return candidate
    raise FileNotFoundError(
        f"could not locate {_LEDGER_RELATIVE} in any parent of {here}; "
        "the revisions ledger guard cannot find the document it guards"
    )


def _ledger_path() -> Path:
    return _repo_root() / _LEDGER_RELATIVE


def _ledger_lines() -> list[str]:
    path = _ledger_path()
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:  # unreadable is a failure, never an empty parse
        raise AssertionError(f"cannot read the revisions ledger at {path}: {exc}") from exc


class Heading:
    """One parsed revision heading, with the line number that produced it."""

    __slots__ = ("label", "line_no", "number", "suffix")

    def __init__(self, line_no: int, label: str, number: int | None, suffix: str) -> None:
        self.line_no = line_no
        self.label = label
        self.number = number
        self.suffix = suffix

    @property
    def is_next(self) -> bool:
        return self.label == _NEXT

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"<{self.label} @ line {self.line_no}>"


def _parse_headings(lines: list[str]) -> list[Heading]:
    headings: list[Heading] = []
    for line_no, line in enumerate(lines, start=1):
        match = _HEADING.match(line)
        if match is None:
            continue
        label = match.group(1)
        number = int(match.group(2)) if match.group(2) is not None else None
        suffix = match.group(3) or ""
        headings.append(Heading(line_no, label, number, suffix))
    return headings


def _merge_target() -> bool:
    """True when running against the merge target.

    Empty string counts as unset: CI spells the off case as `''` rather than
    unsetting the variable, so a bare presence check would read every branch
    build as a merge target.
    """
    return bool(os.environ.get(_MERGE_TARGET_ENV, "").strip())


@pytest.fixture(scope="module")
def lines() -> list[str]:
    return _ledger_lines()


@pytest.fixture(scope="module")
def headings(lines: list[str]) -> list[Heading]:
    parsed = _parse_headings(lines)
    assert parsed, (
        f"no revision headings parsed out of {_ledger_path()}; the ledger is "
        "never legitimately empty, so this is a broken parser rather than a "
        "clean document"
    )
    return parsed


def test_every_revision_shaped_heading_parses(lines: list[str], headings: list[Heading]) -> None:
    """A label this guard cannot read must be loud, never skipped (#223)."""
    parsed_line_numbers = {h.line_no for h in headings}
    unparsed = [
        (line_no, line)
        for line_no, line in enumerate(lines, start=1)
        if _HEADING_SHAPED.match(line) and line_no not in parsed_line_numbers
    ]
    assert not unparsed, (
        "revision-shaped headings that this guard could not parse — fix the "
        "heading or the pattern, but do not let it pass unchecked:\n"
        + "\n".join(f"  line {n}: {line!r}" for n, line in unparsed)
    )


def test_revision_labels_are_unique(headings: list[Heading]) -> None:
    """Two entries sharing a number is the failure the whole job exists for."""
    seen: dict[str, list[int]] = {}
    for heading in headings:
        seen.setdefault(heading.label, []).append(heading.line_no)
    duplicates = {label: at for label, at in seen.items() if len(at) > 1}
    assert not duplicates, (
        # "the same number" was wrong for the case this fires on most often
        # (#822): `R-NEXT` is precisely the ABSENCE of a number, so a reader
        # hitting the two-token state was told their entries claimed a number
        # neither of them had. Same assertion, accurate wording, and it
        # points at the preamble rather than restating it here.
        "duplicate revision labels — two entries carry the same label:\n"
        + "\n".join(f"  {label} at lines {at}" for label, at in sorted(duplicates.items()))
        + ("\n  (`R-NEXT` twice means two deliveries are in flight, not a "
           "numbering mistake — see this file's preamble on stacking)"
           if "R-NEXT" in duplicates else "")
    )


def test_integer_revisions_have_no_gaps(headings: list[Heading]) -> None:
    """1..max complete. File ORDER is deliberately not asserted (#747/#753)."""
    numbers = sorted({h.number for h in headings if h.number is not None and not h.suffix})
    assert numbers, "no integer-numbered revisions found; the ledger cannot be in this state"
    missing = [n for n in range(1, max(numbers) + 1) if n not in numbers]
    assert not missing, (
        f"gaps in the revision sequence: {missing} missing between R1 and R{max(numbers)}"
    )


def test_at_most_one_r_next_and_it_is_last(headings: list[Heading]) -> None:
    """The always-on half — true on a well-formed branch, vacuous on main."""
    pending = [h for h in headings if h.is_next]
    assert len(pending) <= 1, (
        f"{len(pending)} {_NEXT} entries at lines {[h.line_no for h in pending]} — "
        "two deliveries are in flight with entries that will collide at the "
        "merge. This is the R32 collision one layer up, and catching it here "
        "is the point of the convention."
    )
    if pending:
        assert pending[0] is headings[-1], (
            f"the {_NEXT} entry at line {pending[0].line_no} is not the last "
            f"revision heading (last is {headings[-1].label} at line "
            f"{headings[-1].line_no}) — a pending entry parked mid-file is one "
            "the desk will not find when it substitutes the number at merge."
        )


@pytest.mark.skipif(
    not _merge_target(),
    reason=(
        f"{_MERGE_TARGET_ENV} is unset: {_NEXT} is CORRECT on an in-flight "
        "branch, so the strict check runs only against the merge target"
    ),
)
def test_no_r_next_on_the_merge_target(headings: list[Heading]) -> None:
    """The desk's half: the number is substituted before this lands on main."""
    pending = [h for h in headings if h.is_next]
    assert not pending, (
        f"{_NEXT} reached the merge target at lines "
        f"{[h.line_no for h in pending]} — the desk substitutes the real "
        "number at merge, where the ordering is finally known. Replace the "
        "token with the next free revision number."
    )


# ---------------------------------------------------------------------------
# The inline tag, everywhere else a shipping revision gets cited
# (ISSUE #2400/#2403) — a DIFFERENT convention from the heading above, and
# a different failure. `## R-NEXT` marks a whole ledger ENTRY, substituted
# at merge by the desk's own ritual and guarded since JOB #715. `[R-NEXT]`
# marks one CLAIM beside a rule, wherever that rule lives in prose — and
# nothing had ever looked, in any file, for up to ~90 revisions:
# `docs/korax-protocol.md` alone carried 18 unsubstituted instances at
# discovery, 13 of them mid-sentence rather than headings, which is exactly
# the shape a heading-anchored pattern cannot see (#2403's own gate-ritual
# gap: `grep -cE '^## R-NEXT'` reported this file clean nine times running).
# ---------------------------------------------------------------------------

#: The bracketed form. Deliberately distinct from `_HEADING`'s pattern (no
#: `##`, no em-dash) so this can never match the ledger's own heading
#: convention — the two tags coexist in the same repo on purpose and must
#: stay distinguishable by shape alone, not by which file they are in.
_INLINE_TAG = "[R-NEXT]"

#: `_INLINE_TAG` as an exact substring missed the COMBINED shape — a
#: section that already shipped one revision and was amended by a later
#: one writes `[R131, R-NEXT]`, not `[R-NEXT]` alone, and
#: `"[R-NEXT]" in "[R131, R-NEXT]"` is False (ISSUE #2510, found live: the
#: guard reported this file clean on the merge commit that carried the
#: exact tag it exists to catch). Anchored to ONE bracket pair — never
#: matches across two — so unbracketed prose naming the convention by
#: word stays outside it, same discipline as `_HEADING` above; a bracket
#: pair with something else inside (`[3]`) and R-NEXT unbracketed
#: elsewhere on the same line must not match either.
_INLINE_TAG_RE = re.compile(r"\[[^\[\]]*\bR-NEXT\b[^\[\]]*\]")


def _docs_dir() -> Path:
    return _repo_root() / "docs"


def _markdown_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.md"))


def _find_inline_tags(files: list[Path]) -> list[tuple[Path, int, str]]:
    """Every line across `files` carrying an inline `R-NEXT` tag, bare
    (`[R-NEXT]`) or combined with an already-shipped revision beside it
    (`[R131, R-NEXT]`).

    Scans every `docs/**.md` file, never just the ledger — the defect this
    guards against was found in prose, not in a heading, and there is no
    reason to believe `korax-protocol.md` is the only document that can
    grow one.
    """
    offenders: list[tuple[Path, int, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if _INLINE_TAG_RE.search(line):
                offenders.append((path, line_no, line.strip()))
    return offenders


@pytest.mark.skipif(
    not _merge_target(),
    reason=(
        f"{_MERGE_TARGET_ENV} is unset: an inline {_INLINE_TAG} tag is "
        "CORRECT on an in-flight branch (the shipping revision is not "
        "known until merge) — the same shape as the ledger's own heading "
        "check, so this strict half runs only against the merge target too."
    ),
)
def test_no_inline_r_next_tag_in_docs_on_the_merge_target() -> None:
    """The substitution pass's own guard (#2400/#2403), extended to the
    combined shape #2510 found it blind to, so neither backlog can
    silently reaccrue."""
    offenders = _find_inline_tags(_markdown_files(_docs_dir()))
    assert not offenders, (
        f"an inline {_INLINE_TAG}-shaped tag, bare or combined with an "
        "already-shipped revision (`[R131, R-NEXT]`), reached the merge "
        "target — each marks a rule whose shipping revision was never "
        "substituted for the real one (#2400, #2510):\n"
        + "\n".join(
            f"  {p.relative_to(_repo_root())}:{n}: {line}"
            for p, n, line in offenders
        )
    )


#: Canary matrix (#2510: "the canary matrix is the deliverable, because
#: the defect is not that the string was wrong but that one shape was
#: never enumerated"). Two axes — bare vs. combined, heading vs.
#: mid-sentence — four red cases, crossed explicitly rather than folded
#: into one assertion so a regression in any one cell fails on its own
#: line instead of behind a passing `len() == 4`.
_RED_CANARY_CASES = {
    "bare_heading": "### 1.1 A heading `[R-NEXT]`\n",
    "bare_mid_sentence": "A claim, scoped `[R-NEXT]` mid-sentence.\n",
    "combined_heading": "### 11.5 A heading `[R131, R-NEXT]`\n",
    "combined_mid_sentence": (
        "A claim, scoped `[R131, R-NEXT]` mid-sentence.\n"
    ),
}


@pytest.mark.parametrize("case_name", sorted(_RED_CANARY_CASES))
def test_the_inline_tag_scan_can_fail(case_name: str, tmp_path: Path) -> None:
    """Canary, red direction (#112), one case per cell of the matrix
    above. The combined cases are the ones ISSUE #2510 found missing: a
    section that already shipped one revision and was amended by another
    writes `[R131, R-NEXT]`, and an exact-substring test for `[R-NEXT]`
    alone — `"[R-NEXT]" in "[R131, R-NEXT]"` — is False. That exact tag
    reached the merge commit at `97239cc` with the un-fixed guard reading
    it clean; this is the case that must not go quiet again."""
    doc = tmp_path / f"{case_name}.md"
    doc.write_text(_RED_CANARY_CASES[case_name], encoding="utf-8")
    found = _find_inline_tags([doc])
    assert found == [(doc, 1, _RED_CANARY_CASES[case_name].strip())]


def test_the_inline_tag_scan_stays_quiet_on_unrelated_brackets(
    tmp_path: Path,
) -> None:
    """Canary, green direction, the control the combined-form fix needs on
    its own: a bracket pair that does NOT contain `R-NEXT`, on a line that
    separately names `R-NEXT` outside any brackets, must not match — the
    regex is anchored to one bracket pair and must not let an unrelated
    pair on the same line stand in for it."""
    clean_doc = tmp_path / "clean.md"
    clean_doc.write_text(
        "See item [3] about the R-NEXT convention, unbracketed here.\n"
        "Two pairs: [ok] then more text, R-NEXT named but not bracketed.\n",
        encoding="utf-8",
    )
    assert _find_inline_tags([clean_doc]) == []


def test_the_inline_tag_scan_stays_quiet_on_a_clean_doc(tmp_path: Path) -> None:
    """Canary, green direction. Real prose that mentions the ledger's own
    `R-NEXT` convention BY NAME, unbracketed, must never trip this guard —
    a scan keyed on the bare word would refuse the ledger's own preamble
    explaining the convention, and every future reference to it."""
    clean_doc = tmp_path / "clean.md"
    clean_doc.write_text(
        "This section shipped in R42. The next revision (written R-NEXT "
        "in the ledger's own heading convention) is not this one.\n",
        encoding="utf-8",
    )
    assert _find_inline_tags([clean_doc]) == []
