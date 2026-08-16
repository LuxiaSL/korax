"""`tools/deploy.sh`, run for real (not just its predicate) — both
directions of the conditional restart (#112, JOB #2558 item 1).

`ssh` is faked to execute its remote command locally against a fixture
"VPS" checkout; `sudo`/`systemctl` are faked to no-ops; `korax` is faked
to answer the three calls deploy.sh actually makes. This proves the
FULL SCRIPT's control flow — not just `deploy_predicate.sh` in
isolation (see test_deploy_predicate.py) — takes the no-restart branch
when only perch/docs moved and the restart branch when server code did,
using the script's own git-pull/notice/restart machinery, unmocked.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
DEPLOY_SH = TOOLS / "deploy.sh"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture()
def fake_bin(tmp_path: Path) -> Path:
    """A PATH directory standing in for ssh/sudo/systemctl/korax, none of
    which this suite may actually invoke against anything real."""
    bindir = tmp_path / "bin"
    bindir.mkdir()

    # ssh HOST "remote command" -> run the command locally. The fixture
    # "VPS" is just another local directory, so the remote command's own
    # `cd '$KORAX_VPS_DIR'` works unmodified.
    _write_exec(bindir / "ssh", """#!/usr/bin/env bash
shift
exec bash -c "$*"
""")
    _write_exec(bindir / "sudo", """#!/usr/bin/env bash
exec "$@"
""")
    _write_exec(bindir / "systemctl", """#!/usr/bin/env bash
exit 0
""")
    # korax answers the three calls deploy.sh makes: `post` (twice, one
    # piped through a JSON id extractor) and `conformance` (verify loop).
    _write_exec(bindir / "korax", """#!/usr/bin/env bash
for arg in "$@"; do
  if [ "$arg" = "conformance" ]; then
    exit 0
  fi
done
echo '{"id": 999}'
exit 0
""")
    return bindir


@pytest.fixture()
def host_and_vps(tmp_path: Path) -> tuple[Path, Path]:
    """A bare `origin` both host_dir and vps_dir track, matching real
    topology — deploy.sh's `git -C $KORAX_HOST_DIR pull --ff-only` (the
    client leg) needs host_dir to have a remote to pull from, same as
    vps_dir does. Tests push to origin after committing into host, so
    vps's pull (via the fake ssh) has real work to fast-forward through."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--quiet", "--bare", "-b", "main", str(origin)],
        check=True, capture_output=True,
    )

    host = tmp_path / "host"
    host.mkdir()
    _git(host, "init", "--quiet", "-b", "main")
    _git(host, "config", "user.email", "test@example.invalid")
    _git(host, "config", "user.name", "test")
    (host / "server" / "korax" / "perch").mkdir(parents=True)
    (host / "server" / "korax" / "api.py").write_text("# api v1\n")
    (host / "server" / "korax" / "perch" / "index.html").write_text("<html>v1</html>\n")
    _git(host, "remote", "add", "origin", str(origin))
    _git(host, "add", "-A")
    _git(host, "commit", "-m", "base", "--quiet")
    _git(host, "push", "--quiet", "-u", "origin", "main")

    vps = tmp_path / "vps"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(vps)],
        check=True, capture_output=True,
    )
    _git(vps, "config", "user.email", "test@example.invalid")
    _git(vps, "config", "user.name", "test")

    return host, vps


def _run_deploy(fake_bin: Path, host: Path, vps: Path, **env_extra: str) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["KORAX_DEPLOY_PROFILE"] = "fake-profile"
    env["KORAX_VPS"] = "fake-host"  # ignored by the fake ssh
    env["KORAX_VPS_DIR"] = str(vps)
    env["KORAX_HOST_DIR"] = str(host)
    env["KORAX_SERVICE"] = "korax"
    env["KORAX_URL"] = "http://fake.invalid"
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(DEPLOY_SH)],
        capture_output=True, text=True, env=env, timeout=30,
    )


def test_a_perch_only_change_pulls_but_never_restarts(fake_bin: Path, host_and_vps) -> None:
    host, vps = host_and_vps
    (host / "server" / "korax" / "perch" / "index.html").write_text("<html>v2</html>\n")
    _git(host, "add", "-A")
    _git(host, "commit", "-m", "perch only", "--quiet")
    _git(host, "push", "--quiet", "origin", "main")

    result = _run_deploy(fake_bin, host, vps)

    assert result.returncode == 0, result.stderr
    assert "no-restart" in result.stdout
    assert "restart required" not in result.stdout
    assert "no restart, no notice posted" in result.stdout
    # the real behaviour, not just the printed claim: the VPS checkout
    # actually advanced, and systemctl was never invoked.
    assert _git(vps, "rev-parse", "HEAD") == _git(host, "rev-parse", "HEAD")
    assert "systemctl" not in result.stdout  # nothing DRY-RUN-echoed either, since this is a real run


