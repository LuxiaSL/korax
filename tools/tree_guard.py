"""A suite must test the tree it was collected from (ISSUE #2286).

**The defect this exists for.** Every band here builds in a `git
worktree`, and the repo's venv holds an EDITABLE install pointing at the
shared checkout. So from a worktree:

    source /home/luxia/projects/korax/.venv/bin/activate
    python -m pytest clients/mcp/tests

collects test FILES from the worktree and imports `korax` / `korax_cli`
/ `korax_mcp` from **the shared checkout**. The suite is a hybrid of two
revisions and nothing says so.

**Why a guard and not a convention.** It is invisible for exactly as
long as the two trees agree, and speaks only once another band merges
something — so it surfaces as YOUR delivery breaking, in a file you
never touched, at the moment you are about to deliver. That is how it
was found (#2283: a red for `korax_why`, a verb belonging to another
band's revision). Convention did not prevent it; the band who walked
into it already knew about the rake (#1963).

**And the direction that should worry us more.** A red announces
itself. A GREEN does not: when the shared checkout is AHEAD of the
branch, the suite passes on code the delivery does not contain, and a
gate grades numbers never measured against the delivered bytes. The
mill checked their own gate against exactly this and found it clean
(#2290) — by measuring, not by remembering, which is the whole lesson.

So this module does two things, and the second is the mill's addition
at #2290:

  ENFORCE  refuse to run a suite whose packages resolve outside its own
           tree, naming both paths and the invocation that fixes it
           (#415 — the refusal is the instruction).
  REPORT   print the resolved paths in the header of EVERY run, so a
           suite's numbers are self-describing: a claimant can paste
           them into a delivery and a gate can read them without
           re-running anything.

Deliberately free of any pytest import: this stays a plain module that
can be exercised on its own, and the conftest that loads it converts a
refusal into the pytest-level error. It also never IMPORTS the packages
it checks — `find_spec` locates without executing, which keeps the
server suite's "no client package imports" rule (#1548) intact here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

#: The invocation that resolves packages to the tree you are standing in.
#: `--project .` is the load-bearing part; CI's `--directory <pkg>` leg is
#: the same fix expressed per-package.
CORRECT_INVOCATION = "uv run --project . pytest"


class CrossTreeImport(Exception):
    """A package under test resolved outside the tree the tests came from."""


def resolve(package: str) -> Path | None:
    """Where `package` WOULD import from, without importing it.

    `None` when it is absent or is a namespace package with no single
    origin — both are "this guard has nothing to say", never a failure:
    a suite that does not use a package is not testing the wrong one.
    """
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin or spec.origin == "built-in":
        return None
    return Path(spec.origin).resolve()


def offenders(tree_root: Path, packages: tuple[str, ...]) -> list[tuple[str, Path]]:
    """The packages resolving outside `tree_root`, in the order given."""
    tree_root = Path(tree_root).resolve()
    out: list[tuple[str, Path]] = []
    for name in packages:
        where = resolve(name)
        if where is None:
            continue
        if not where.is_relative_to(tree_root):
            out.append((name, where))
    return out


def header(tree_root: Path, packages: tuple[str, ...]) -> str:
    """One line per package: what this run is actually testing.

    Printed on every run, green or red. The point is that a suite result
    stops being a number whose provenance you have to reconstruct later.
    """
    tree_root = Path(tree_root).resolve()
    lines = [f"korax tree: {tree_root}"]
    for name in packages:
        where = resolve(name)
        if where is None:
            lines.append(f"  {name}: (not installed)")
            continue
        try:
            shown: str = str(where.relative_to(tree_root))
        except ValueError:
            shown = f"{where}   <-- OUTSIDE THIS TREE"
        lines.append(f"  {name}: {shown}")
    return "\n".join(lines)


def announce(terminalreporter, tree_root: Path, packages: tuple[str, ...]) -> None:
    """Write the resolved paths where they survive `-q`.

    **Two obvious implementations are broken, and both were tried here
    rather than reasoned about.**

    `pytest_report_header` is the idiomatic hook and is silent at
    negative verbosity — so under `-q`, which is what this floor and CI
    actually run, the paths never appear.

    Writing to the terminal reporter from `pytest_configure` looks like
    the fix and is not: global output capture is already active that
    early, so the line goes into a buffer nobody reads and vanishes at
    every verbosity. It LOOKS like it works because the guard beside it
    does.

    So this runs from `pytest_terminal_summary`, after capture is
    released — which also puts the paths immediately beside the pass/fail
    counts, exactly where someone about to quote those numbers into a
    delivery is already looking. Reporting that only speaks in the
    invocation nobody uses is the same defect class this module exists to
    catch: an instrument quiet when it matters.
    """
    if terminalreporter is None:
        return  # -p no:terminal, or a worker process: nothing to write to
    terminalreporter.write_line(header(tree_root, packages))


def enforce(tree_root: Path, packages: tuple[str, ...]) -> None:
    """Raise `CrossTreeImport` if any package resolves outside the tree."""
    bad = offenders(tree_root, packages)
    if not bad:
        return
    tree_root = Path(tree_root).resolve()
    detail = "\n".join(f"    {name:10} -> {where}" for name, where in bad)
    raise CrossTreeImport(
        "this suite would test another checkout's code.\n\n"
        f"  tests collected from: {tree_root}\n"
        "  but these resolve elsewhere:\n"
        f"{detail}\n\n"
        "  You are almost certainly in a git worktree with the shared\n"
        "  checkout's venv active. The editable install points at that\n"
        "  checkout, so the test FILES are yours and the CODE under test\n"
        "  is not — a red here can belong to another band's merge, and a\n"
        "  green can be measured against bytes you are not delivering.\n\n"
        f"  Run instead, from this tree:  {CORRECT_INVOCATION}\n"
        "  (ISSUE #2286; lineage #1963)"
    )
