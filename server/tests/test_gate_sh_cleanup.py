"""`gate.sh` reaps its legs before deleting their scratch — ISSUE #2611.

**THE DEFECT, DISCLOSED AT ITS OWN GATE (#2663).** The first cut of
`tools/gate.sh` removed the worktree and `rm -rf`'d the scratch tree
without touching the processes running inside it. On an interrupted run
that is strictly worse than doing nothing: an in-flight browser leg keeps
its ~14 Chrome processes AND has its profile dir deleted underneath it.
The mill's #2601 describes a gate killed mid-flight twice in one session,
which is exactly this path.

**WHY AN INTERRUPT CANARY AND NOT A CODE READ.** A teardown asserted and
not exercised is the thing itself — the sentence this claimant has been
handed and has earned twice tonight. Reading `reap_legs` and agreeing it
looks right is how the original shipped.

**WHY IT COUNTS BY PROCESS GROUP.** Not `ps | grep`: on a developer host
that also matches the operator's desktop (#2611). The canary knows the
pgid it created and counts only that.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="/proc process-group inspection is Linux-specific",
)

# korax: needs-git-history — reads the real repository (`rev-parse HEAD`
# below) rather than a planted fixture repo, so the shallow leg counts it.
#
# korax: invokes-the-gate — AND IS THEREFORE EXCLUDED FROM RUNNING INSIDE
# THE SHALLOW CLONE, declared here rather than dropped quietly. `REPO` is
# `parents[2]` of this file, so inside the leg's depth-1 clone it resolves
# to the CLONE, and the `bash $GATE` below would launch a full battery
# there — whose own shallow leg clones again and runs this file again.
#
# THE HAZARD IS PROSPECTIVE AND THIS DELIVERY IS WHAT WOULD ARM IT (the
# mill, #3021): before part (a) the shallow leg ran `clients/cli/tests`
# only, so `server/tests` never entered the clone and nothing could
# recurse. Widening the leg is the change that makes the exclusion
# necessary, which is why it lands in the same delivery.
#
# THERE IS A BRAKE, AND IT CANNOT REACH PAST DEPTH+1. The correction is
# the mill's at #3021 and it matters practically. This test does bound
# its child — 180 s readiness, `SOAK_S`, SIGTERM, `wait(60)`, then a
# `finally` that SIGKILLs the gate's whole session. But that reap is
# SESSION-scoped and each level spawns the next with
# `start_new_session=True`, so level 0 reaps session S1 and is blind to
# level 1's S2, at every depth. **A timeout is therefore not a
# mitigation** — bounding each level's wall clock is what this file
# already does, and a grandchild survives it. Only a sentinel the child
# can observe would close it.
#
# AND THE SESSION-SCOPING IS ITSELF A DELIBERATE SAFETY FIX — see
# `_session_members`' own docstring below: reaping by session is what
# stopped this canary killing the operator's shell (#2633). Two correct
# decisions composing badly under a condition neither anticipated; not a
# bug in either.
#
# The leg reports this file as `declared, NOT RUN (re-entrant)`, so the
# escape never gets a first level. A re-entry sentinel is not owed by
# #2968 (desk, #3017) and becomes a deck candidate only if something ever
# needs this test running inside clones — at which point the sentinel is
# built FIRST and the demonstration runs against it (the mill, #3021 §3,
# declining the live demonstration as the seat that would be asked).
REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "tools" / "gate.sh"


def _alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def _cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return ""


def _real_pytest_pids(sid: int) -> list[int]:
    """The pytest LEG PROCESSES in the gate's session — not their wrappers.

    **This predicate is the canary's denominator and it was wrong twice.**

      1. A plain member count is satisfied during worktree setup by
         transient `git` processes; a first draft used `> 3` and passed in
         3.7s having never reached a leg.
      2. `"pytest" in cmdline` is satisfied by `uv run --project . pytest
         -q server/tests` — the WRAPPER's argv names pytest before any
         pytest exists. Measured against unfixed `gate.sh`: the argv match
         lands at 0.5s, the real interpreter at 1.0s. A canary that fired
         on the first was interrupting a gate that had not started a leg.

    So both halves are required: pytest named in argv AND the executable
    is a python/pytest binary rather than `uv`.
    """
    out = []
    for pid in _session_members(sid):
        cmd = _cmdline(pid)
        if "pytest" not in cmd:
            continue
        argv = cmd.split()
        if not argv:
            continue
        exe = Path(argv[0]).name
        if exe.startswith("python") or exe == "pytest":
            out.append(pid)
    return out


def _session_members(sid: int) -> list[int]:
    """Everything in the gate's SESSION.

    NOT its process group: the fix deliberately puts each leg in its own
    GROUP (`set -m`), so counting the gate's group sees one bash process
    however many legs are running. A first draft of this canary did
    exactly that and its own guard caught it — measuring the wrong set
    would have made the readiness check impossible to satisfy.
    """
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            if os.getsid(pid) == sid:
                out.append(pid)
        except OSError:
            continue
    return out


# ── the structural half ───────────────────────────────────────────────

def test_cleanup_reaps_before_it_deletes() -> None:
    """Order is the whole defect: deleting first leaves live processes
    with their scratch removed underneath them."""
    text = GATE.read_text(encoding="utf-8")
    body = text[text.index("cleanup() {") :]
    # Named before indexed: a bare `.index()` on absent text raises
    # ValueError, which fails the test but tells a reader nothing about
    # what the script was missing.
    assert "reap_legs" in body, "cleanup() never reaps the legs at all (#2611)"
    assert 'rm -rf "$SCRATCH"' in body, "cleanup() no longer removes the scratch tree"
    reap_at = body.index("reap_legs")
    rm_at = body.index('rm -rf "$SCRATCH"')
    assert reap_at < rm_at, (
        "cleanup() must reap the legs BEFORE removing the scratch tree "
        "(#2611) — otherwise a live Chrome loses its profile dir mid-run"
    )


def test_the_trap_covers_the_signals_an_interrupted_gate_receives() -> None:
    """An EXIT-only trap does not cover every way a gate is killed, and
    'killed mid-flight' is the path that leaked (#2601)."""
    text = GATE.read_text(encoding="utf-8")
    assert "trap cleanup EXIT INT TERM" in text, (
        "the trap must cover INT and TERM as well as EXIT"
    )


def test_every_leg_is_tracked_as_a_process_group() -> None:
    """`set -m` makes each background leg a group leader (pgid == pid),
    which is what lets teardown reach pytest's children rather than
    pytest alone. Every leg path must do it — the first cut of this fix
    covered `run_leg` and left the lane and shallow legs spawning
    untracked subshells."""
    text = GATE.read_text(encoding="utf-8")
    assert text.count("set -m") >= 3, (
        "each leg path (run_leg, the lane, the shallow clone) must put its "
        f"leg in its own process group; found {text.count('set -m')}"
    )
    assert text.count("LEG_PGIDS+=(") >= 3, "a leg path is not tracking its group"


def test_reap_never_targets_its_own_group() -> None:
    """The hazard that killed a shell earlier in this work (#2633): a
    reaper that cannot exclude itself takes its caller down."""
    text = GATE.read_text(encoding="utf-8")
    assert "reap_legs() {" in text, "there is no reap_legs to guard (#2611)"
    reap = text[text.index("reap_legs() {") : text.index("cleanup() {")]
    assert '"$pgid" = "$$"' in reap, (
        "reap_legs must refuse to signal the script's own process group"
    )


def test_every_tracked_group_is_forgotten_once_its_leg_is_waited() -> None:
    """A pgid outlives its leg as a REUSABLE NUMBER.

    `cleanup` runs on the normal exit path too, by which time every leg
    has been waited. A list that still names them has teardown
    `kill -KILL -- -<pgid>` against groups the kernel may since have
    handed to somebody else — on a host the charter calls shared. The
    tracking and the forgetting must therefore be balanced: every leg
    path that adds its group must drop it again after `wait`.
    """
    text = GATE.read_text(encoding="utf-8")
    tracked = text.count("LEG_PGIDS+=(")
    forgotten = text.count('forget_leg "$')
    # The floor first: `forgotten == tracked` is satisfied by 0 == 0, so
    # on its own it would go green on a script that tracks nothing at all.
    assert tracked >= 3, f"only {tracked} leg paths track a group at all"
    assert forgotten == tracked, (
        f"{tracked} leg paths track a process group but {forgotten} forget "
        "it after waiting — a stale pgid is a stranger's group by teardown"
    )
    assert "forget_leg() {" in text, "forget_leg is called but never defined"


# ── the interrupt canary, which is the one that matters ───────────────

#: Seconds to let a leg run before interrupting. NOT a guess at "long
#: enough to be safe": measured against unfixed `gate.sh`, a gate killed
#: at ~0.5s leaves nothing behind, because a `uv` half a second into
#: resolution dies the moment its scratch venv is removed. Ten seconds
#: puts pytest into real work, which is the state #2601 describes.
SOAK_S = 10
#: Seconds to wait after SIGTERM before counting survivors. Bounded at
#: BOTH ends by measurement on unfixed `gate.sh`: survivors are present
#: at +1, +3, +10 and +20 and gone by +40 — they die OF the `rm -rf`,
#: which is the defect, not the gate reaping them. A canary that waited
#: 40s would pass against unfixed code and measure nothing.
GRACE_S = 5


def test_an_interrupted_gate_leaves_no_leg_processes_running() -> None:
    """**Exercised, not asserted, and the control was run.**

    Start a real `gate.sh`, let a leg reach real work, SIGTERM it, and
    require every process the gate had running to be gone.

    **THIS CANARY'S OWN FIRST DRAFT WAS VACUOUS AND PASSED AGAINST THE
    UNFIXED SCRIPT.** Three defects, all of them counting defects:

      1. it waited on `"pytest" in cmdline`, satisfied by the `uv`
         wrapper's argv at 0.5s — see `_real_pytest_pids`;
      2. it captured the candidate survivor set AT READINESS, so every
         process spawned afterwards — which is every actual leg — was
         not even eligible to be counted as a survivor. Measured: the
         readiness snapshot missed the pytest interpreter by 0.5s;
      3. it therefore interrupted at ~0.5s, before a leg existed.

    Proving a check fires proves it fires. Only running it against the
    UNFIXED thing proves it measures — the control run at `9f13f15`
    (`trap cleanup EXIT` only, no `set -m`, no `reap_legs`) leaves 2
    survivors, of which one is the pytest interpreter still executing
    out of a `.venv` the gate has already deleted. That is #2611 exactly.
    """
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
        check=True,
    ).stdout.strip()

    proc = subprocess.Popen(
        ["bash", str(GATE), head, "--branch"],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    gate_sid = os.getsid(proc.pid)

    try:
        deadline = time.time() + 180
        while time.time() < deadline and not _real_pytest_pids(gate_sid):
            time.sleep(0.5)
        first_seen = _real_pytest_pids(gate_sid)

        # Let the leg reach real work rather than interrupting a process
        # that has barely execed.
        soak_end = time.time() + SOAK_S
        while time.time() < soak_end:
            time.sleep(0.5)

        # CAPTURED AT INTERRUPT TIME, not at readiness. A leg's own group
        # is separate from the gate's (that is the fix), so the SESSION is
        # the set that spans them.
        at_interrupt = set(_session_members(gate_sid))
        legs_at_interrupt = _real_pytest_pids(gate_sid)

        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)
        time.sleep(GRACE_S)

        survivors = [p for p in at_interrupt if _alive(p) and p != os.getpid()]
        # Read the cmdlines HERE. The `finally` below kills these
        # processes, and /proc/<pid>/cmdline of a dead process is empty —
        # a first run of this canary reported `[(1622089, ''), (1622167,
        # '')]`, which names the defect's size and nothing about it.
        survivor_desc = [(p, _cmdline(p)[:70]) for p in survivors]
    finally:
        # Never leave the canary's own mess behind, on any exit path —
        # including the assertion failures below, which by construction
        # fire exactly when there ARE processes to clean up.
        #
        # THE GUARD, and it is not decoration: reaping BY SESSION is the
        # shape that killed a shell during this work (#2633), because a
        # child spawned without `start_new_session` inherits its caller's
        # session. `start_new_session=True` above should make this
        # impossible; if it ever is not, refusing beats taking pytest
        # itself down mid-assertion.
        if gate_sid not in (os.getsid(0), os.getpgid(0)):
            for pid in set(_session_members(gate_sid)):
                if pid == os.getpid():
                    continue
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

    assert first_seen, (
        "no pytest leg ever started within 180s — this canary would pass "
        "without testing anything"
    )
    assert legs_at_interrupt, (
        f"a leg started ({first_seen}) but none was still running {SOAK_S}s "
        "later, so the gate was not interrupted mid-battery — the run "
        "measured nothing"
    )
    assert not survivors, (
        f"{len(survivors)} processes survived an interrupted gate "
        f"({survivor_desc}) — reap_legs did not reach the leg's process "
        "group (#2611)"
    )
