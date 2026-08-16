"""`tools/deploy_predicate.sh` — the conditional-restart decision, tested
against a local git fixture (JOB #2558 item 1, #2553 §3, #2556's caveat).

The script is standalone precisely so it is testable without SSH or a
live board: two commits in a throwaway repo stand in for "previously
deployed" and "target". Both directions (#112) plus the fails-closed
cases the brief names explicitly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "deploy_predicate.sh"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message, "--quiet")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "fixture-repo"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    (root / "server" / "korax" / "perch").mkdir(parents=True)
    (root / "server" / "korax" / "__init__.py").write_text("# init\n")
    (root / "server" / "korax" / "api.py").write_text("# api\n")
    (root / "server" / "korax" / "perch" / "index.html").write_text("<html></html>\n")
    (root / "docs").mkdir()
    (root / "docs" / "README.md").write_text("# docs\n")
    return root


def run_predicate(repo_dir: Path, deployed_sha: str, target_sha: str) -> str:
    result = subprocess.run(
        [str(SCRIPT), str(repo_dir), deployed_sha, target_sha],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"the predicate's exit code is never the decision — always 0. "
        f"got {result.returncode}, stderr={result.stderr!r}"
    )
    return result.stdout.strip()


# -- both directions (#112) --------------------------------------------------


def test_a_server_py_change_says_restart(repo: Path) -> None:
    base = _commit(repo, "base")
    (repo / "server" / "korax" / "api.py").write_text("# api, changed\n")
    target = _commit(repo, "touch api.py")

    decision = run_predicate(repo, base, target)
    assert decision.startswith("restart ")
    assert "server/korax/api.py" in decision
    assert "1 file(s)" in decision


def test_a_perch_only_change_says_no_restart(repo: Path) -> None:
    base = _commit(repo, "base")
    (repo / "server" / "korax" / "perch" / "index.html").write_text("<html>v2</html>\n")
    target = _commit(repo, "touch perch asset only")

    decision = run_predicate(repo, base, target)
    assert decision.startswith("no-restart ")
    assert "0 files" in decision


def test_a_docs_only_change_says_no_restart(repo: Path) -> None:
    base = _commit(repo, "base")
    (repo / "docs" / "README.md").write_text("# docs, changed\n")
    target = _commit(repo, "touch docs only")

    decision = run_predicate(repo, base, target)
    assert decision.startswith("no-restart ")


def test_both_perch_and_server_py_changed_still_says_restart(repo: Path) -> None:
    """Any server/korax/**.py touch triggers restart, regardless of what
    else moved in the same commit — the predicate is a union, not a
    majority vote."""
    base = _commit(repo, "base")
    (repo / "server" / "korax" / "perch" / "index.html").write_text("<html>v2</html>\n")
    (repo / "server" / "korax" / "api.py").write_text("# api, changed\n")
    target = _commit(repo, "touch both")

    decision = run_predicate(repo, base, target)
    assert decision.startswith("restart ")
    assert "server/korax/api.py" in decision


def test_no_change_at_all_says_no_restart(repo: Path) -> None:
    """same..same is a legal, if pointless, invocation — the diff is
    empty and the predicate must not treat it as indeterminate."""
    base = _commit(repo, "base")
    decision = run_predicate(repo, base, base)
    assert decision.startswith("no-restart ")


# -- fails closed (#2547) -----------------------------------------------------


def test_missing_deployed_sha_fails_closed(repo: Path) -> None:
    target = _commit(repo, "base")
    result = subprocess.run(
        [str(SCRIPT), str(repo), "", target],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip().startswith("restart indeterminate:")


def test_missing_all_arguments_fails_closed() -> None:
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip().startswith("restart indeterminate:")


def test_unresolvable_deployed_sha_fails_closed(repo: Path) -> None:
    target = _commit(repo, "base")
    decision = run_predicate(repo, "0" * 40, target)
    assert decision.startswith("restart indeterminate:")
    assert "not a resolvable commit" in decision


def test_unresolvable_target_sha_fails_closed(repo: Path) -> None:
    base = _commit(repo, "base")
    decision = run_predicate(repo, base, "0" * 40)
    assert decision.startswith("restart indeterminate:")
    assert "not a resolvable commit" in decision


def test_nonexistent_repo_dir_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    decision = run_predicate(missing, "0" * 40, "1" * 40)
    assert decision.startswith("restart indeterminate:")
    assert "does not exist" in decision


# -- self-describing with denominators (#2485) --------------------------------


def test_the_restart_decision_names_which_files_matched(repo: Path) -> None:
    base = _commit(repo, "base")
    (repo / "server" / "korax" / "api.py").write_text("# changed 1\n")
    (repo / "server" / "korax" / "store.py").write_text("# new file\n")
    target = _commit(repo, "touch two files")

    decision = run_predicate(repo, base, target)
    assert "2 file(s)" in decision
    assert "server/korax/api.py" in decision
    assert "server/korax/store.py" in decision


def test_the_no_restart_decision_names_the_range(repo: Path) -> None:
    base = _commit(repo, "base")
    (repo / "docs" / "README.md").write_text("# changed\n")
    target = _commit(repo, "docs only")

    decision = run_predicate(repo, base, target)
    assert base in decision
    assert target in decision
