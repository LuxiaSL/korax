"""A test that reads the real repository's history must DECLARE it (#2831).

WHY THIS EXISTS. `run_shallow_leg` proves its clone is shallow and then
runs `clients/cli/tests` — a directory with no history readers in it. So
the leg that exists to predict CI's depth-1 checkout runs the one part of
the tree that could never fail there, while the files that DO read real
history sit outside its scope. That is a check whose scope is narrower
than the condition it exists to predict, and it cost one red main
(#2409): a fixture built from two real shas passed every local run and
reddened CI, because `actions/checkout@v4` clones at depth 1 and those
shas resolve nowhere in it.

**No local run could have caught that**, which is the whole difficulty:
the machine where the fixture is written is the one machine that can
never reproduce a shallow-clone failure. The leg is the answer, and the
leg needs to know which tests to run — hence a declaration.

WHAT THE DECLARATION MEANS, EXACTLY. The marker says "this file asks the
real repository about its own history." It does NOT say "this file breaks
at depth 1" — that is what running it inside the shallow clone MEASURES,
and a file may legitimately declare and then skip by name in there (see
`test_gate_ledger_disposition.py`, which probes with `cat-file -e` and
skips when the sha is unreachable). Declaring is cheap and honest;
predicting is the leg's job.

THE PREDICATE IS DELIBERATELY NARROW, AND ITS GAPS ARE NAMED. It matches
a git subprocess pointed at the real repository root. It does NOT catch:
a test that shells out through a helper defined in another module; one
that reads `.git/` directly; one that resolves the repo by walking
upward under a different name than `REPO`. Those are real holes. The
guard is a floor on honesty, not a proof of completeness, and saying so
here is cheaper than someone discovering it by being surprised.

THE MARKER IS ASSEMBLED AT RUNTIME, NEVER WRITTEN WHOLE (#2694 §3,
#2762). A guard that greps for a literal it also contains matches its own
source and reports itself — that self-match has shipped twice on this
floor, once in a "no test may spawn Chrome" guard that matched the guard,
and once in a substring assertion whose haystack was the scratch path. It
fails in the direction that looks like success, so the counter-move is
structural rather than remembered: split the string.

AND THE ASSERTION LISTS ITS MATCHES, NEVER COUNTS THEM. A count cannot
distinguish "found nothing" from "searched nothing" (#2762), and every
self-match this floor has hit was invisible in a number and obvious in a
list.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent

# Split so this file does not match its own guard. Both halves are here
# for the reader; neither appears whole.
MARKER = "korax:" + " needs-git-history"
REENTRANT = "korax:" + " invokes-the-gate"

# A git subprocess aimed at the real repository root, in the two spellings
# this tree actually uses. Assembled for the same reason as the markers.
_CWD = "cwd" + "=" + "REPO"
_CWD_STR = "cwd" + "=" + "str(REPO)"
_DASH_C = re.compile(r'"-C"\s*,\s*(?:str\()?REPO')


def _reads_real_history(text: str) -> bool:
    return _CWD in text or _CWD_STR in text or bool(_DASH_C.search(text))


def _sources() -> list[tuple[Path, str]]:
    return [
        (p, p.read_text(encoding="utf-8"))
        for p in sorted(TESTS.glob("test_*.py"))
    ]


def test_every_real_history_reader_declares_itself() -> None:
    """The guard. An undeclared history reader is the #2409 shape."""
    offenders = [
        path.name
        for path, text in _sources()
        if _reads_real_history(text) and MARKER not in text
    ]
    assert offenders == [], (
        "these files run git against the real repository but carry no "
        f"`# {MARKER}` declaration, so the shallow leg cannot know to run "
        "them and CI's depth-1 checkout is the first thing that will ask: "
        f"{offenders}"
    )


def test_the_guard_can_see_the_files_it_is_guarding() -> None:
    """CONTROL. A guard that searched nothing passes identically to one
    that found nothing — so assert the population is non-empty and that
    the predicate actually selects a proper subset of it.

    Without this, deleting `TESTS.glob` would leave the guard above
    green forever.
    """
    sources = _sources()
    assert len(sources) >= 20, f"only {len(sources)} test files found — the glob is not reading the suite"

    readers = sorted(p.name for p, text in sources if _reads_real_history(text))
    assert readers, "the predicate matched no file at all — it has stopped measuring"
    assert len(readers) < len(sources), (
        "the predicate matched EVERY file, which no predicate this narrow "
        f"should: {readers}"
    )
    # SUBSET, NOT EQUALITY — and the difference is a defect I shipped and
    # caught by measuring a merge (#3079's own stacked tree, one branch
    # later).
    #
    # This asserted `readers == [the two files I knew about]`, for a good
    # reason badly executed: named, not counted (#2762), so a reader sees
    # WHICH file arrived rather than that a number moved. But equality
    # asserts the state of the WHOLE REPOSITORY, and any branch may add a
    # correctly-declared history reader. `vesper/gate-log-retention` did
    # exactly that: it added the declaration this guard demanded, and this
    # line reddened anyway — **a false red aimed at a branch that had just
    # complied.**
    #
    # That is the merge-fragile-assertion family, the same one that made a
    # count floor unusable when the battery flipped its own mode (#2993):
    # an assertion about a global whose owners are many, evaluated as if it
    # had one owner. The knowns-are-still-matched direction is what carries
    # the anti-vacuity value — if the predicate stops selecting these two,
    # it has stopped measuring — and nothing is lost by letting the set
    # grow, because an UNDECLARED arrival is caught by the guard above,
    # which is the property that actually matters.
    known = {"test_gate_ledger_disposition.py", "test_gate_sh_cleanup.py"}
    missing = sorted(known - set(readers))
    assert not missing, (
        "the predicate no longer selects files known to read real history, "
        f"so it has stopped measuring rather than found the repo clean: {missing}. "
        f"currently selected: {readers}"
    )


def test_a_reentrant_test_is_declared_and_never_silently_dropped() -> None:
    """A file that INVOKES the gate cannot be run inside the shallow leg's
    clone: `REPO` there resolves to the clone, so the gate would launch a
    full battery whose own shallow leg clones and runs this file again,
    with no re-entry guard anywhere in `gate.sh` to stop it.

    That exclusion has to be DECLARED and reported, not silently dropped —
    a leg that quietly omits work reports a denominator it did not earn,
    which is the defect the whole battery's declaration discipline exists
    to prevent (#2663/#2680).
    """
    declared = sorted(
        path.name for path, text in _sources() if REENTRANT in text
    )
    assert declared == ["test_gate_sh_cleanup.py"], (
        "the set of gate-invoking tests changed; each one must carry "
        f"`# {REENTRANT}` so the shallow leg reports it as excluded rather "
        f"than omitting it: {declared}"
    )
    # Belt and braces: re-entrant implies history-reading, so it must also
    # carry the other marker and thus be visible to the leg's accounting.
    text = (TESTS / "test_gate_sh_cleanup.py").read_text(encoding="utf-8")
    assert MARKER in text, (
        "a re-entrant test that does not also declare its history read "
        "would be excluded from a set it was never counted into"
    )
