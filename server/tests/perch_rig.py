"""The browser rig, spawned and reaped in one place — ISSUE #2608.

**THE DEFECT.** Six browser tests each carried their own copy of
spawn-and-kill, and every copy had the same two holes:

  1. `chrome.kill()` reaps the ROOT ONLY. Chrome forks zygotes, a GPU
     process, utility processes and a crashpad handler — **measured at
     14 processes per tree, of which 14 survived** (#2633 arm A).
  2. `finally` does not run when the interpreter is SIGKILLed, and that
     is the path that actually leaked: 8 orphaned trees, 113 processes,
     9.0 GB on the shared host, three of them four days old (#2601).

A `finally` can never cover SIGKILL; only the kernel can. So the fix is
two mechanisms for two different failures, and **both were measured
before being designed around** (#2633):

    A  plain spawn (the old six sites)   14 spawned -> 14 survivors
    B  start_new_session + PDEATHSIG     14 spawned ->  0 survivors
    C  start_new_session + killpg        14 spawned ->  0 survivors

PDEATHSIG covers pytest being SIGKILLed, when no code of ours runs at
all. The explicit `killpg` in teardown covers the normal and exception
paths deterministically, without waiting for Chrome to notice its parent
is gone. One of the two always fires.

**Note what arm B does NOT prove.** The kernel guarantees only that the
ROOT gets SIGKILL — PDEATHSIG is not inherited across fork. The tree
collapsing is Chrome's own behaviour (its children exit when the browser
process dies), visible in the A/B difference. So this holds for Chrome
and must be re-measured before being trusted for any other spawned tree.

**SAFETY, WHICH IS NOT DECORATION HERE.** An early probe for this work
identified "the tree" by SESSION ID and reaped by session — and killed
the shell running it, because a process spawned without
`start_new_session` inherits the caller's session (#2633). So this class
reaps ONLY process groups it created itself, and refuses to signal its
own group under any circumstances. `killpg` is safe here *because the
rig made the group*; it would be dangerous the moment somebody pointed
this at a process they did not spawn.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

#: prctl(2). PR_SET_PDEATHSIG = 1; we ask for SIGKILL so a child cannot
#: decline it the way it could decline SIGTERM.
_PR_SET_PDEATHSIG = 1


def _pdeathsig() -> None:  # pragma: no cover - runs in the forked child
    """Ask the kernel to SIGKILL this child when its parent dies.

    Runs between fork and exec. Deliberately swallows failure: a rig that
    refused to start because a hardening step was unavailable would be a
    worse defect than the leak it prevents, and `killpg` still covers
    every path except the parent being SIGKILLed.
    """
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(
            _PR_SET_PDEATHSIG, signal.SIGKILL
        )
    except Exception:
        pass


def free_port() -> int:
    """An unused localhost port.

    Lived in five of the six sites as an identical private copy; it is
    rig plumbing and belongs with the rig.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class PerchRig:
    """Spawns the browser rig's processes and guarantees their reaping.

    Every spawn goes into its OWN session (hence its own process group),
    so teardown can kill the group rather than the tip. The rig tracks
    the groups it created and will signal nothing else.
    """

    def __init__(self) -> None:
        self._groups: list[int] = []
        self._procs: list[subprocess.Popen[bytes]] = []
        self._profiles: list[Path] = []
        self._own_pgid = os.getpgid(0)

    # ── spawning ──────────────────────────────────────────────────────

    def spawn(self, argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        """Spawn a tracked child in its own session, with PDEATHSIG set."""
        proc = subprocess.Popen(  # type: ignore[call-overload]
            argv,
            start_new_session=True,
            preexec_fn=_pdeathsig if sys.platform.startswith("linux") else None,
            **kwargs,
        )
        self._procs.append(proc)
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:  # already gone; nothing to track
            return proc
        # THE GUARD. `start_new_session` should make this impossible, and
        # if it ever is not, reaping would take our own test runner down
        # with it — which is exactly what the first draft of this work
        # did to a shell (#2633).
        if pgid != self._own_pgid:
            self._groups.append(pgid)
        return proc

    def serve(self, script: Path, server_dir: Path, info: Path) -> subprocess.Popen[bytes]:
        """The seed-and-serve helper every browser test starts with."""
        return self.spawn([sys.executable, str(script), str(server_dir), str(info)])

    def chrome(self, chrome_binary: str, profile: Path) -> tuple[subprocess.Popen[bytes], int]:
        """Headless Chrome on a fresh CDP port, with its profile tracked
        for removal on every exit path (#2608 item 4)."""
        port = free_port()
        self._profiles.append(profile)
        proc = self.spawn(
            [
                chrome_binary, "--headless=new", "--disable-gpu", "--no-sandbox",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}", "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc, port

    # ── reaping ───────────────────────────────────────────────────────

    def reap(self) -> None:
        """Kill every group this rig created, then drop the profiles.

        Idempotent and never raises: teardown that can fail is teardown
        that sometimes does not run.
        """
        for pgid in self._groups:
            if pgid == self._own_pgid:  # unreachable by construction; belt
                continue
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
        self._groups.clear()

        for proc in self._procs:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        self._procs.clear()

        for profile in self._profiles:
            shutil.rmtree(profile, ignore_errors=True)
        self._profiles.clear()
