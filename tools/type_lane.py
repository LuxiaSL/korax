"""The type lane, and it says what it ran against — ISSUE #2378, ruled #2379.

**THE DEFECT THIS EXISTS FOR.** R131 shipped a lane whose output is
`All checks passed!` and `Success: no issues found in 49 source files`.
Neither string names a sha, a tree, or a time. So a delivery that says
"ruff passed" makes a claim **no artifact binds to the delivered
bytes** — and a claimant who ran the lane honestly, then added a file,
then quoted the earlier result, produces output textually identical to
a current clean run.

That is not hypothetical: #2375 bounced a delivery for exactly it, and
the mill's reading was *"a stale measurement reported as current, not a
fabricated one."* The wrong answer and the right answer were the same
string.

**AND THE GATE IS THE PRIMARY VICTIM, NOT THE CLAIMANT** (#2380). The
mill's own gate envelopes say "ruff and mypy clean on the merged tree",
which is unpinned in precisely the way the bounced claim was — and
nobody bounced the gate. One gap, two victims, and the one whose whole
function is to stop taking claims on trust is the one that should have
noticed first. So this prints for a GATE TRANSCRIPT, where seven legs'
output runs together: one distinctive line, quotable on its own.

**WHY A WRAPPER AND NOT A HOOK — the asymmetry that decided the shape.**
R130 never had to change its command: `pytest` is still `pytest`, and
the `korax tree:` line rides a `conftest.py` plugin seam the repo
controls. **`ruff` and `mypy` expose no such seam.** So self-describing
output cannot be bolted onto the existing invocation; it has to be a
different command that wraps them. R131's character-for-character
property survives only because THIS becomes the one command everywhere
— CI and local, same line (#2379).

The bare `uv run ruff check .` stays perfectly runnable mid-work. It
just stops being citable as delivery evidence, exactly as a suite
number without R130's tree line already is.

**THE STAMP TELLS THE TRUTH ABOUT A DIRTY TREE AND NEVER REFUSES.** A
stamp naming a clean sha over uncommitted changes is a worse lie than
no stamp at all — it manufactures the confidence this whole tool exists
to remove. A mid-work run is legitimate; the stamp says `DIRTY (n
files)` and the gate weighs it (#2378's constraint, adopted verbatim as
the acceptance floor at #2379).

**AND IT REPORTS WHERE THE PACKAGES RESOLVE FROM, WHICH IS NOT
DECORATION.** `mypy` resolves imports through the installed
distributions, so a lane run under another checkout's venv type-checks
that checkout's code while collecting config from this one — R130's
hazard (#2286), arriving in the lane instead of the suite, and silent
in the direction that matters: a GREEN over code the delivery does not
contain. `tree_guard.header()` is reused rather than reimplemented so
the `korax tree:` line is byte-identical to the suites' and one grep
finds both.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]

#: The distributions whose resolution decides what `mypy` actually reads.
PACKAGES: tuple[str, ...] = ("korax", "korax_cli", "korax_mcp")

#: The two checks, in order, each run to completion. NOT short-circuited:
#: a ruff failure must not hide a mypy failure, because a claimant who
#: fixes the first and re-runs should not discover the second on the
#: third attempt. Both rc values are reported; the exit code is their
#: max-nonzero (see `main`).
CHECKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ruff", ("ruff", "check", ".")),
    ("mypy", ("mypy",)),
)


def _tree_guard():
    """Load `tree_guard` BY PATH, matching the conftests' own reason
    (`clients/mcp/tests/conftest.py`): loading it by name would resolve
    through whatever `tools` package happens to be importable, which is
    the exact confusion this file reports on."""
    spec = importlib.util.spec_from_file_location(
        "korax_tree_guard_lane", TREE / "tools" / "tree_guard.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - packaging
        raise RuntimeError("could not load tools/tree_guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=TREE, check=False
    )
    return proc.returncode, proc.stdout.strip()


def revision() -> str:
    """The sha, or an explicit unknown — never a plausible-looking blank.

    An empty string here would render as `sha: ` and read as a stamp
    that was made and found nothing, which is the shape of defect this
    file exists to remove."""
    rc, out = _git("rev-parse", "HEAD")
    return out if rc == 0 and out else "UNKNOWN (not a git tree, or git unavailable)"


def dirty_state() -> tuple[bool, int, str]:
    """`(is_dirty, file_count, rendered)`.

    A tree whose state cannot be READ is reported as unknown, not as
    clean. Failing open here would put `CLEAN` beside a sha on a tree
    nobody measured — the precise lie the acceptance floor forbids.
    """
    rc, out = _git("status", "--porcelain")
    if rc != 0:
        return True, 0, "DIRTY-STATE UNKNOWN (git status failed — treat as dirty)"
    files = [line for line in out.splitlines() if line.strip()]
    if files:
        return True, len(files), f"DIRTY ({len(files)} file{'s' if len(files) != 1 else ''})"
    return False, 0, "CLEAN"


def stamp() -> str:
    """The provenance block, printed before either checker runs.

    Printed on every run, pass or fail — the point is that a lane result
    stops being a string whose provenance you reconstruct later, and a
    stamp that appeared only on success would be absent from every
    transcript where it was most needed.
    """
    guard = _tree_guard()
    _dirty, _n, rendered = dirty_state()
    return "\n".join(
        [
            guard.header(TREE, PACKAGES),
            f"sha: {revision()}",
            f"working tree: {rendered}",
        ]
    )


def run_checks(runner=subprocess.run) -> list[tuple[str, int]]:
    """Run every check to completion; return `(name, returncode)` pairs."""
    results: list[tuple[str, int]] = []
    for name, argv in CHECKS:
        proc = runner(list(argv), cwd=TREE, check=False)
        results.append((name, proc.returncode))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="type_lane",
        description=(
            "The type lane with its provenance. Runs `ruff check .` and `mypy` "
            "over the workspace, after printing the tree, the sha and the "
            "working-tree state. THIS is the invocation to cite as delivery "
            "evidence (ISSUE #2378, ruled #2379); the bare tool commands stay "
            "runnable mid-work but are not citable."
        ),
    )
    parser.add_argument(
        "--stamp-only",
        action="store_true",
        help="print the provenance block and exit 0 without running either "
        "checker (for a gate transcript that wants the stamp beside numbers "
        "it already has)",
    )
    args = parser.parse_args(argv)

    print(stamp(), flush=True)
    if args.stamp_only:
        return 0

    results = run_checks()

    # THE EXIT CODE IS THE TOOLS' EXIT CODE. A wrapper that swallowed a
    # nonzero rc would be #2085's pipe-swallows-the-exit-code defect
    # rebuilt inside the lane built to prevent it — and it would fail
    # green, which is the direction that does not announce itself.
    failed = [name for name, rc in results if rc != 0]
    if failed:
        print(
            "\nlane FAILED: " + ", ".join(failed),
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - entrypoint
    raise SystemExit(main())
