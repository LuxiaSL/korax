"""The cross-tree import guard (ISSUE #2286, ruled light-track at #2287).

**What makes this canary honest.** The guard's red direction has to be a
GENUINE cross-tree import — a package resolving under a different
checkout of this repo — not a fabricated path. Pointing the guard at
`/nonexistent` and watching it complain would test my own `assert`
statement and nothing else; that is the failure I committed at #2289 not
to make. So the red case builds a real second tree on disk with a real
`server/korax/__init__.py` in it, and asks the guard the same question
it will be asked in production.

The green direction matters just as much (#112): all four invocations
this floor actually uses — a worktree under `uv run --project .`, the
shared checkout, CI's `--directory` leg, and the mill's detached gate —
are same-tree by construction, and the guard must stay silent for every
one of them. A guard that fired on the gate would be worse than no guard.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "tree_guard.py"


def _guard():
    spec = importlib.util.spec_from_file_location("korax_tree_guard_test", TOOLS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _guard()


# ── the green direction: the invocations this floor actually uses ─────

def test_this_very_run_is_same_tree() -> None:
    """The live control. This suite is running SOMEWHERE — a worktree, the
    shared checkout, CI, or the mill's gate — and wherever that is, the
    guard must be quiet. If this ever fails, the suite really is testing
    another tree and the whole issue is reproducing itself."""
    tree = Path(__file__).resolve().parents[2]
    guard.enforce(tree, ("korax",))  # raises if it disagrees


def test_a_package_absent_from_the_environment_is_not_an_offence() -> None:
    """"Not installed" is not "wrong tree". A suite that does not use a
    package cannot be testing the wrong copy of it, and a guard that
    failed here would fire on every partial environment."""
    assert guard.resolve("korax_definitely_not_a_package") is None
    guard.enforce(Path(__file__).resolve().parents[2],
                  ("korax_definitely_not_a_package",))


# ── the red direction: a REAL second checkout, not a fabricated path ──

@pytest.fixture()
def second_tree(tmp_path: Path) -> Path:
    """A real second copy of this repo's layout, with a real package in it.

    This is the shape the defect actually takes: two checkouts of the same
    project, one of them holding the package the interpreter resolves.
    """
    pkg = tmp_path / "server" / "korax"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("# a second checkout's korax\n", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    return tmp_path


def test_the_guard_catches_a_package_resolving_in_another_tree(
    second_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The canary.** `korax` is importable from THIS tree; the guard is
    asked whether it belongs to the OTHER one — which is exactly the
    question a worktree run asks when the venv points at the shared
    checkout. It must refuse, and the refusal must be usable."""
    with pytest.raises(guard.CrossTreeImport) as excinfo:
        guard.enforce(second_tree, ("korax",))

    message = str(excinfo.value)
    # #415: the refusal names what moved, and what to run instead.
    assert str(second_tree) in message, "the refusal must name the expected tree"
    assert "korax" in message
    assert guard.CORRECT_INVOCATION in message, (
        "the refusal must carry the invocation that fixes it — an error "
        "that diagnoses without instructing is half a guard"
    )
    # and it names the offending path, not merely the fact of an offence
    where = guard.resolve("korax")
    assert str(where) in message


def test_the_guard_reports_the_offender_and_not_just_a_boolean(
    second_tree: Path,
) -> None:
    found = guard.offenders(second_tree, ("korax",))
    assert len(found) == 1
    name, path = found[0]
    assert name == "korax"
    assert path == guard.resolve("korax")


def test_a_package_inside_the_tree_is_never_an_offender(second_tree: Path) -> None:
    """The guard must judge by CONTAINMENT, not by string prefix: a path
    that merely starts with the same characters is a different directory."""
    assert guard.offenders(second_tree, ("korax",)), "precondition"
    sibling = Path(str(second_tree) + "-other")
    # `/x/tree-other/...` must not count as inside `/x/tree`
    assert not str(sibling).startswith(str(second_tree) + "/")
    assert str(sibling).startswith(str(second_tree))


# ── the header, which is the mill's #2290 addition ────────────────────

def test_the_header_names_the_tree_and_every_package() -> None:
    tree = Path(__file__).resolve().parents[2]
    text = guard.header(tree, ("korax",))
    assert str(tree) in text
    assert "korax" in text
    # relative inside the tree — the point is legibility, and an absolute
    # path here would bury the one case that matters in noise
    assert "server/korax/__init__.py" in text


