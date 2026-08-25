"""Acceptance for JOB #3612 — `gate.sh` checks the one thing
`KORAX_MERGE_TARGET=1` asserts and never verified.

Defect of record #3495 (quill), binding form #3497 §3 (slate, ruled
#3483). The tool declared "this is CI's condition on main" against
whatever sha it was handed and never checked the sha could ever BE
main, so a correct battery on the wrong tree reported green with
nothing flagged — measured, not predicted: three branch tips gated in
one night that measured trees that will never exist on main (#3471).

**THE FIXTURES ARE HERMETIC AND THE REMOTE IS REAL.** `origin` is a
local bare repo, so `ls-remote` is genuinely exercised — the real
command, the real ref negotiation — with no network and no reliance on
GitHub being reachable from wherever this suite runs. The one test that
must prove the NO-NETWORK property points `origin` at a path that does
not exist, which is the fastest honest way to be unable to reach a
remote.

**Every test asserts WHICH PATH RAN, never merely "non-zero".** A bash
function that does not exist exits 127, which is non-zero, so a test
asserting "must fail" passes against code that was never written — the
false green this file's sibling nearly shipped at R172. `_declared`
below is the guard, and the exit codes (2 = diverged, 3 =
cannot-resolve) are asserted distinctly so "the network was down"
can never be read as "the delivery diverged".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "tools" / "gate.sh"

DIVERGED = 2
CANNOT_RESOLVE = 3


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _call(snippet: str) -> subprocess.CompletedProcess[str]:
    """Run a real gate.sh function, sourced, in a real bash."""
    return subprocess.run(
        ["bash", "-c", f"set -uo pipefail; source {GATE!s}; {snippet}"],
        capture_output=True, text=True, check=False,
    )


def _predicate(repo: Path, target: str, merge_target: int = 1) -> subprocess.CompletedProcess[str]:
    """Call the REAL predicate against a fixture repo.

    The repo is passed as the primitive's own argument rather than by
    reassigning `REPO_ROOT`, which is `readonly` — the same shape
    `load_floors` already takes, for the same stated reason (#2668,
    #2682): a primitive the suite cannot point at a fixture is one the
    suite has to reimplement, and a reimplementation can agree with a
    bug in the real thing.
    """
    return _call(
        f'TARGET_SHA="{target}"; MERGE_TARGET={merge_target}; '
        f'assert_target_can_become_main "{repo}"'
    )


def _declared(name: str) -> bool:
    return _call(f"declare -F {name} >/dev/null").returncode == 0


# ── the 127 guard, first, because everything below depends on it ──────

def test_the_predicate_functions_are_actually_defined() -> None:
    """**THE FALSE GREEN THIS SUITE WOULD OTHERWISE SHIP.**

    A missing bash function exits 127. Every "this must fail" assertion
    below would therefore PASS against a gate.sh where the predicate was
    never written, or was renamed, or was deleted — the test would be
    green for the one reason it exists to rule out. Asserted first and
    by name so a rename reddens HERE, loudly, instead of silently
    disarming four other tests.
    """
    for name in (
        "resolve_origin_main",
        "assert_target_can_become_main",
        "_merge_target_diverged",
        "_merge_target_unresolved",
    ):
        assert _declared(name), f"gate.sh no longer defines {name}()"


# ── fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def repo_with_origin(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A work repo whose `origin` is a real (local, bare) repository.

    Layout, and every sha below is used by name in a test:

        A ── B          on origin/main   (B is origin's main)
         \\
          C             a branch off A   -> merge-base(C, B) = A != B
        B ── M          M merges C into B -> merge-base(M, B) = B

    `M` is the MATERIALISED merge — the thing the mill actually gates —
    and it is in here so that acceptance 2's "gates clean under
    MERGE_TARGET=1" is proved on the real shape rather than only on a
    branch that happens to be main itself.
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", "."], cwd=work, check=True)
    _git(work, "config", "user.email", "canary@example.invalid")
    _git(work, "config", "user.name", "canary")
    _git(work, "remote", "add", "origin", str(origin))

    (work / "f").write_text("a\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "A")
    sha_a = _git(work, "rev-parse", "HEAD")

    (work / "f").write_text("b\n")
    _git(work, "commit", "-qam", "B")
    sha_b = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "-q", "origin", "main")

    _git(work, "checkout", "-q", "-b", "side", sha_a)
    (work / "g").write_text("c\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "C")
    sha_c = _git(work, "rev-parse", "HEAD")

    _git(work, "checkout", "-q", "main")
    _git(work, "merge", "-q", "--no-ff", "-m", "M", "side")
    sha_m = _git(work, "rev-parse", "HEAD")
    # Left UNPUSHED on purpose: origin's main stays at B, which is
    # exactly the mill's position at a merge — the materialised merge
    # exists locally and main has not moved to it yet.

    return work, {"A": sha_a, "B": sha_b, "C": sha_c, "M": sha_m}


# ── acceptance 1: the defect's own shape, red ─────────────────────────

def test_a_tree_that_can_never_be_main_dies_naming_branch(
    repo_with_origin: tuple[Path, dict[str, str]],
) -> None:
    """**ACCEPTANCE 1 — the night of #3471 reproduced small.**

    `C` is a branch off `A` while origin's main is `B`, so
    merge-base(C, origin/main) is `A`, not `B`. Before this predicate
    that tree gated green under `KORAX_MERGE_TARGET=1` with nothing
    flagged. It must now die, and the message must name `--branch`,
    because a claimant hitting this is not doing anything wrong — they
    are using the wrong mode, and the fix has to be in the message or
    they will reach for `--keep` and a rerun instead.
    """
    work, sha = repo_with_origin
    result = _predicate(work, sha["C"])

    assert result.returncode == DIVERGED, (
        f"a diverged tree must exit {DIVERGED}; got {result.returncode}\n"
        f"{result.stderr}"
    )
    assert "NOT an ancestor" in result.stderr
    assert "--branch" in result.stderr, (
        "the diverged message must name --branch: the reader is in the "
        "wrong mode, and the remedy belongs in the message"
    )
    assert "CANNOT RESOLVE" not in result.stderr, (
        "a diverged tree must not be reported as an unreadable ref — "
        "collapsing the defect into the instrument is how this guard "
        "gets disabled inside a week (#3497 §2)"
    )


# ── acceptance 2: the two shapes that must stay green ─────────────────

def test_the_materialised_merge_gates_clean_under_merge_target(
    repo_with_origin: tuple[Path, dict[str, str]],
) -> None:
    """**ACCEPTANCE 2, the predicate rather than the proxy.**

    `M` is a MERGE COMMIT whose merge-base with origin/main is origin/main.
    It must pass. This is also the test that keeps the refused remedy
    refused: #3497 §2 rejected "is it a merge commit" as over-refusing,
    with quill's live counterexample `979b1d0`, and the reason this
    predicate is stated as an ancestry question is that ancestry is the
    property that actually matters.
    """
    work, sha = repo_with_origin
    result = _predicate(work, sha["M"])
    assert result.returncode == 0, f"the materialised merge must pass\n{result.stderr}"


def test_main_itself_gates_clean_under_merge_target(
    repo_with_origin: tuple[Path, dict[str, str]],
) -> None:
    """origin's main IS its own ancestor. The degenerate case is in here
    because it is the case CI runs: on a push to main the tree being
    checked and the ref being checked against are the same commit, and a
    predicate that got the reflexive case wrong would red every CI run
    on main while looking correct on every branch."""
    work, sha = repo_with_origin
    result = _predicate(work, sha["B"])
    assert result.returncode == 0, f"main itself must pass\n{result.stderr}"


@pytest.mark.parametrize("target", ["C", "M", "B"])
def test_branch_mode_is_a_no_op_for_every_shape(
    repo_with_origin: tuple[Path, dict[str, str]], target: str,
) -> None:
    """**ACCEPTANCE 2's other half — four builder runs' behaviour preserved.**

    Measured placement (#3497 §1): four of five observed runs were
    builders' `--branch` self-checks. If the predicate fired there it
    would break self-checking before delivery, which is the need
    `--branch` exists to serve. Parametrised over the DIVERGED tree too,
    because that is the one where a leaked check would actually bite.
    """
    work, sha = repo_with_origin
    result = _predicate(work, sha[target], merge_target=0)
    assert result.returncode == 0, (
        f"--branch must be a no-op for {target}\n{result.stderr}"
    )
    assert result.stderr == "", "--branch must not even narrate the check"


# ── acceptance 3: cannot-resolve is DISTINGUISHED, and never proceeds ─

def test_an_unreachable_remote_cannot_resolve_and_does_not_proceed(
    repo_with_origin: tuple[Path, dict[str, str]],
) -> None:
    """**ACCEPTANCE 3, and the brief's one BINDING property.**

    *"whatever the deliverer picks must hold the property that a
    no-network run lands in `cannot-resolve`, not in a stale
    `verified-equal`."*

    This is the test that forces the design. A local
    `refs/remotes/origin/main` IS present in this fixture and IS an
    ancestor of the target — so an implementation that read the local
    cache would answer `verified-equal` here and pass. It must not. The
    ref is a cache; the question is about origin.
    """
    work, sha = repo_with_origin
    assert _git(work, "rev-parse", "--verify", "refs/remotes/origin/main"), (
        "fixture precondition: the local cache must exist, or this test "
        "cannot tell a cache-reader from a remote-reader"
    )
    _git(work, "remote", "set-url", "origin", str(work / "does-not-exist.git"))

    result = _predicate(work, sha["B"])

    assert result.returncode == CANNOT_RESOLVE, (
        f"an unreachable origin must exit {CANNOT_RESOLVE}, not "
        f"{result.returncode} — and above all not 0\n{result.stderr}"
    )
    assert "CANNOT RESOLVE" in result.stderr
    assert "refs/heads/main" in result.stderr, (
        "the cannot-resolve message must NAME THE REF (#3497 §3): the "
        "reader's next action depends on which ref could not be read"
    )
    assert "NOT an ancestor" not in result.stderr, (
        "an unreadable ref must not be reported as a diverged tree"
    )


def test_a_remote_without_main_cannot_resolve(
    repo_with_origin: tuple[Path, dict[str, str]],
) -> None:
    """A reachable origin that simply has no `main` is still
    cannot-resolve. `ls-remote` EXITS 0 with EMPTY OUTPUT for a ref that
    does not exist — the failure shape most likely to be read as
    success by a resolver that only checks the exit code."""
    work, sha = repo_with_origin
    _git(work, "push", "-q", "origin", "main:refs/heads/trunk")
    # origin's HEAD must move off `main` first — git refuses to delete
    # the branch a repository's HEAD points at, which is the bare repo
    # protecting itself and nothing to do with what is under test.
    origin = Path(_git(work, "config", "remote.origin.url"))
    subprocess.run(
        ["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/trunk"],
        check=True, capture_output=True,
    )
    _git(work, "push", "-q", "origin", "--delete", "main")

    probe = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=work, capture_output=True, text=True, check=False,
    )
    assert probe.returncode == 0 and probe.stdout.strip() == "", (
        "control: ls-remote is expected to succeed-with-nothing here; if "
        "that ever changes this test is no longer testing what it says"
    )

    result = _predicate(work, sha["B"])
    assert result.returncode == CANNOT_RESOLVE, (
        f"a remote with no main must exit {CANNOT_RESOLVE}\n{result.stderr}"
    )
    assert "CANNOT RESOLVE" in result.stderr


def test_a_sha_resolved_remotely_but_absent_locally_cannot_resolve(
    tmp_path: Path,
) -> None:
    """**THE CI/SHALLOW HAZARD IN MINIATURE, and the subtlest of the three.**

    origin answers with a perfectly good sha that this repo does not
    have — the shape a shallow checkout produces, and the one where an
    implementation is most tempted to fall back to the local cache and
    call it equal. `merge-base` against a missing object cannot answer,
    so the honest outcome is cannot-resolve, not a pass.
    """
    origin = tmp_path / "origin.git"
    # `-b main` PINS origin's HEAD. Without it a bare init takes HEAD from the
    # ambient `init.defaultBranch`, which is host state this fixture does not
    # control: where that default is `master`, origin's HEAD names a branch the
    # seed never creates, `clone` below yields an UNBORN HEAD, and the
    # `rev-parse HEAD` two lines on exits 128 before the test reaches its
    # subject. Green on a `main`-defaulting host, red on the runner — CI #4219.
    # The working repo at the sibling fixture above is already explicit for the
    # same reason; the bare one was not.
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True,
    )

    def clone(name: str) -> Path:
        path = tmp_path / name
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(path)], check=True,
            capture_output=True,
        )
        _git(path, "config", "user.email", "canary@example.invalid")
        _git(path, "config", "user.name", "canary")
        return path

    seed = clone("seed")
    (seed / "f").write_text("a\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "A")
    _git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")

    mine = clone("mine")
    local_head = _git(mine, "rev-parse", "HEAD")

    # A second seat pushes; my clone never fetches it.
    (seed / "f").write_text("b\n")
    _git(seed, "commit", "-qam", "B")
    _git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")
    remote_head = _git(seed, "rev-parse", "HEAD")

    assert subprocess.run(
        ["git", "cat-file", "-e", f"{remote_head}^{{commit}}"],
        cwd=mine, capture_output=True, check=False,
    ).returncode != 0, "fixture precondition: the new sha must be absent locally"

    result = _predicate(mine, local_head)
    assert result.returncode == CANNOT_RESOLVE, (
        f"a remotely-known but locally-absent main must exit "
        f"{CANNOT_RESOLVE}, not {result.returncode}\n{result.stderr}"
    )
    assert "not in this repo" in result.stderr
    assert "fetch" in result.stderr, (
        "the message must name the remedy: this one is fixed by fetching, "
        "unlike the other two cannot-resolve shapes"
    )


# ── acceptance 4: three distinct exit paths, structurally ─────────────

def test_the_three_outcomes_are_three_exit_paths_not_one_die() -> None:
    """**ACCEPTANCE 4, asserted on the artifact.**

    *"The three-outcome structure is asserted as three distinct exit
    paths, not one die with two texts interpolated."* The distinction
    matters because a single die with an interpolated reason is one
    edit away from becoming a single message, and then the defect and
    the instrument are indistinguishable again — which is the failure
    #3497 §2 refused by name.
    """
    text = GATE.read_text(encoding="utf-8")
    body = text.split("\nassert_target_can_become_main() {", 1)
    assert len(body) == 2, "gate.sh no longer declares the predicate"
    body = body[1].split("\n}\n", 1)[0]

    assert body.count("_merge_target_diverged") == 1
    assert "_merge_target_unresolved" in body
    assert body.count("return 0") == 2, (
        "exactly two `return 0`: the --branch no-op and the verified-equal "
        "outcome. A third is a path that proceeds without deciding"
    )
    assert "die " not in body, (
        "the outcomes must not route through the generic die(): it exits 2 "
        "for everything, which is precisely the collapse this JOB forbids"
    )


def test_the_two_failures_carry_different_exit_codes() -> None:
    """The defect and the instrument are distinguishable BY A MACHINE,
    not only by a human reading prose. The mill reads exit codes; "the
    network was down" must never be reportable as "the delivery
    diverged"."""
    text = GATE.read_text(encoding="utf-8")

    def code_of(fn: str) -> str:
        body = text.split(f"\n{fn}() {{", 1)[1].split("\n}\n", 1)[0]
        return body.rsplit("exit ", 1)[1].strip().splitlines()[0]

    assert code_of("_merge_target_diverged") == str(DIVERGED)
    assert code_of("_merge_target_unresolved") == str(CANNOT_RESOLVE)


# ── the resolution order, stated and enforced ─────────────────────────

def test_the_resolver_asks_origin_and_never_the_local_cache() -> None:
    """**THE RESOLUTION ORDER, enforced rather than documented.**

    Remote truth, not the local ref. `refs/remotes/origin/main` is a
    CACHE: reading it offline answers `verified-equal` against a main
    that moved hours ago, and the brief forbids exactly that stale
    green. The behavioural proof is
    `test_an_unreachable_remote_cannot_resolve_and_does_not_proceed`;
    this is the structural guard that stops a well-meaning "fall back to
    the local ref when the network is down" from being added later,
    which would reintroduce the defect while looking like a robustness
    fix.
    """
    text = GATE.read_text(encoding="utf-8")
    body = text.split("\nresolve_origin_main() {", 1)[1].split("\n}\n", 1)[0]
    assert "ls-remote" in body
    assert "refs/remotes" not in body, (
        "the resolver must not read the local remote-tracking ref — that "
        "is a cache, and a cache read offline is a stale verified-equal"
    )


def test_the_remote_call_is_bounded() -> None:
    """**MEASURED, NOT ASSUMED — and the measurement is why this test exists.**

    `git ls-remote` against a host whose packets are blackholed does not
    fail, it HANGS: 2m14s on a stock Linux TCP stack, measured against
    203.0.113.1 (TEST-NET-3). DNS failure returns in 12ms, so the fast
    shape hides the slow one. A precondition that hangs for over two
    minutes before the battery starts is its own defect, so the call is
    bounded and the bound is asserted here — an unbounded resolver still
    passes every behavioural test in this file, because they all use
    remotes that answer immediately.
    """
    text = GATE.read_text(encoding="utf-8")
    body = text.split("\nresolve_origin_main() {", 1)[1].split("\n}\n", 1)[0]
    assert "timeout" in body, "the ls-remote call must be bounded"
    assert "BatchMode" in body, (
        "a credential prompt turns a no-network run into a hang waiting on "
        "a human who is not there"
    )


# ── the wiring, without which every test above is on an orphan ────────

def test_the_predicate_is_actually_called_by_the_entry_function() -> None:
    """**THE GAP THE TESTS ABOVE LEAVE.** Every assertion in this file
    calls the predicate directly, so all of them keep passing if the
    entry function stops calling it — a unit test on an orphaned
    function is a check that cannot fail for the reason it exists
    (#111). Asserted off the artifact because the alternative is running
    a twelve-leg battery per fixture.
    """
    text = GATE.read_text(encoding="utf-8")
    body = text.split("\nmain() {", 1)[1].split("\n}\n", 1)[0]
    assert "assert_target_can_become_main" in body, (
        "the entry function no longer calls the predicate — the check is "
        "defined and never runs, which reads green forever"
    )
    order = body.index("assert_target_can_become_main")
    assert order < body.index("run_battery"), (
        "the predicate must run BEFORE the battery: it is a precondition, "
        "and a check that fires after twelve legs have run has already "
        "spent everything it exists to save"
    )
    assert order > body.index("trap cleanup"), (
        "it must run AFTER the cleanup trap is armed, or its exit leaks "
        "the worktree it just created (#2756's family)"
    )


def test_the_report_proves_the_predicate_ran() -> None:
    """The mode line has always ASSERTED "CI's condition on main". Now
    that the claim is checked, the report says so and names the sha it
    checked against — the same denominator discipline this tool applies
    to its legs, applied to its own precondition."""
    report = GATE.read_text(encoding="utf-8").split("report()")[-1]
    assert "predicate:" in report
    assert "MERGE_TARGET_MAIN_SHA" in report, (
        "the report must name the sha the predicate verified against, or "
        "it is announcing a check rather than evidencing one"
    )
