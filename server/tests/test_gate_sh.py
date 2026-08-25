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

def test_the_battery_declares_twelve_legs() -> None:
    """M comes from the DECLARATION, which is the whole point.

    The gavel settled M = 10 at #2514: 3 suites + browser + 3 CI-parity
    + 2 lane + shallow. #2680/#2682 cut an eleventh, ledger-disposition,
    and named the denominator move as a deliberate act rather than a
    side effect — this assertion is that act, restated as a check. A
    report that counted what it happened to run could not tell a
    shrunken battery from a whole one (#2482).

    **M MOVES 11 -> 12 AT JOB #3160**, and this line is that act. The
    twelfth is `floors`: the calibration load, which is DECIDED (it
    parses a file, runs nothing, cannot flake) and runs before every
    guarded leg. It is a leg rather than a silent precondition because a
    missing calibration must be visible in the report as a red, not as
    an absence a reader has to notice — the same reason the battery
    reports `SKIPPED` and `NOT REACHED` rather than omitting them.
    """
    legs = _bash_array("LEG_NAMES")
    assert len(legs) == 12, f"expected 12 declared legs, found {len(legs)}: {legs}"
    assert len(set(legs)) == len(legs), f"duplicate leg name in {legs}"
    assert "ledger-disposition" in legs
    assert "floors" in legs


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


# ── the browser leg is UNCONDITIONAL (JOB #3210) ──────────────────────
#
# THREE TESTS WERE DELETED HERE, and what they proved is worth stating
# because it is the reason the predicate they guarded is gone:
#
#   * the predicate fired on every live perch root, both directions
#   * `server/korax/perch/**` ALONE missed a driver-only change — the
#     gap the set carried until #2520, real instance R131/`b789438`
#     (#2518 §2, #2525)
#   * it named no directory that does not exist
#
# All three tested whether a SKIP PREDICATE was correct. There is no
# skip predicate now: the leg runs whenever CI would, which is always
# (#3017's direction). **A test of a retired rule passes forever and
# guards nothing**, so they retire with it — and the gap they recorded
# is preserved in `gate.sh` beside the tombstone, where anyone
# reintroducing a predicate will meet it.


