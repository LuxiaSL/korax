"""`tools/gate.sh` — the gate ritual as code. JOB #2504, ISSUE #2085.

**WHY THESE ARE REPO TESTS AND NOT A CANARY SCRIPT.** The whole subject
of this JOB is that the mill's battery lived in `/tmp/claude-output/
gate-*.sh` and died with the session (#2492). A delivery whose canaries
live in `/tmp` rebuilds that defect inside the fix for it — the same
shape slate caught in the R85 rig at #2322 and then nearly repeated here.
So the acceptance evidence is a suite, and it runs on every gate forever
rather than once in a session nobody can reopen.

**EVERY TEST READS THE DECLARATION OUT OF THE SCRIPT.** None of them
carries its own copy of `PERCH_PATHS` or `LEG_NAMES`. A test holding a
duplicate of the thing under test passes while the two drift apart —
that is exactly #2482's argv-drift, where a probe's declaration and the
artifact compared against it were allowed to disagree.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "tools" / "gate.sh"


def _bash_array(name: str) -> list[str]:
    """Pull a `readonly NAME=( ... )` array out of gate.sh, verbatim.

    Parsed from the script rather than restated here, so a test can
    never assert about a declaration the tool no longer has.
    """
    text = GATE.read_text(encoding="utf-8")
    match = re.search(rf"^readonly {name}=\(\n(.*?)^\)$", text, re.M | re.S)
    assert match, f"{name} is not declared as a readonly array in tools/gate.sh"
    items: list[str] = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line.strip("'\""))
    return items


# ── the tool itself ───────────────────────────────────────────────────

def test_gate_sh_exists_and_is_executable() -> None:
    assert GATE.is_file(), "tools/gate.sh is missing"
    assert GATE.stat().st_mode & 0o111, "tools/gate.sh is not executable"


def test_gate_sh_parses() -> None:
    """`bash -n` — the same check CI runs on `tools/deploy.sh`."""
    proc = subprocess.run(
        ["bash", "-n", str(GATE)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"gate.sh does not parse:\n{proc.stderr}"


def test_no_leg_pipes_its_output_into_tee() -> None:
    """ISSUE #2085, which this tool closes, asserted precisely.

    `cmd | tee log` reports TEE's exit code, so every `&&` after one is
    a lie about what succeeded. This names that shape exactly rather
    than scanning for `|` in general: a first draft of this test did the
    general scan and flagged five lines, every one of them a `|` inside
    a quoted regex (`(passed|failed|error)`), a comment (`PASS | FAIL`),
    or a `case` pattern — five false positives and zero real findings.
    A check that cannot tell a shell pipe from a regex alternation is
    not checking #2085, and its green would have meant nothing.
    """
    offenders = [
        (n, line.strip())
        for n, line in enumerate(GATE.read_text(encoding="utf-8").splitlines(), 1)
        if "| tee" in line and not line.strip().startswith("#")
    ]
    assert not offenders, (
        "a leg's exit code would be tee's, not the command's — #2085:\n"
        + "\n".join(f"  {n}: {s}" for n, s in offenders)
    )


def test_every_leg_captures_the_exit_code_on_the_next_line() -> None:
    """The positive form of #2085, which is the one that can be checked.

    A leg runs, redirects to a FILE, and `$?` is read immediately — with
    nothing in between that could overwrite it. Asserting the structure
    beats scanning for a forbidden character.
    """
    text = GATE.read_text(encoding="utf-8")
    for redirect, capture in (
        ('> "$LOGDIR/$name.log" 2>&1', "local rc=$?"),
        ('> "$LOGDIR/shallow-clone.log" 2>&1', "local rc=$?"),
        ('> "$LOGDIR/type-lane.log" 2>&1', "local rc=$?"),
    ):
        idx = text.find(redirect)
        assert idx != -1, f"expected a leg redirecting to a file: {redirect}"
        following = text[idx + len(redirect) : idx + len(redirect) + 120]
        assert capture in following, (
            f"after {redirect!r} the very next statement must capture $?, "
            f"got:\n{following!r}"
        )


# ── the denominator (#2485, #2514) ────────────────────────────────────

def test_the_battery_declares_eleven_legs() -> None:
    """M comes from the DECLARATION, which is the whole point.

    The gavel settled M = 10 at #2514: 3 suites + browser + 3 CI-parity
    + 2 lane + shallow. #2680/#2682 cut an eleventh, ledger-disposition,
    and named the denominator move as a deliberate act rather than a
    side effect — this assertion is that act, restated as a check. A
    report that counted what it happened to run could not tell a
    shrunken battery from a whole one (#2482).
    """
    legs = _bash_array("LEG_NAMES")
    assert len(legs) == 11, f"expected 11 declared legs, found {len(legs)}: {legs}"
    assert len(set(legs)) == len(legs), f"duplicate leg name in {legs}"
    assert "ledger-disposition" in legs


def test_ruff_and_mypy_are_separate_legs_though_one_command_runs_them() -> None:
    """#2478's table counts two; R135/#2379 makes the wrapper one command.

    Both facts are true, and the reconciliation is that ONE invocation
    reports TWO legs. If a later edit collapses them the denominator
    silently becomes 9 while every prior gate said 10.
    """
    legs = _bash_array("LEG_NAMES")
    assert "ruff" in legs and "mypy" in legs, (
        "ruff and mypy must remain separately reported legs"
    )
    text = GATE.read_text(encoding="utf-8")
    assert "tools/type_lane.py" in text, (
        "the lane must run through the wrapper — the bare commands are not "
        "citable as delivery evidence (#2379/#2381)"
    )


def test_every_declared_leg_has_something_that_can_set_its_status() -> None:
    """A name in LEG_NAMES that nothing ever runs would report MISSING
    forever. Cheap structural check that the two halves match."""
    text = GATE.read_text(encoding="utf-8")
    for leg in _bash_array("LEG_NAMES"):
        assert re.search(rf"(run_leg|skip_leg) {re.escape(leg)}\b", text) or re.search(
            rf"LEG_STATUS\[{re.escape(leg)}\]", text
        ), f"declared leg {leg!r} has no runner and no status assignment"


def test_a_skip_is_reported_and_not_absorbed() -> None:
    """`9 of 9` for a skipped leg is the shrunken-battery defect (#2482)."""
    text = GATE.read_text(encoding="utf-8")
    assert "a skip is not a pass" in text
    assert "$ran of $LEG_COUNT" in text, (
        "the legs line must state its denominator explicitly"
    )


# ── the browser predicate (#2518 §2, #2520, #2525) ────────────────────

@pytest.fixture()
def planted(tmp_path: Path) -> tuple[Path, str]:
    """A throwaway repo carrying every root the real one has.

    Planted rather than borrowed: the R131 case proves the predicate
    against real history, and this proves it against files chosen to hit
    each root independently — including a `.js` driver, which #2525
    identified as the case the old predicate was blindest to.
    """
    repo = tmp_path / "repo"
    (repo / "server/korax/perch/js").mkdir(parents=True)
    (repo / "server/tests").mkdir(parents=True)
    (repo / "clients/cli").mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    (repo / "server/korax/perch/js/app.js").write_text("baseline\n")
    (repo / "server/tests/perch_smoke_driver.js").write_text("baseline\n")
    (repo / "server/tests/test_perch_smoke.py").write_text("baseline\n")
    (repo / "clients/cli/cli.py").write_text("baseline\n")

    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    git("config", "user.email", "canary@example.invalid")
    git("config", "user.name", "canary")
    git("add", "-A")
    git("commit", "-qm", "baseline")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, base


def _fires(repo: Path, base: str, paths: list[str]) -> bool:
    out = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD", "--", *paths],
        cwd=repo, capture_output=True, text=True, check=False,
    ).stdout.strip()
    return bool(out)


def _touch_and_commit(repo: Path, rel: str, base: str) -> None:
    subprocess.run(["git", "reset", "-q", "--hard", base], cwd=repo, check=True,
                   capture_output=True)
    (repo / rel).write_text("changed\n")
    subprocess.run(["git", "commit", "-qam", f"touch {rel}"], cwd=repo, check=True,
                   capture_output=True)


@pytest.mark.parametrize(
    "changed,owed",
    [
        ("server/korax/perch/js/app.js", True),
        ("server/tests/perch_smoke_driver.js", True),
        ("server/tests/test_perch_smoke.py", True),
        ("clients/cli/cli.py", False),
    ],
)
def test_the_browser_predicate_fires_on_every_live_perch_root(
    planted: tuple[Path, str], changed: str, owed: bool
) -> None:
    """BOTH directions (#112): it fires where the leg is owed and stays
    silent where it is not. A predicate that only ever fired would be as
    useless as one that never did."""
    repo, base = planted
    _touch_and_commit(repo, changed, base)
    assert _fires(repo, base, _bash_array("PERCH_PATHS")) is owed, (
        f"changing {changed} should {'' if owed else 'NOT '}make the browser leg owed"
    )


def test_the_driver_case_is_the_one_the_app_only_predicate_missed(
    planted: tuple[Path, str]
) -> None:
    """The regression this predicate exists for, shown rather than said.

    `server/korax/perch/**` alone — the set carried until #2520 — returns
    nothing for a driver-only change, so the leg reports `SKIPPED (no
    perch files)`: truthfully, about the wrong question. R131/`b789438`
    is the real instance (#2525); this is the same shape on planted
    files so it cannot rot when that commit ages out of anyone's memory.
    """
    repo, base = planted
    _touch_and_commit(repo, "server/tests/perch_smoke_driver.js", base)
    assert not _fires(repo, base, ["server/korax/perch/**"]), (
        "the app-only predicate should MISS a driver-only change — if this "
        "starts passing, the regression it documents has changed shape"
    )
    assert _fires(repo, base, _bash_array("PERCH_PATHS")), (
        "the shipped predicate must catch a driver-only change"
    )


def test_the_predicate_names_no_directory_that_does_not_exist() -> None:
    """`clients/perch/**` was in the handed-down set and has never
    existed (#2520). A pathspec nobody can trip is indistinguishable
    from one that is watching, which is #2510's enumeration axis."""
    for spec in _bash_array("PERCH_PATHS"):
        root = spec.split("*")[0].rstrip("/")
        assert (REPO / root).exists(), (
            f"predicate names {spec!r} but {root!r} does not exist in the tree"
        )


# ── the shallow leg's own control (#2518 §4) ──────────────────────────

def test_the_shallow_leg_carries_a_control_not_just_an_assertion() -> None:
    """Proving the leg reddens on a missing fixture proves it fails when
    it should. Proving the BARE-PATH form does not redden is what proves
    it is shallow at all — `--depth` is silently ignored for a local
    path and git's warning goes to stderr, where a script drops it
    (#2409, #2492 §1). The control lives in the leg so it cannot decay
    into something somebody ran once."""
    text = GATE.read_text(encoding="utf-8")
    assert 'git clone --depth 1 "file://$WT"' in text, "the file:// form is required"
    assert 'git clone --depth 1 "$WT"' in text, (
        "the bare-path CONTROL clone is missing — without it the leg proves "
        "only that it can fail, not that it is shallow"
    )
    assert "CONTROL FAILED" in text, (
        "the leg must redden when the control shows file:// is not what makes "
        "the clone shallow"
    )


def test_the_browser_leg_requires_its_dependencies_like_ci_does() -> None:
    """Without `KORAX_BROWSER_REQUIRED=1` a missing Chrome SKIPS
    (`test_perch_smoke.py`) and the leg exits 0 having run nothing — a
    green leg that measured zero tests. CI sets it; the hand-run battery
    did not."""
    assert "KORAX_BROWSER_REQUIRED=1" in GATE.read_text(encoding="utf-8")


# ── the ledger checks, both files (#2496 item 3) ──────────────────────

def test_the_ledger_checks_cover_the_revisions_file() -> None:
    """The allocation step is two halves and the prose half was the one
    being run from memory — which is how nineteen inline tags accrued
    against a ledger at R138 (#2496)."""
    text = GATE.read_text(encoding="utf-8")
    assert "docs/korax-revisions.md" in text
    assert "R-NEXT" in text


def test_the_inline_tag_check_echoes_the_guard_rather_than_narrowing_it() -> None:
    """**The regression that bounced R142 (#2634).**

    The suite's guard scans `_docs_dir().rglob("*.md")` — every markdown
    file under `docs/`. The first cut of gate.sh's ledger line read
    `docs/korax-protocol.md` alone, so it reported clean about a
    narrower question than the check it stood in for, while the guard
    had a hit in `korax-revisions.md`.

    A stand-in that answers less than its original reports clean at
    exactly the moment the original would not — #2482's argument aimed
    at the replacement instead of the thing replaced. This asserts the
    two scopes agree, so the narrowing cannot come back quietly.
    """
    text = GATE.read_text(encoding="utf-8")
    assert "--include='*.md'" in text and '"$docs"' in text, (
        "the inline-tag check must scan every docs/**.md file, matching "
        "test_revisions_ledger.py's _docs_dir().rglob('*.md') scope"
    )
    assert "korax-protocol.md" not in text.split("run_ledger_checks")[-1], (
        "the ledger check must not narrow back to a single named document"
    )


def test_the_inline_tag_pattern_matches_the_guards_own_pattern() -> None:
    """Bare `[R-NEXT]` and combined `[R131, R-NEXT]`, and NOT a bracket
    pair with something else in it — the guard's `_INLINE_TAG_RE`
    anchored to one bracket pair (#2510). Compiled and exercised here
    rather than compared as a string, so the two cannot agree textually
    while behaving differently."""
    import re

    text = GATE.read_text(encoding="utf-8")
    match = re.search(r"grep -rhoE '([^']+)'", text)
    assert match, "could not find the inline-tag grep pattern in gate.sh"
    pattern = re.compile(match.group(1))

    assert pattern.search("see [R-NEXT] here")
    assert pattern.search("see [R131, R-NEXT] here")
    assert not pattern.search("see [3] here and R-NEXT unbracketed")
    assert not pattern.search("the R-NEXT convention, unbracketed")


def test_the_battery_sets_the_merge_target_env() -> None:
    """**The omission that bounced R142 (#2634).**

    CI sets `KORAX_MERGE_TARGET` on main. Two guards in
    `test_revisions_ledger.py` skip without it, so a gate that does not
    set it cannot reproduce the one condition it exists to reproduce —
    and renders those two as ordinary skips, which reads as environment
    noise rather than as checks that never ran.
    """
    text = GATE.read_text(encoding="utf-8")
    assert "KORAX_MERGE_TARGET=1" in text, (
        "gate.sh must set KORAX_MERGE_TARGET=1 or its suite legs run a "
        "weaker battery than CI runs on main"
    )
    assert re.search(r"^MERGE_TARGET=1\s*$", text, re.M), (
        "merge-target mode must be the DEFAULT — this tool's argument is a "
        "merge-target sha, and at a merge target the heading is already "
        "renamed"
    )
    assert 'env "${env_args[@]}"' in text, (
        "the env must be applied in run_leg, so EVERY leg carries it rather "
        "than one of them"
    )


def test_the_branch_escape_exists_and_the_mode_is_always_reported() -> None:
    """`--branch` is needed because an unrenamed `## R-NEXT` heading is
    CORRECT on an in-flight branch — the strict guard would fire on the
    one thing the branch is supposed to carry, so a claimant could not
    self-check before delivering.

    And the mode must be REPORTED in both directions. A battery that ran
    the weaker environment must not be indistinguishable from one that
    ran the strict one — this tool's own denominator rule (#2485)
    applied to its environment instead of its legs.
    """
    text = GATE.read_text(encoding="utf-8")
    assert "--branch) MERGE_TARGET=0" in text, "the branch escape is missing"
    report = text.split("report()")[-1]
    assert "KORAX_MERGE_TARGET=1" in report, "strict mode must be reported"
    assert "unset (--branch)" in report, (
        "the weaker mode must announce itself, or a --branch run reads as a "
        "merge-target run"
    )
