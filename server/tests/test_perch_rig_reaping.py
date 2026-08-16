"""The rig reaps its tree — ISSUE #2608's canary, both directions.

**WHY THIS IS A REPO TEST AND NOT A SCRIPT.** The leak was found because
eight orphaned Chrome trees sat on a shared host for up to four days
(#2601). A canary proving the fix, living in `/tmp` and dying with the
session, would be the #2085 defect rebuilt inside the fix for it — the
same trap this claimant caught themselves walking into on `tools/gate.sh`
(#2595).

**WHY IT USES SIGKILL.** A canary that interrupts politely exercises the
`finally` that already worked and proves nothing about the path that
actually leaked. SIGKILL is the only signal that distinguishes the
kernel-level guarantee (PDEATHSIG) from the cooperative one.

**WHY IT COUNTS BY PPID WALK.** `ps | grep chrome` on a developer host
also matches Steam, Discord and other desktop apps — counting those would
make the canary pass or fail for reasons unrelated to the rig (#2611).
Descendants are found by walking `/proc` from the pid we spawned.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="PDEATHSIG and /proc walking are Linux-specific; the rig degrades "
    "to killpg-only elsewhere and this canary cannot measure that here",
)

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent


def _stat_fields(pid: int) -> list[str] | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat[stat.rindex(")") + 2 :].split()


def _alive(pid: int) -> bool:
    return _stat_fields(pid) is not None


def descendants(root: int) -> set[int]:
    """Every live descendant of `root`, inclusive, by PPID walk."""
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        fields = _stat_fields(pid)
        if fields:
            children.setdefault(int(fields[1]), []).append(pid)
    seen: set[int] = set()
    stack = [root]
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        stack.extend(children.get(pid, []))
    return seen


#: A parent that spawns a NON-COOPERATING tree through the real rig.
#: `sleep` does not watch its parent, so this measures the kernel
#: guarantee alone — which is why it is used to pin the fix's BOUNDARY
#: and never as a stand-in for Chrome.
_PARENT = """
import sys, time
sys.path.insert(0, {tests!r})
from perch_rig import PerchRig
rig = PerchRig()
p = rig.spawn(["sh", "-c", "sleep 300 & sleep 300 & sleep 300"])
sys.stdout.write(str(p.pid) + "\\n")
sys.stdout.flush()
time.sleep(300)
"""


def _settled_tree(root: int, stable_for: int = 4, timeout: float = 15.0) -> set[int]:
    """Poll until the descendant count stops changing, then return it.

    A threshold ("more than N") passes the moment the tree is big enough
    to satisfy it, which for Chrome is well before it has finished
    forking — so the canary would reap a partial tree and report a number
    that overstates what it measured.
    """
    deadline = time.time() + timeout
    last, steady = -1, 0
    tree: set[int] = set()
    while time.time() < deadline:
        tree = descendants(root)
        if len(tree) == last:
            steady += 1
            if steady >= stable_for and len(tree) > 1:
                return tree
        else:
            steady = 0
            last = len(tree)
        time.sleep(0.25)
    return tree


def _spawn_parent(tmp_path: Path) -> tuple[subprocess.Popen[str], int]:
    src = _PARENT.format(tests=str(TESTS))
    parent = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(src)],
        stdout=subprocess.PIPE, text=True, start_new_session=True,
    )
    child_pid = int(parent.stdout.readline().strip())  # type: ignore[union-attr]
    for _ in range(40):
        if len(descendants(child_pid)) > 1:
            break
        time.sleep(0.1)
    return parent, child_pid


CHROME = "/opt/google/chrome/chrome"

#: The real thing, spawned through the real rig — the tree the fix is
#: actually for.
_PARENT_CHROME = """
import sys, time
sys.path.insert(0, {tests!r})
from perch_rig import PerchRig
rig = PerchRig()
p, port = rig.chrome({chrome!r}, __import__("pathlib").Path({profile!r}))
sys.stdout.write(str(p.pid) + "\\n")
sys.stdout.flush()
time.sleep(300)
"""


@pytest.mark.browser
@pytest.mark.skipif(not Path(CHROME).exists(), reason="no chrome binary")
def test_the_rig_reaps_a_chrome_tree_when_its_parent_is_sigkilled(tmp_path) -> None:
    """**The path that actually leaked, on the process tree it leaked.**

    `finally` never runs under SIGKILL, so only the kernel can help —
    PDEATHSIG, set at spawn. Before the rig this left the whole tree
    alive: 14 spawned, 14 survivors on real Chrome (#2633 arm A).

    THIS USES REAL CHROME ON PURPOSE. A first draft stood `sh -c "sleep
    & sleep & sleep"` in for the browser and failed, 3 of 4 surviving —
    correctly, because **PDEATHSIG is not inherited across fork** and
    `sleep` does not watch its parent. Chrome's tree collapses because
    Chrome's children exit when the browser process dies; that is
    Chrome's behaviour, not the kernel's. Substituting a cheaper process
    measured a different mechanism than the one being shipped. The
    limitation itself is pinned separately, below.
    """
    profile = tmp_path / "chrome-profile"
    src = _PARENT_CHROME.format(tests=str(TESTS), chrome=CHROME, profile=str(profile))
    parent = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(src)],
        stdout=subprocess.PIPE, text=True, start_new_session=True,
    )
    child_pid = int(parent.stdout.readline().strip())  # type: ignore[union-attr]
    tree = _settled_tree(child_pid)
    # Chrome reaches ~10 within a second and settles at 14 by ~2.7s
    # (measured). A first draft broke at `> 3`, which passed while
    # reaping a PARTIALLY BUILT tree — green, and measuring less than it
    # claimed. Waiting for the count to stop moving is what makes the
    # number in the failure message mean something.
    assert len(tree) >= 10, (
        f"chrome forked only {len(tree)} processes before settling — this "
        "canary is supposed to reap a real tree, and below ~10 it is not "
        "measuring the case that leaked"
    )

    parent.kill()  # SIGKILL: no code of ours runs
    for _ in range(60):
        if not any(_alive(p) for p in tree):
            break
        time.sleep(0.25)

    survivors = [p for p in tree if _alive(p)]
    for pid in survivors:  # never leave the canary's own mess behind
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    shutil.rmtree(profile, ignore_errors=True)
    assert not survivors, (
        f"{len(survivors)} of {len(tree)} chrome processes survived their "
        "parent's SIGKILL — PDEATHSIG is not reaping the tree"
    )


def test_pdeathsig_alone_does_NOT_reap_a_non_cooperating_tree(tmp_path) -> None:
    """**The fix's boundary, pinned as a fact rather than left to be
    rediscovered.**

    PDEATHSIG is not inherited across fork, so the kernel guarantees only
    that the ROOT dies. Chrome's descendants exit anyway because they
    watch the browser process; `sleep` does not, and survives.

    So: under SIGKILL of the parent, the rig reaps a COOPERATING tree
    (Chrome) and cannot reap a non-cooperating one. No in-process fix
    changes that — when pytest is SIGKILLed no code of ours runs at all,
    and a supervising process is the only thing that could. Asserting the
    limitation here means a future rig that spawns something
    non-cooperating meets a red test instead of a fresh leak.
    """
    parent, child_pid = _spawn_parent(tmp_path)
    tree = descendants(child_pid)
    assert len(tree) > 1, "canary did not build a tree"

    parent.kill()
    time.sleep(1.5)
    survivors = [p for p in tree if _alive(p)]
    for pid in survivors:
        try:
            os.kill(pid, 9)
        except OSError:
            pass

    assert survivors, (
        "a non-cooperating tree was fully reaped by PDEATHSIG alone — if "
        "that is genuinely true on this kernel, this boundary has moved "
        "and the rig's documentation is now wrong in the safe direction"
    )


def test_reap_kills_the_tree_on_the_ordinary_path(tmp_path) -> None:
    """The deterministic half: `killpg` with the parent still alive.

    This is the path a passing test takes, and it must not wait on the
    kernel or on a child noticing anything.
    """
    sys.path.insert(0, str(TESTS))
    from perch_rig import PerchRig

    rig = PerchRig()
    proc = rig.spawn(["sh", "-c", "sleep 300 & sleep 300 & sleep 300"])
    for _ in range(40):
        if len(descendants(proc.pid)) > 1:
            break
        time.sleep(0.1)
    tree = descendants(proc.pid)
    assert len(tree) > 1, "canary did not build a tree"

    rig.reap()
    for _ in range(50):
        if not any(_alive(p) for p in tree):
            break
        time.sleep(0.1)
    survivors = [p for p in tree if _alive(p)]
    for pid in survivors:
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    assert not survivors, f"{len(survivors)} survived rig.reap()"


def test_the_control_a_plain_spawn_DOES_leak(tmp_path) -> None:
    """**The control, and the canary is worthless without it.**

    Proving the rig reaps proves the rig reaps. It does NOT prove the
    reaping is what did it — a tree that would have died anyway makes
    every arm above pass for free. This asserts the OLD shape still
    leaks, so the two tests above measure a difference rather than a
    constant (#2518's rule, applied to this fixture).
    """
    src = textwrap.dedent("""
        import subprocess, sys, time
        p = subprocess.Popen(["sh", "-c", "sleep 300 & sleep 300 & sleep 300"])
        sys.stdout.write(str(p.pid) + "\\n"); sys.stdout.flush()
        time.sleep(300)
    """)
    parent = subprocess.Popen(
        [sys.executable, "-c", src], stdout=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    child_pid = int(parent.stdout.readline().strip())  # type: ignore[union-attr]
    for _ in range(40):
        if len(descendants(child_pid)) > 1:
            break
        time.sleep(0.1)
    tree = descendants(child_pid)

    parent.kill()
    time.sleep(1.0)
    survivors = [p for p in tree if _alive(p)]

    # clean up whatever the control leaked, by pid, never by group
    for pid in survivors:
        try:
            os.kill(pid, 9)
        except OSError:
            pass

    assert survivors, (
        "a plain spawn did NOT leak on this host — if that is genuinely "
        "true the reaping tests above prove nothing, because the tree dies "
        "without them"
    )


def test_the_rig_refuses_to_reap_its_own_process_group() -> None:
    """The hazard that nearly shipped: an early probe for this work
    identified the tree by SESSION ID and reaped by session, killing the
    shell running it (#2633). A process spawned WITHOUT
    `start_new_session` inherits the caller's session, so 'reap the
    session' means 'reap yourself'.

    The rig therefore tracks only groups it created and never its own.
    """
    sys.path.insert(0, str(TESTS))
    from perch_rig import PerchRig

    rig = PerchRig()
    assert rig._own_pgid == os.getpgid(0)
    proc = rig.spawn(["sh", "-c", "sleep 5"])
    assert rig._own_pgid not in rig._groups, (
        "the rig tracked its OWN process group for reaping — teardown would "
        "kill the test runner"
    )
    assert os.getpgid(proc.pid) != rig._own_pgid, (
        "spawn did not put the child in its own session"
    )
    rig.reap()


def test_the_profile_directory_is_removed(tmp_path) -> None:
    """#2608 item 4 — the dirs outlive the processes otherwise."""
    sys.path.insert(0, str(TESTS))
    from perch_rig import PerchRig

    rig = PerchRig()
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    (profile / "SingletonLock").write_text("x")
    rig._profiles.append(profile)
    rig.reap()
    assert not profile.exists(), "the chrome profile dir survived reap()"
    shutil.rmtree(profile, ignore_errors=True)


def test_every_browser_test_spawns_through_the_rig() -> None:
    """**The enumeration guard, and #2608 predicted its own need.**

    The issue said: *"a fix applied to one is a fix applied to one; the
    seventh browser test anybody writes will copy the sixth."* That came
    true DURING this delivery — R143 merged
    `test_perch_forum_s4_browser.py` while the fix for the other six was
    being written, and it arrived carrying its own copy of the old
    spawn-and-kill. Its leaked profile dir is how it was noticed.

    So the fix cannot be six (or seven) edits: it needs an assertion that
    no NEW site can reintroduce the pattern. Only `perch_rig.py` may
    spawn Chrome.
    """
    tests = Path(__file__).resolve().parent
    # THE NEEDLE IS ASSEMBLED, AND THIS FILE EXCLUDES ITSELF. A literal
    # `"--user-data-dir"` here matches THIS file's own source, so the
    # guard reported itself as the offender and was red on arrival —
    # the fifth self-matching check this claimant has been lied to by in
    # one session (`pgrep` twice, a substring assertion against a scratch
    # path, a session-id reap). Both defences are kept: the split needle
    # survives being copied elsewhere, the self-exclusion survives being
    # renamed.
    needle = "--user-data" + "-dir"
    offenders = []
    for path in sorted(tests.glob("test_perch_*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        if needle in text:
            offenders.append(path.name)
    assert not offenders, (
        "these tests spawn Chrome directly instead of through `perch_rig`, "
        "so they carry their own teardown and will leak the tree on SIGKILL "
        f"(#2608): {offenders}"
    )
