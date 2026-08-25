"""`tools/shell_lane.py` — the shell lane, ISSUE #3990.

**WHY THESE ARE REPO TESTS.** The whole subject of the issue is a claim
in a header with nothing holding it to account. A lane whose own
behaviour is unasserted would be that defect one level up — and the
lane's failure modes are the interesting half, because a checker that
cannot go red is indistinguishable from a clean repo (#112/#921).

**EVERY TEST READS THE DECLARATION OUT OF THE MODULE.** None carries its
own copy of the severity floor or the no-disable file list; a test
holding a duplicate passes while the two drift apart (#2482).
"""

from __future__ import annotations

# korax: needs-git-history
#
# Declared because `test_the_repo_is_actually_clean_at_this_tree` runs the
# real lane at `cwd=REPO`, and the lane asks git which files are tracked.
# Per #2831's own terms the marker means "this file asks the real
# repository", NOT "this file breaks at depth 1" — and this one should
# not: `git ls-files` reads the INDEX, which `actions/checkout@v4`
# populates fully at depth 1. That is a prediction, and predicting is the
# shallow leg's job rather than this comment's; the leg now runs this file
# and will say.

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LANE = REPO / "tools" / "shell_lane.py"


def _lane():
    """Load the lane BY PATH, for the reason it loads `tree_guard` that
    way: importing by name resolves through whatever `tools` package is
    importable, which is the confusion its own stamp reports on."""
    spec = importlib.util.spec_from_file_location("korax_shell_lane_under_test", LANE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_lane_exists_and_parses() -> None:
    assert LANE.is_file(), "tools/shell_lane.py is missing"
    _lane()


def test_the_lane_is_wired_into_ci() -> None:
    """A lane nothing runs is a lane that cannot go red where it matters.

    Asserted against the workflow text rather than a YAML parse so this
    test needs no parser dependency of its own; the invocation string is
    what must match the local one (#2379), and that is a substring
    question.
    """
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uv run tools/shell_lane.py" in ci, (
        "the shell lane is not invoked by CI — the claim it exists to hold "
        "would go unchecked exactly where nobody is watching"
    )


def test_ci_runs_the_same_invocation_a_band_runs() -> None:
    """R131's character-for-character property (#2379), one lane over.

    If CI ran a bare `shellcheck` while a band ran the wrapper, the two
    would differ in scope, severity and resolution path while reporting
    the same way.
    """
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "shellcheck" not in ci.split("shell:")[-1].split("deploy-script:")[0] or (
        "uv run tools/shell_lane.py" in ci
    ), "CI must invoke the wrapper, never the bare checker"


def test_the_checker_is_pinned_rather_than_taken_from_the_host() -> None:
    """`shellcheck` is a system package, present on CI and absent on at
    least one band's host — which is how this repo went its whole life
    unable to run the check its own header claimed to pass. Resolving it
    through the pinned dependency is what makes the two invocations the
    same tool.
    """
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "shellcheck-py" in pyproject, (
        "shellcheck-py is not pinned; the lane would resolve whatever the "
        "host happens to ship, or nothing at all"
    )


def test_the_scope_is_tracked_files_not_a_glob() -> None:
    """A `rglob` sweeps `.venv`, build trees and nested worktrees, so the
    lane's scope would depend on the state of a checkout rather than on
    the repo — differing between a band's host and CI while reporting
    identically.
    """
    lane = _lane()
    seen: dict[str, list[str]] = {}

    class _Proc:
        returncode = 0
        stdout = "tools/a.sh\ntools/b.sh\n"
        stderr = ""

    def runner(argv, **kwargs):
        seen["argv"] = list(argv)
        return _Proc()

    assert lane.shell_files(runner=runner) == ["tools/a.sh", "tools/b.sh"]
    assert seen["argv"][:2] == ["git", "ls-files"], (
        f"the lane must ask git which files are tracked: {seen['argv']}"
    )


def test_the_lane_refuses_to_report_clean_over_an_empty_set() -> None:
    """#2485's denominator rule, in the lane instead of the suite. An
    empty file list means the scope query answered about the wrong tree,
    and 'checked nothing' must never render as 'found nothing wrong'.
    """
    lane = _lane()
    lane_files = lane.shell_files
    try:
        lane.shell_files = lambda *a, **k: []
        assert lane.main([]) == 2
    finally:
        lane.shell_files = lane_files


def test_the_disable_check_reads_the_file_itself(tmp_path: Path) -> None:
    """THE ONE FINDING SHELLCHECK CAN NEVER REPORT, by construction: it
    HONOURS a disable directive, so asking the checker whether a file
    carries suppressions comes back clean forever. The claim
    `korax-watch.sh` makes about itself is therefore only checkable by
    reading the bytes.
    """
    lane = _lane()
    assert lane.check_disables(paths=()) == []

    claimed = REPO / "tools" / "korax-watch.sh"
    assert claimed.is_file()
    assert lane.check_disables() == [], (
        "tools/korax-watch.sh carries a disable directive while its header "
        "claims it has none"
    )


def test_a_missing_file_that_claims_no_disables_is_an_offender() -> None:
    """Absent must not read as compliant — the empty-result family
    (#223/#156): a lookup that finds nothing and a file that is clean
    produce the same list unless one of them is made to speak.
    """
    lane = _lane()
    offenders = lane.check_disables(paths=("tools/does-not-exist.sh",))
    assert len(offenders) == 1 and "does not exist" in offenders[0]


def test_the_severity_floor_is_declared_not_defaulted() -> None:
    """ruff's config carries the same argument in prose: a checker that
    inherits its tool's default silently changes what it checks when the
    tool is upgraded. The floor is the repo's statement, and it shows up
    in a diff when it moves.
    """
    lane = _lane()
    assert lane.SEVERITY == "warning"
    assert f"--severity={lane.SEVERITY}" in LANE.read_text(encoding="utf-8")


def test_the_repo_is_actually_clean_at_this_tree() -> None:
    """THE CANARY THAT MUST STAY QUIET. Every test above proves the lane
    can speak; this one proves it is not shouting. Runs the real lane.
    """
    proc = subprocess.run(
        ["uv", "run", str(LANE)], cwd=REPO, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, (
        f"the shell lane is red at this tree:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "shell lane: clean" in proc.stdout


def test_the_stamp_names_the_tree() -> None:
    """A lane result that names no tree is a string whose provenance the
    next reader reconstructs — #2378's defect, which is why this is a
    wrapper at all.
    """
    lane = _lane()
    assert "korax tree:" in lane.stamp()