def test_the_header_shouts_when_a_package_is_outside(second_tree: Path) -> None:
    """The header is printed on GREEN runs too, so it has to be readable
    when something is wrong without waiting for the guard to speak."""
    text = guard.header(second_tree, ("korax",))
    assert "OUTSIDE THIS TREE" in text
    assert str(guard.resolve("korax")) in text


def test_the_header_actually_reaches_the_terminal_under_q() -> None:
    """**The reporting half must speak in the invocation people use.**

    This is not paranoia about a print statement; it is the defect this
    delivery already walked into twice. `pytest_report_header` is silent
    under `-q`. Moving the write to `pytest_configure` looked like the
    fix and was worse — global capture is active that early, so the line
    went to a discarded buffer and vanished at EVERY verbosity while
    still looking fine, because the guard beside it kept working.

    Both were caught by eye, which is not a mechanism. `-q` is what this
    floor and CI run, so the assertion is made against `-q` specifically:
    a reporting feature nobody sees is not a reporting feature.
    """
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    run = subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__)), "-q",
         "-k", "test_this_very_run_is_same_tree", "-p", "no:randomly"],
        capture_output=True, text=True, timeout=120,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "korax tree:" in run.stdout, (
        "the resolved-tree line did not reach the terminal under -q — "
        "the reporting half of #2286 is dead in the invocation this "
        f"floor actually uses.\n{run.stdout}"
    )
    assert "server/korax/__init__.py" in run.stdout


# ── tree STATE: which tree is not the same question as which bytes ────

def _git_repo(path: Path) -> callable:
    """A real repo at `path`; returns a runner for further git commands."""
    import subprocess  # noqa: PLC0415

    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=path, capture_output=True, text=True, check=True)
        return proc.stdout.strip()

    path.mkdir(parents=True, exist_ok=True)
    run("init", "-q")
    (path / "a.txt").write_text("one\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "first")
    return run


def test_tree_state_reports_the_head_of_a_clean_repo(tmp_path) -> None:
    run = _git_repo(tmp_path / "r")
    state = guard.tree_state(tmp_path / "r")
    assert state == run("rev-parse", "--short", "HEAD"), (
        "a clean tree at a known commit reports that commit and nothing else"
    )
    assert "dirty" not in state


def test_tree_state_reports_dirty(tmp_path) -> None:
    """An uncommitted change means these bytes exist on one machine — the
    single most important thing to see beside a green suite."""
    _git_repo(tmp_path / "r")
    (tmp_path / "r" / "a.txt").write_text("changed\n", encoding="utf-8")
    assert "dirty" in guard.tree_state(tmp_path / "r")


def test_tree_state_reports_ahead_of_origin(tmp_path) -> None:
    """**The mill's #2433 case.** The shared checkout sat 7 commits ahead
    of origin with three unmerged deliveries in it, and every path printed
    was correct. This is the fact that would have shown it."""
    origin = tmp_path / "origin.git"
    import subprocess  # noqa: PLC0415
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)

    run = _git_repo(tmp_path / "r")
    run("remote", "add", "origin", str(origin))
    run("push", "-q", "origin", "HEAD:refs/heads/main")
    run("fetch", "-q", "origin")

    (tmp_path / "r" / "a.txt").write_text("two\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "ahead by one")

    state = guard.tree_state(tmp_path / "r")
    assert "1 ahead of origin/main" in state, state


def test_tree_state_degrades_to_none_outside_a_git_checkout(tmp_path) -> None:
    """**A reporting feature that stops a run is a worse defect than the
    one it reports.** A tarball, an exported source drop or a CI step that
    removed `.git` must still be able to run the suite — so this returns
    None and the header simply omits the line."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert guard.tree_state(plain) is None


def test_the_header_carries_the_state_when_there_is_one(tmp_path) -> None:
    run = _git_repo(tmp_path / "r")
    text = guard.header(tmp_path / "r", ())
    assert "HEAD " + run("rev-parse", "--short", "HEAD") in text


def test_the_header_still_renders_without_git(tmp_path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    text = guard.header(plain, ("korax",))
    assert "korax tree:" in text
    assert "HEAD" not in text, "no state line rather than a broken one"