def test_the_browser_leg_has_no_skip_path_at_all() -> None:
    """The replacement guard, and it is a source property because the
    behaviour is now unconditional.

    Red-check: restoring the `if browser_is_owed` form makes this fail
    on the `skip_leg browser` line, which is the only thing that could
    reintroduce a silent gate-vs-CI asymmetry.
    """
    text = (REPO / "tools" / "gate.sh").read_text(encoding="utf-8")
    assert "skip_leg browser" not in text, (
        "the browser leg acquired a skip path again — CI runs it "
        "unconditionally, so any skip is a gate that reports green about "
        "a leg CI will run on the merge (#2902 §2 measured five of six "
        "queued branches skipping it)"
    )
    assert "browser_is_owed" not in text.replace("# `browser_is_owed()`", ""), (
        "the retired predicate is back as live logic"
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


# ── the count contract (#2953/#2954/#2963; floors of record #2994) ─────
# These are the acceptance for JOB #2968 part (c). Where a property can be
# read off the artifact it is asserted there (DECIDED); where it must be
# exercised, the real bash function is called against a fixture rather
# than reimplemented in Python — a test that restates the logic can agree
# with a bug in it (#2668's canary rule, the same reason leg 11's suite
# calls gate.sh's own primitives).


def _bash_assoc(name: str) -> dict[str, str]:
    """Pull a `declare -A NAME=( [k]=v ... )` table out of gate.sh."""
    text = GATE.read_text(encoding="utf-8")
    match = re.search(rf"^declare -A {name}=\(\n(.*?)^\)$", text, re.M | re.S)
    assert match, f"{name} is not declared as an associative array in tools/gate.sh"
    return dict(re.findall(r"\[([\w-]+)\]=(\S+)", match.group(1)))


def _call_gate_fn(snippet: str) -> subprocess.CompletedProcess[str]:
    """Run a real gate.sh function, sourced, in a real bash."""
    return subprocess.run(
        ["bash", "-c", f"set -uo pipefail; source {GATE!s}; {snippet}"],
        capture_output=True, text=True, check=False,
    )


def test_the_collect_appends_no_verbosity_flag() -> None:
    """THE -qq TRAP, GUARDED STRUCTURALLY. Every floored leg already
    passes `-q`; appending a second one gives pytest `-qq`, which
    suppresses the collected-count line entirely, so the collect parses
    as nothing and the leg reddens for a reason unrelated to its tests.

    That is not hypothetical — it is what the first cut of this function
    did, and it was caught only because the CONTROL went red identically
    to the treatment. A comment would rely on the next person reading it.
    """
    text = GATE.read_text(encoding="utf-8")
    match = re.search(r'out="\$\( cd "\$WT" && "\$@" (.*?) 2>&1 \)"', text)
    assert match, "collect_selected no longer builds its command the expected way"
    appended = match.group(1).split()
    assert appended == ["--collect-only"], (
        "collect_selected must append ONLY --collect-only; a verbosity flag "
        f"here makes the leg's own -q into -qq and blinds the parse: {appended}"
    )


def test_the_count_check_runs_adjacent_to_each_leg() -> None:
    """#2963: per invocation, beside the leg — a battery that checks
    counts once in a preamble asserts about a run other than the one it
    reports."""
    text = GATE.read_text(encoding="utf-8")
    run_leg = re.search(r"^run_leg\(\) \{\n(.*?)^\}$", text, re.M | re.S)
    assert run_leg, "run_leg is no longer a top-level function"
    assert "assert_counts" in run_leg.group(1), (
        "run_leg does not call assert_counts, so the count contract has "
        "moved away from the invocation it describes"
    )


def test_the_two_reads_come_from_different_sources() -> None:
    """The floor reads the artifact; the identity reads the run. If both
    came from the run's own output the identity would be arithmetic
    rather than evidence."""
    text = GATE.read_text(encoding="utf-8")
    collect = re.search(r"^collect_selected\(\) \{\n(.*?)^\}$", text, re.M | re.S)
    outcomes = re.search(r"^sum_outcomes\(\) \{\n(.*?)^\}$", text, re.M | re.S)
    assert collect and outcomes, "the two count readers are no longer both present"
    assert "--collect-only" in collect.group(1), "the decided read no longer collects"
    assert "$LOGDIR" not in collect.group(1), (
        "the decided read is reading the leg's log — that is the sampled "
        "source, and using it for both makes the identity a tautology"
    )
    assert '"$log"' in outcomes.group(1), "the sampled read no longer reads the leg log"


@pytest.mark.parametrize(
    "summary, expected",
    [
        ("940 passed, 8 deselected in 76.46s", "940"),
        ("938 passed, 2 skipped, 8 deselected in 75.68s", "940"),
        ("1 failed, 5 passed in 2.10s", "6"),
        ("235 passed, 2 skipped in 18.00s", "237"),
        ("1 error, 3 passed in 1.00s", "4"),
    ],
)
def test_sum_outcomes_counts_every_outcome_and_no_deselection(
    tmp_path: Path, summary: str, expected: str,
) -> None:
    """The real function, against real summary lines.

    Rows two and four are the load-bearing ones: the SAME total from a
    different passed/skipped split. That is why the identity survives the
    battery flipping its own mode, and why the floor could not live on
    `passed` (#2993).

    `deselected` is deliberately not summed — it is the complement of
    selected, not an outcome.
    """
    log = tmp_path / "leg.log"
    log.write_text(f"....\n{summary}\n", encoding="utf-8")
    result = _call_gate_fn(f'sum_outcomes "{log}"')
    assert result.stdout == expected, (
        f"sum_outcomes({summary!r}) gave {result.stdout!r}, want {expected!r}"
    )


def test_sum_outcomes_refuses_a_log_with_no_outcome_line(tmp_path: Path) -> None:
    """Fail closed. An unreadable log must not read as zero outcomes,
    which would satisfy no identity and look like catastrophic loss, nor
    as success."""
    log = tmp_path / "leg.log"
    log.write_text("collected nothing useful\n", encoding="utf-8")
    result = _call_gate_fn(f'sum_outcomes "{log}"')
    assert result.returncode != 0, "sum_outcomes returned success on an unparseable log"
    assert result.stdout == "", f"it also emitted a count: {result.stdout!r}"


# ── the shallow leg's declared set (#2831, three states ruled #3017) ────


def test_the_shallow_leg_declares_both_markers() -> None:
    text = GATE.read_text(encoding="utf-8")
    for name in ("SHALLOW_MARKER", "SHALLOW_REENTRANT"):
        assert re.search(rf"^readonly {name}=", text, re.M), (
            f"{name} is not declared at file scope — inside a function a "
            "readonly explodes on the second call, which the acceptance "
            "suite makes by sourcing this script"
        )


def test_the_shallow_leg_fails_closed_on_an_empty_declared_set() -> None:
    """The one state that would let this leg go green having run nothing
    — which is the exact defect it was rebuilt to stop. `clients/cli/tests`
    was never going to fail for being shallow; an empty declared set is
    the same vacuity with the honest-looking cause."""
    text = GATE.read_text(encoding="utf-8")
    leg = re.search(r"^run_shallow_leg\(\) \{\n(.*?)^\}$", text, re.M | re.S)
    assert leg, "run_shallow_leg is no longer a top-level function"
    body = leg.group(1)
    assert "${#runnable[@]} -eq 0" in body, (
        "no empty-set guard: the leg can run nothing and report PASS"
    )
    assert "rc -eq 5" in body, (
        "pytest exit 5 (nothing collected) is not handled separately — "
        "'the files were there but nothing ran' is a different repair"
    )


def test_the_shallow_leg_reports_the_re_entrant_exclusion() -> None:
    """Never a silent drop (#3017). A leg that quietly omits the hard
    case reports a denominator it did not earn."""
    text = GATE.read_text(encoding="utf-8")
    leg = re.search(r"^run_shallow_leg\(\) \{\n(.*?)^\}$", text, re.M | re.S)
    assert leg, "run_shallow_leg is no longer a top-level function"
    body = leg.group(1)
    assert "reentrant" in body and "excluded_note" in body, (
        "the re-entrant partition is gone; an excluded file would vanish "
        "from the report rather than being named"
    )
    assert "$excluded_note" in body, "the exclusion is computed but never reported"


# ── the floors file (JOB #3160, option C ruled #3098) ──────────────────
# The calibration moved out of `gate.sh` into `tools/gate-floors.txt` so
# the gating seat can maintain the DATA at each merge without editing the
# instrument it is recused from (#2503), and so every floor carries the
# sha it was measured at (#3100/#3102 — a constant does not travel, it
# sits, and what decays is the ability to recover why it was right).

FLOORS = REPO / "tools" / "gate-floors.txt"


def _floor_rows() -> list[list[str]]:
    rows = []
    for line in FLOORS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        rows.append(stripped.split())
    return rows


def test_the_hardcoded_floor_table_is_gone() -> None:
    """The retirement, asserted rather than assumed. A leftover literal
    table would shadow the file silently and the two would drift."""
    text = GATE.read_text(encoding="utf-8")
    match = re.search(r"^declare -A LEG_FLOOR=\((.*?)\)", text, re.M | re.S)
    assert match, "LEG_FLOOR is no longer declared at all — the report reads it"
    body = match.group(1).strip()
    assert body == "", (
        "LEG_FLOOR still carries literal entries; the calibration is the "
        f"file's job now and two sources of truth is one too many: {body!r}"
    )


def test_every_floor_row_names_a_declared_leg() -> None:
    """Dead calibration reads like coverage — the same defect as a floor
    declared for a leg that does not run (guarded above for the old
    table, and now for the file)."""
    legs = set(_bash_array("LEG_NAMES"))
    orphans = sorted({row[0] for row in _floor_rows()} - legs)
    assert orphans == [], f"floor rows for legs that do not exist: {orphans}"


def test_every_floor_row_carries_its_provenance() -> None:
    """THE BINDING CLAUSE (#3100), now with the pair (JOB #3239). A bare
    number is the `939` defect — retired twice in one day, both times
    unrecoverable without going and looking. But ONE sha was not enough
    either: it says where a number was anchored, not what reproduces it,
    which is why R167's true anchor could only be written in prose
    (#3226 §4). Seven fields, and the base+delivery pair is what makes a
    row decidable rather than merely attributable."""
    for row in _floor_rows():
        assert len(row) == 7, (
            f"row has {len(row)} fields, want 7 "
            f"(leg floor base delivery revision band date): {' '.join(row)}"
        )
        leg, floor, base, delivery, revision, band, date = row
        assert floor.isdigit(), f"{leg}: floor is not a number: {floor}"
        assert re.fullmatch(r"[0-9a-f]{7,40}", base), f"{leg}: base not a sha: {base}"
        assert re.fullmatch(r"[0-9a-f]{7,40}", delivery), (
            f"{leg}: delivery not a sha: {delivery}"
        )
        assert re.fullmatch(r"R\d+", revision), f"{leg}: not a revision: {revision}"
        assert band.startswith("band:"), f"{leg}: not a band id: {band}"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", date), f"{leg}: not a date: {date}"


@pytest.mark.parametrize(
    "planted, needle",
    [
        # THE OLD SHAPE IS THE FIRST CASE ON PURPOSE. It is a well-formed
        # row of the format this delivery replaced, and it must be refused
        # as a shape rather than tolerated as a shorter dialect.
        ("suite-cli 335 e5a658ac R164 band:x 2026-08-16", "want 7"),
        ("suite-cli 335 e5a658ac R164", "want 7"),
        ("suite-cli lots e5a658ac bd463450 R167 band:x 2026-08-16", "not a number"),
        ("suite-cli 335 R167 bd463450 R167 band:x 2026-08-16", "base is not a sha"),
        ("suite-cli 335 e5a658ac 2026-08-16 R167 band:x 2026-08-16",
         "delivery is not a sha"),
        ("suite-imaginary 1 e5a658ac bd463450 R167 band:x 2026-08-16",
         "not a declared leg"),
    ],
)
def test_load_floors_refuses_each_malformed_shape(
    tmp_path: Path, planted: str, needle: str,
) -> None:
    """The real bash function against a real planted file, per row shape.

    Each refusal names a DIFFERENT cause: a parse that answered "bad
    file" to all three would be one check wearing three names, and the
    controls could not tell which clause fired (#3151).
    """
    staged = tmp_path / "gate-floors.txt"
    staged.write_text(FLOORS.read_text(encoding="utf-8") + planted + "\n", encoding="utf-8")
    result = _call_gate_fn(
        f'if load_floors "{staged}"; then echo OK; else echo "$FLOORS_ERROR"; fi'
    )
    assert "OK" not in result.stdout, f"the parser accepted {planted!r}"
    assert needle in result.stdout, (
        f"refused {planted!r} but not for the stated reason: {result.stdout!r}"
    )


def test_load_floors_refuses_an_absent_file(tmp_path: Path) -> None:
    """A floor is not a default. An empty directory is the shape a fresh
    checkout or a botched merge produces."""
    result = _call_gate_fn(
        f'if load_floors "{tmp_path}/nonexistent.txt"; then echo OK; else echo "$FLOORS_ERROR"; fi'
    )
    assert "OK" not in result.stdout, "the parser invented a calibration"
    assert "missing" in result.stdout, result.stdout


def test_load_floors_accepts_the_shipped_file() -> None:
    """CONTROL for the four refusals above. A parser that rejected
    everything would pass all of them and measure nothing."""
    result = _call_gate_fn(
        'if load_floors; then echo "OK ${#LEG_FLOOR[@]}"; else echo "$FLOORS_ERROR"; fi'
    )
    assert result.stdout.startswith("OK "), result.stdout
    assert int(result.stdout.split()[1]) == len(_floor_rows())


def test_a_failed_calibration_reds_every_leg_not_just_guarded_ones() -> None:
    """FAIL WIDE. With no file the battery cannot know which legs were
    supposed to be guarded, and that ignorance IS the defect — so a leg
    carrying no floor when the file is present must red too, rather than
    the battery deciding from a table it could not read that it did not
    matter."""
    text = GATE.read_text(encoding="utf-8")
    fn = re.search(r"^assert_counts\(\) \{\n(.*?)^\}$", text, re.M | re.S)
    assert fn, "assert_counts is no longer a top-level function"
    body = fn.group(1)
    guard = body.index('if [ -n "$FLOORS_ERROR" ]')
    floor_read = body.index('local floor=')
    assert guard < floor_read, (
        "the FLOORS_ERROR guard runs AFTER the floor lookup, so a leg with "
        "no floor returns green before the guard is reached"
    )


def test_the_floors_leg_is_declared_and_runs_before_the_guarded_legs() -> None:
    """Order is load-bearing: a guarded leg that runs first would assert
    against a calibration that had not been read."""
    assert "floors" in _bash_array("LEG_NAMES"), "the floors leg is not declared"
    text = GATE.read_text(encoding="utf-8")
    battery = re.search(r"^run_battery\(\) \{\n(.*?)^\}$", text, re.M | re.S)
    assert battery, "run_battery is no longer a top-level function"
    body = battery.group(1)
    assert body.index("run_floors_leg") < body.index("run_leg suite-server"), (
        "the floors leg does not run before the first guarded leg"
    )


# ── the harness line discriminates (JOB #3210 clause 3) ───────────────


def test_the_report_names_the_harness_that_produced_it() -> None:
    """Presence. Necessary, and on its own it proves nothing — see the
    next test, which is the one that can fail for the right reason."""
    text = (REPO / "tools" / "gate.sh").read_text(encoding="utf-8")
    assert 'echo "harness:' in text, (
        "report() must name the gate.sh that produced it, or two reports "
        "from different harnesses are indistinguishable whenever the "
        "delivery leaves the leg count unchanged (#3200's near-miss)"
    )


def test_two_harnesses_produce_DIFFERENT_harness_lines(tmp_path: Path) -> None:
    """THE PROPERTY, not the presence — and this is the distinction I
    struck from my own acceptance list an hour before writing it
    (#3181/#3182): a canary that shows a line EXISTS in both runs
    without comparing them cannot go red for the reason it was written.

    So this extracts the computation from `gate.sh` and evaluates it
    from two distinct files with distinct content, then asserts the two
    lines DIFFER. Both halves matter: same content at different paths
    must differ (path), and same path is impossible here so the content
    hash carries the rest.
    """
    text = (REPO / "tools" / "gate.sh").read_text(encoding="utf-8")
    start = text.index("  local harness_path harness_hash")
    end = text.index("\n", text.index('echo "harness:', start))
    snippet = text[start:end].replace("  local ", "  ")

    outs = []
    for i, filler in enumerate(("# harness A\n", "# harness B — different bytes\n")):
        script = tmp_path / f"h{i}" / "gate.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("#!/usr/bin/env bash\n" + filler + snippet + "\n",
                          encoding="utf-8")
        proc = subprocess.run(["bash", str(script)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        line = proc.stdout.strip()
        assert line.startswith("harness:"), line
        assert "unavailable" not in line, f"hash did not compute: {line}"
        outs.append(line)

    assert outs[0] != outs[1], (
        f"two different harnesses produced the SAME line — the dual-harness "
        f"procedure would compare one to itself and say nothing:\n{outs[0]}"
    )
    # and the hash half discriminates on its own, not just the path
    assert outs[0].split("sha256 ")[1] != outs[1].split("sha256 ")[1], (
        "the content hash did not differ between different bytes"
    )


# ── completeness under merge-target (#3880, ruled #3883) ──────────────
# A leg that never ran is not a leg that passed, and under merge-target
# it is not a gate that may exit 0. These call gate.sh's OWN decisions
# against a planted leg table rather than running a twelve-leg battery
# per fixture — the same reason the count-contract block above calls the
# real bash: a test that restates the rule can agree with a bug in it.


def _planted_statuses(overrides: dict[str, str]) -> dict[str, str]:
    """Every declared leg PASS, with named overrides.

    The leg names are read out of the script; this suite never carries a
    copy of them, so it cannot pass while the two drift apart (#2482).
    """
    table = {name: "PASS" for name in _bash_array("LEG_NAMES")}
    for name, state in overrides.items():
        assert name in table, f"{name!r} is not a declared leg in gate.sh"
        table[name] = state
    return table


def _status_rc(overrides: dict[str, str], *, merge_target: int) -> int:
    """The real exit decision, over a planted leg table."""
    assigns = " ".join(
        f"LEG_STATUS[{n}]={v};" for n, v in _planted_statuses(overrides).items()
    )
    proc = _call_gate_fn(
        "declare -F battery_status >/dev/null || exit 99; "
        f"{assigns} MERGE_TARGET={merge_target}; battery_status"
    )
    # A MISSING function exits 127 — non-zero — which would satisfy every
    # "must be non-zero" assertion below for entirely the wrong reason.
    # Fail loudly on the rename instead of passing on the accident.
    assert proc.returncode != 99, (
        "gate.sh no longer defines battery_status; this suite exercises the "
        "real decision and must not report green against a missing function"
    )
    return proc.returncode


def _verdict(
    ran: int, failed: int, skipped: int, missing: int, *, merge_target: int
) -> str:
    """The real final line, over planted counts."""
    proc = _call_gate_fn(
        "declare -F verdict_line >/dev/null || exit 99; "
        f"MERGE_TARGET={merge_target}; "
        f"verdict_line {ran} {failed} {skipped} {missing}"
    )
    assert proc.returncode != 99, "gate.sh no longer defines verdict_line"
    return proc.stdout.strip()


def test_merge_target_exits_non_zero_when_a_leg_skipped() -> None:
    """(i) THE DEFECT. `KORAX_MERGE_TARGET=1` already marks the battery
    that must be complete, so completeness is a property of the mode and
    not of anyone's memory (#3883 §1). Before this fix the same status
    came back from a run that skipped a leg and one that did not, so no
    supervisor or automation reading the status could tell them apart
    (#3880 §2).
    """
    assert _status_rc({"ledger-disposition": "SKIP"}, merge_target=1) != 0, (
        "a merge-target battery with a skipped leg exited 0 — the status "
        "channel cannot distinguish it from a complete run"
    )


def test_merge_target_exits_non_zero_when_a_leg_not_reached() -> None:
    """(iv) 'Not reached' is the same channel mismatch one column over in
    the same `legs` line; a fix closing one and leaving the other builds
    the next instance of this issue into itself (#3883 §2).
    """
    assert _status_rc({"ledger-disposition": "MISSING"}, merge_target=1) != 0


def test_branch_runs_still_exit_zero_on_a_legitimate_skip() -> None:
    """(iii) THE CONTROL, and the whole reason this is scoped to the mode.
    A builder's `--branch` run skips the two merge-target ledger guards by
    design — reddening those would make self-checking before delivery
    impossible, which is the need `--branch` exists to serve.
    """
    assert _status_rc({"ledger-disposition": "SKIP"}, merge_target=0) == 0


def test_a_red_leg_still_reds_the_gate_in_both_modes() -> None:
    """The new guard must sit BESIDE the old one, not replace it."""
    assert _status_rc({"suite-server": "FAIL"}, merge_target=1) != 0
    assert _status_rc({"suite-server": "FAIL"}, merge_target=0) != 0


def test_a_complete_battery_still_exits_zero_in_both_modes() -> None:
    """THE CANARY. A guard that reds everything passes every assertion
    above and is worthless; this is the one that must stay QUIET when
    nothing is wrong (#112/#921).
    """
    assert _status_rc({}, merge_target=1) == 0
    assert _status_rc({}, merge_target=0) == 0


def test_the_verdict_leads_with_incompleteness_under_merge_target() -> None:
    """(i)'s report half — #3883 §3, stated as a property.

    The mill read `fail=` off a battery that had skipped a leg and took
    the gate for clean. The prose and status channels must not disagree
    about severity, so what LEADS the line is correctness, not layout.
    """
    line = _verdict(11, 0, 1, 0, merge_target=1)
    assert re.match(r"GATE INCOMPLETE\b", line), (
        f"the merge-target verdict must LEAD with the incompleteness: {line!r}"
    )
    assert "1 of 12" in line, f"the verdict must carry its denominator: {line!r}"


def test_the_verdict_leads_with_incompleteness_when_a_leg_is_not_reached() -> None:
    """(iv)'s report half. Before this, a not-reached leg with no red legs
    printed `GATE FAILED — 0 of 11 ran legs red` — true in status, wrong
    in the property, and it names a redness that did not happen.
    """
    line = _verdict(11, 0, 0, 1, merge_target=1)
    assert re.match(r"GATE INCOMPLETE\b", line), line


def test_a_red_leg_is_still_named_when_the_battery_is_also_incomplete() -> None:
    """Leading with incompleteness must not HIDE a failure — a reader
    grepping for the red must still find it on the same line.
    """
    line = _verdict(10, 1, 1, 0, merge_target=1)
    assert re.match(r"GATE INCOMPLETE\b", line), line
    assert "red" in line, f"a failed leg vanished from the verdict: {line!r}"


def test_the_branch_verdict_is_byte_identical_to_today() -> None:
    """(iii)'s report half. `--branch` is unchanged in BOTH channels."""
    assert _verdict(11, 0, 1, 0, merge_target=0) == (
        "GATE fail=0 — but 1 of 12 legs did NOT run (named above)"
    )
    assert _verdict(12, 0, 0, 0, merge_target=0) == (
        "GATE fail=0 — 12 of 12 legs, none skipped, none missing"
    )


def test_the_clean_verdict_is_unchanged_under_merge_target() -> None:
    """(ii) A complete, green merge-target run reads exactly as before."""
    assert _verdict(12, 0, 0, 0, merge_target=1) == (
        "GATE fail=0 — 12 of 12 legs, none skipped, none missing"
    )


def test_the_completeness_decisions_are_actually_wired_in() -> None:
    """THE GAP THE TESTS ABOVE LEAVE. Every assertion in this block calls
    `battery_status` and `verdict_line` directly, so all of them keep
    passing if the entry point stops calling one and goes back to
    deciding for itself. A unit test on an orphaned function is a check
    that cannot fail for the reason it exists (#111).

    Asserted off the artifact because the alternative is a twelve-leg
    battery per assertion; the end-to-end run is the gate's own job.
    """
    text = GATE.read_text(encoding="utf-8")

    entry = text.split("\nmain() {", 1)
    assert len(entry) == 2, "gate.sh no longer declares an entry function"
    body = entry[1].split("\n}", 1)[0]
    assert "battery_status" in body, (
        "the entry function no longer calls battery_status — the exit "
        "status is being decided somewhere this suite does not test"
    )
    assert "LEG_STATUS" not in body, (
        "the entry function reads the leg table again; the exit decision "
        "lives in battery_status and must not be restated beside it"
    )

    summary = text.split("report()")[-1]
    assert "verdict_line" in summary, (
        "the summary no longer calls verdict_line — the final line is "
        "being composed somewhere this suite does not test"
    )


def test_a_not_reached_leg_reds_the_gate_in_both_modes() -> None:
    """THE MILL'S QUESTION AT #3982 §3, answered by measurement.

    They asked whether the `missing > 0, failed = 0` branch had the same
    prose/status seam one column over — the line was lead-wrong, so was
    the exit code wrong too? It was not: `MISSING` has always redded the
    gate in BOTH modes, and unlike a skip it should, because "not
    reached" means the battery did not complete rather than that a leg
    declined to run. Only the LINE was wrong there, and only under
    merge-target.

    Asserted rather than left to the reader because the seam this whole
    delivery closes is two channels disagreeing, and "I checked and this
    one agrees" is worth exactly as much as the check that proves it.
    """
    assert _status_rc({"ledger-disposition": "MISSING"}, merge_target=1) != 0
    assert _status_rc({"ledger-disposition": "MISSING"}, merge_target=0) != 0
