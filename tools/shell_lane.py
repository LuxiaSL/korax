"""The shell lane, and it says what it ran against — ISSUE #3990.

**THE DEFECT THIS EXISTS FOR.** `tools/korax-watch.sh:56` says of itself
*"Passes `shellcheck` with no disables."* Nothing checked it. CI runs
shellcheck on no file at all, so from the day that sentence was written
until this lane, its truth was nobody's job — a documented invariant
with nothing asserting it is not an invariant (#111).

It happened to be TRUE, measured at `1bb797d`. That is the outcome that
makes the point rather than weakens it: **the claim was right and
unverified for its whole life, and an unverified true claim is
indistinguishable from an unverified false one** until somebody runs the
check. The shell surface here is four files; nobody had ever run
shellcheck over all four at once.

**WHY A WRAPPER AND NOT A BARE CI STEP** — the same asymmetry that
decided `type_lane.py`'s shape (#2378, ruled #2379). `shellcheck`'s
output names no tree, no sha and no time, so a delivery quoting "shellcheck
clean" makes a claim no artifact binds to the delivered bytes. The stamp
is `tree_guard.header()`, byte-identical to the suites' and the type
lane's, so one grep finds all three in a gate transcript.

**AND IT IS RESOLVED THROUGH uv, NOT FROM THE HOST.** `shellcheck` is a
system package: present on CI images, absent on at least one band's host
(mine — this issue was filed with `uvx --from shellcheck-py`, disclosed
at the time as a different resolution path from CI's, which is a caveat
this lane deletes rather than inherits). `shellcheck-py` is pinned in
`[dependency-groups]` so the local invocation and CI's are the same tool
at the same version.

**TWO CLAIMS, CHECKED SEPARATELY, BECAUSE THE FILES MAKE DIFFERENT
PROMISES.**

  1. Every shell file is shellcheck-clean at `--severity=warning`.
  2. `korax-watch.sh` additionally carries NO disable directives, which
     is the stronger claim its own header makes.

`gate.sh:386` carries a deliberate, commented `# shellcheck disable=SC2086`
and that is CORRECT — that file promises nothing, and a guard demanding
"no disables" everywhere would red a legitimate suppression (#3986 §3).
So the strong claim is asserted at the file that makes it, and nowhere
else. **A guard that checks a promise nobody made is how a rule starts
being routed around.**

**THE SEVERITY FLOOR IS A DECISION, NOT A DEFAULT.** `--severity=warning`
excludes `info` and `style`. The one info-level finding in this repo is
`deploy.sh:132`'s SC2029 (an unescaped ssh expansion, deliberate — the
remote command is built to expand client-side). Gating on style notes
would make the lane's first act a demand to rewrite a working line, and
a lane that opens by being wrong gets disabled rather than fixed. Raise
the floor deliberately if the flock wants it; do not let it drift.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]
PACKAGES: tuple[str, ...] = ("korax", "korax_cli", "korax_mcp")

#: The file whose header claims no disables, and the claim it makes.
#: One entry today; a list because the next file to claim it should be
#: added here rather than in a second copy of the logic.
NO_DISABLE_FILES: tuple[str, ...] = ("tools/korax-watch.sh",)

#: Excludes `info` and `style` — see the module docstring. Named here so
#: it is one edit in one place and shows up in a diff when it moves.
SEVERITY = "warning"


def _tree_guard():
    """Load `tree_guard` BY PATH, for `type_lane.py`'s stated reason:
    loading it by name resolves through whatever `tools` package happens
    to be importable, which is the confusion the stamp reports on."""
    spec = importlib.util.spec_from_file_location(
        "korax_tree_guard_shell_lane", TREE / "tools" / "tree_guard.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - packaging
        raise RuntimeError("could not load tools/tree_guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stamp() -> str:
    """The provenance block, printed on every run, pass or fail."""
    return _tree_guard().header(TREE, PACKAGES)


def shell_files(runner=subprocess.run) -> list[str]:
    """Every tracked `*.sh`, from git rather than from a glob.

    **Tracked, not found.** A `rglob` would sweep `.venv`, build trees
    and any worktree a band happens to have nested here, so the lane's
    scope would depend on the state of the checkout rather than on the
    repo — and it would differ between a band's host and CI while
    reporting the same way. `git ls-files` answers about the repo.
    """
    proc = runner(
        ["git", "ls-files", "*.sh"],
        cwd=TREE, check=False, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {proc.stderr.strip()}")
    return sorted(line for line in proc.stdout.split("\n") if line.strip())


def check_disables(paths: tuple[str, ...] = NO_DISABLE_FILES) -> list[str]:
    """Files claiming no disables that carry one anyway.

    Read here rather than delegated to shellcheck because shellcheck
    HONOURS a disable directive — it is the one finding the tool will
    never report, by construction. A check that asked shellcheck whether
    a file has suppressions would come back clean forever.
    """
    offenders: list[str] = []
    for rel in paths:
        target = TREE / rel
        if not target.is_file():
            offenders.append(f"{rel}: claimed no disables and does not exist")
            continue
        for number, line in enumerate(
            target.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "shellcheck disable=" in line:
                offenders.append(f"{rel}:{number}: {line.strip()}")
    return offenders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shell_lane",
        description=(
            "The shell lane with its provenance. Runs shellcheck over every "
            "tracked *.sh after printing the tree, the sha and the "
            "working-tree state. THIS is the invocation to cite as delivery "
            "evidence; a bare `shellcheck` stays runnable mid-work but names "
            "no tree (ISSUE #3990, and #2378's rule applied one lane over)."
        ),
    )
    parser.add_argument(
        "--stamp-only",
        action="store_true",
        help="print the provenance block and exit, running no checker",
    )
    args = parser.parse_args(argv)

    print(stamp(), flush=True)
    if args.stamp_only:
        return 0

    files = shell_files()
    if not files:
        # A lane that checks nothing must not report clean. An empty set
        # here means `git ls-files` answered about the wrong tree, which
        # is the failure this whole family is about (#2485's denominator
        # rule, in the lane instead of the suite).
        print(
            "shell lane: NO tracked *.sh found — refusing to report clean "
            "over an empty set",
            file=sys.stderr,
        )
        return 2
    print(f"  {len(files)} shell files, severity floor {SEVERITY}", flush=True)

    proc = subprocess.run(
        ["shellcheck", f"--severity={SEVERITY}", *files], cwd=TREE, check=False
    )
    failed = proc.returncode != 0

    offenders = check_disables()
    if offenders:
        failed = True
        print(
            "\nshell lane: these files claim `no disables` in their own "
            "header and carry one:",
            file=sys.stderr,
        )
        for line in offenders:
            print(f"  {line}", file=sys.stderr)

    if not failed:
        print("shell lane: clean")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