def test_a_server_py_change_notices_pulls_and_restarts(fake_bin: Path, host_and_vps) -> None:
    host, vps = host_and_vps
    (host / "server" / "korax" / "api.py").write_text("# api v2\n")
    _git(host, "add", "-A")
    _git(host, "commit", "-m", "server change", "--quiet")
    _git(host, "push", "--quiet", "origin", "main")

    result = _run_deploy(fake_bin, host, vps)

    assert result.returncode == 0, result.stderr
    assert "restart required" in result.stdout
    assert "notice posted as #999" in result.stdout
    assert "board answering" in result.stdout
    assert _git(vps, "rev-parse", "HEAD") == _git(host, "rev-parse", "HEAD")


def test_an_unreachable_vps_fails_closed_to_restart(fake_bin: Path, host_and_vps) -> None:
    """The deployed-sha ssh read fails (unreachable host) -> the
    predicate gets an empty deployed_sha -> indeterminate -> restart."""
    host, vps = host_and_vps
    (host / "server" / "korax" / "perch" / "index.html").write_text("<html>v2</html>\n")
    _git(host, "add", "-A")
    _git(host, "commit", "-m", "perch only, but vps is unreachable", "--quiet")
    _git(host, "push", "--quiet", "origin", "main")

    bindir = fake_bin.parent / "bin-broken"
    bindir.mkdir()
    _write_exec(bindir / "ssh", "#!/usr/bin/env bash\nexit 255\n")
    for name in ("sudo", "systemctl", "korax"):
        (bindir / name).write_bytes((fake_bin / name).read_bytes())
        (bindir / name).chmod((fake_bin / name).stat().st_mode)

    result = _run_deploy(bindir, host, vps)

    assert result.returncode != 0  # the ssh pull/restart calls also fail(255) under set -e
    assert "indeterminate" in result.stdout
    assert "restart required" in result.stdout


def test_a_host_checkout_lagging_origin_still_restarts(fake_bin: Path, host_and_vps) -> None:
    """The defect the mill's bounce found (#2705): deploy.sh used to
    resolve the predicate's target sha from the HOST CHECKOUT's own
    HEAD, but both pulls (the VPS's and the host's own step 3) land on
    origin/main — so whenever the host checkout lags origin, the
    decided pair and the deployed pair diverged, and a required restart
    could be silently skipped. That divergence is the common case, not
    an edge case: step 3 exists specifically because the host checkout
    lags origin routinely.

    The other two integration tests always commit into `host` and then
    push, so `host == origin/main` in every one of their fixtures —
    structurally unable to construct the state that matters. This test
    constructs it: the server-code-changing commit reaches `origin`
    through a THIRD clone, never through `host`'s own working tree, so
    `host`'s checkout genuinely lags when deploy.sh runs.
    """
    host, vps = host_and_vps
    origin = host.parent / "origin.git"

    other = host.parent / "other-clone"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(other)],
        check=True, capture_output=True,
    )
    _git(other, "config", "user.email", "test@example.invalid")
    _git(other, "config", "user.name", "test")
    (other / "server" / "korax" / "api.py").write_text(
        "# api v2 -- landed without host ever pulling\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "server change, merged by someone else", "--quiet")
    _git(other, "push", "--quiet", "origin", "main")

    # The divergence itself: host's checkout is untouched.
    assert _git(host, "rev-parse", "HEAD") != _git(other, "rev-parse", "HEAD")

    result = _run_deploy(fake_bin, host, vps)

    assert result.returncode == 0, result.stderr
    assert "restart required" in result.stdout, (
        "deciding from host's stale HEAD instead of origin/main would "
        f"have said no-restart here — the exact defect #2705 found.\n"
        f"{result.stdout}"
    )
    assert "notice posted as #999" in result.stdout
    # both checkouts land on the real target, not host's stale HEAD
    assert _git(vps, "rev-parse", "HEAD") == _git(other, "rev-parse", "HEAD")
    assert _git(host, "rev-parse", "HEAD") == _git(other, "rev-parse", "HEAD")
