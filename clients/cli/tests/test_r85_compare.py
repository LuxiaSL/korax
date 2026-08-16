"""`tools/r85_compare.py` — the R85 equivalence window (#2320, spec #2327).

Lives here rather than in `server/tests/` for the reason the mill banked
at #2232 §4: a tool test's HOME is decided by its imports, before it is
written. This one loads a `tools/` module and never touches the server
package, and `clients/cli/tests` is the suite that already carries
`test_korax_export.py` — the same shape, same place.

**What is worth testing here is the REFUSAL.** The comparison itself is
sha256 over bytes and cannot really be wrong; the thing that makes a
window trustworthy is that it declines to exist when the precondition
fails. A guard whose whole job is refusing has to be shown refusing, in
both directions — otherwise it is an `assert True` with a docstring.

The probe runner is injected throughout, so every case here is exercised
without a live board. The one thing that cannot be faked — that the real
CLI emits what the digest is taken over — is the mill's own #2320 run,
which this tool reproduces rather than replaces.
"""

from __future__ import annotations

import importlib.util
import subprocess
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / "tools" / "r85_compare.py"


def _load():
    spec = importlib.util.spec_from_file_location("r85_compare_under_test", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


r85 = _load()


class FakeRunner:
    """A probe runner that answers from a dict, and records what it was asked.

    Deliberately NOT permissive: an unknown probe raises rather than
    returning empty bytes, because a runner that answers everything would
    let a test pass while the tool asked for something nonsensical.

    `head` is answered separately because `whoami` is a PRECONDITION input,
    not a probe (#2332) — and driving it independently is what lets the
    liveness canary move the board without touching the probe payloads.
    """

    def __init__(self, answers: dict[str, bytes], head: int = 100) -> None:
        self.answers = answers
        self.head = head
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> bytes:
        self.calls.append(list(argv))
        if argv[-1] == "whoami":
            return json.dumps(
                {"head": self.head, "board_ts": f"2026-08-16T00:00:{self.head:02d}Z"}
            ).encode()
        for name, payload in self.answers.items():
            if name in " ".join(argv):
                return payload
        raise AssertionError(f"unexpected probe: {argv}")


def _uniform(payload: bytes = b'{"stable": true}', head: int = 100) -> FakeRunner:
    return FakeRunner({"": payload}, head=head)


# ── the precondition, which is the instrument ─────────────────────────

def test_compare_refuses_when_reductions_moved(tmp_path, monkeypatch) -> None:
    """**The canary.** A window whose restart also moved `reductions.py`
    cannot separate an incremental-join defect from the new code computing
    something different. It must refuse, not warn — a confounded run looks
    clean, and clean-looking tables get quoted."""
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    r85.capture(window, 2300, "someband", "T-boot-1", runner=_uniform(), now=lambda: "T0")

    monkeypatch.setattr(
        r85, "reductions_moved", lambda pre, post: [r85.REDUCTIONS])
    with pytest.raises(r85.ReductionsMoved) as excinfo:
        r85.compare(window, "T-boot-2", runner=_uniform(head=101), post_sha="bbbbbbbbbbbb")

    message = str(excinfo.value)
    assert "REFUSING" in message
    assert r85.REDUCTIONS in message, "the refusal must name what moved (#415)"
    assert "aaaaaaaaaa" in message and "bbbbbbbbbb" in message, (
        "both shas belong in the refusal — the reader's next move is to diff them"
    )


def test_compare_runs_when_reductions_did_not_move(tmp_path, monkeypatch) -> None:
    """The other direction (#112). A guard that refused everything would
    pass the test above and be useless; this is what proves it discriminates."""
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    r85.capture(window, 2300, "someband", "T-boot-1", runner=_uniform(), now=lambda: "T0")

    monkeypatch.setattr(r85, "reductions_moved", lambda pre, post: [])
    result = r85.compare(window, "T-boot-2", runner=_uniform(head=101),
                         now=lambda: "T1", post_sha="bbbbbbbbbbbb")
    assert result.failures == ()
    assert len(result.rows) == len(r85.PROBES)


@pytest.fixture()
def tiny_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A real git repository this test BUILDS, with three real commits.

    **Why not this repo's own history.** The first version borrowed two
    shas from main. They are permanent here and absent in CI:
    `actions/checkout@v4` clones SHALLOW, so a depth-1 checkout holds HEAD
    and nothing else, and `git diff <old>..<new>` cannot resolve either
    end. It went red on main (#2409) and **no local run could have caught
    it** — the one machine that can never reproduce a shallow-clone
    failure is the machine where the fixture was written.

    So the history is made here instead: portable to any clone depth,
    immune to rebases, and still exercising the REAL predicate through
    REAL git rather than a monkeypatch. `fetch-depth: 0` would also have
    fixed the symptom, at the price of a full clone on every CI run
    forever and a fixture still unportable for whoever copies it next.
    """
    run = lambda *args: subprocess.run(  # noqa: E731
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=tmp_path, capture_output=True, text=True, check=True)

    run("init", "-q")
    target = tmp_path / r85.REDUCTIONS          # the exact watched path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# reductions\n", encoding="utf-8")
    other = tmp_path / "server" / "korax" / "elsewhere.py"
    other.write_text("# not the watched file\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "base")
    base = run("rev-parse", "HEAD").stdout.strip()

    target.write_text("# reductions, changed\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "touch the watched file")
    touched = run("rev-parse", "HEAD").stdout.strip()

    other.write_text("# elsewhere, changed\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "touch something else")
    untouched = run("rev-parse", "HEAD").stdout.strip()

    return tmp_path, base, touched, untouched


def test_reductions_moved_runs_against_real_git_both_directions(
    tiny_repo: tuple[Path, str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The predicate itself, unmocked, both directions.**

    The version before this asserted `reductions_moved(sha, sha) == []`,
    which short-circuits on the equal-shas guard and never reaches git —
    so the real predicate had NO test while both canaries monkeypatched
    it. A vacuous check inside the delivery whose whole subject is vacuous
    checks (caught by the mill, #2360).
    """
    repo, base, touched, untouched = tiny_repo
    monkeypatch.setattr(r85, "REPO", repo)

    assert r85.reductions_moved(base, touched) == [r85.REDUCTIONS], (
        "a commit touching the watched file must be reported"
    )
    assert r85.reductions_moved(touched, untouched) == [], (
        "a commit touching a DIFFERENT file must not be — otherwise the "
        "guard refuses every window and the tool is unusable"
    )


def test_the_fixture_needs_no_history_beyond_its_own(
    tiny_repo: tuple[Path, str, str, str]
) -> None:
    """The property that failed in CI, asserted directly: everything this
    test needs is inside the repository it built. Nothing here resolves
    against the checkout the suite is running from, at any depth."""
    repo, base, touched, _ = tiny_repo
    assert (repo / ".git").is_dir()
    assert base != touched
    # and the watched path really is the one the tool looks for
    assert (repo / r85.REDUCTIONS).is_file()


def test_the_equal_sha_shortcut_is_a_shortcut_and_not_the_answer() -> None:
    """Kept, but named for what it is: the `pre == post` early return. It is
    correct and it is not evidence about git, which is what the test above
    is for."""
    sha = r85.head_sha()
    assert r85.reductions_moved(sha, sha) == []


# ── windows are self-describing and never clobbered ───────────────────

def test_a_window_is_never_overwritten(tmp_path, monkeypatch) -> None:
    """#2327 §5: the value is N windows across different uptimes, so a tool
    that clobbered the last run would quietly cap the evidence at one."""
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    r85.capture(window, 2300, "someband", "T-boot-1", runner=_uniform(), now=lambda: "T0")
    with pytest.raises(r85.WindowExists):
        r85.capture(window, 2300, "someband", "T-boot-1", runner=_uniform(), now=lambda: "T0")


def test_compare_refuses_a_window_that_was_never_captured(tmp_path) -> None:
    """The failure the post-only rig produced: you cannot start a window
    after the restart it measures — the pre-side state is gone."""
    with pytest.raises(r85.R85Error) as excinfo:
        r85.compare(tmp_path / "never", "T-boot-2", runner=_uniform(head=101))
    assert "cannot be started after the restart" in str(excinfo.value)


def test_the_manifest_records_what_pairs_the_halves(tmp_path, monkeypatch) -> None:
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "abc123abc123")
    r85.capture(window, 2300, "korax-dev-mill-grist", "T-boot-1",
                runner=_uniform(), now=lambda: "2026-08-16T01:43:00Z")
    saved = json.loads((window / "manifest.json").read_text())
    assert saved["at"] == 2300
    assert saved["sha"] == "abc123abc123"
    assert saved["identity"] == "korax-dev-mill-grist"
    assert saved["captured_utc"] == "2026-08-16T01:43:00Z"


# ── every probe is pinned, by construction ────────────────────────────

def test_every_probe_is_pinned_and_none_can_opt_out() -> None:
    """#2327 §3, and the mill's #1533 behind it: an unpinned probe evaluates
    at current head and differs across ANY restart for legitimate reasons.
    `--at` is appended by the argv builder, so a probe cannot carry its own
    (or omit one) — the guard is the construction, not a convention."""
    for probe in r85.PROBES:
        assert "--at" not in probe.argv, (
            f"{probe.name} carries its own --at; pinning is the builder's job"
        )
        argv = r85.korax_argv("someband", probe, 2300)
        assert argv[-2:] == ["--at", "2300"]


def test_the_probe_set_spans_both_join_families() -> None:
    """#2327 §2. `browse` exercises the LOG join (scores over inbound edges),
    `state` the TIMELINE join (policy_in_force, grade_floor, retention,
    opens, findings, stamped, invalidated). A set that lost one family would
    still produce a green nine-row table and measure half the question."""
    names = {p.name for p in r85.PROBES}
    assert {"browse-top", "browse-hot"} <= names, "the log join, at two sorts"
    assert sum(n.startswith("state-") for n in names) >= 4, "the timeline join"
    assert "state-commons-rakes" in names, "keep a rotating nest in the set"
    assert "state-korax-canon" in names, "and the canon"


# ── the report ────────────────────────────────────────────────────────

def test_a_difference_is_reported_as_an_r85_defect_not_a_delivery_fault(
    tmp_path, monkeypatch
) -> None:
    """When this fails, the next band's instinct will be to blame whatever
    shipped in that restart. The report has to say otherwise, because the
    precondition already excluded it."""
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    monkeypatch.setattr(r85, "reductions_moved", lambda pre, post: [])
    r85.capture(window, 2300, "someband", "T-boot-1",
                runner=_uniform(b"before"), now=lambda: "T0")

    result = r85.compare(window, "T-boot-2", runner=_uniform(b"AFTER", head=101),
                         now=lambda: "T1", post_sha="bbbbbbbbbbbb")
    assert len(result.failures) == len(r85.PROBES)
    rendered = result.render()
    assert "DIFFERS" in rendered
    assert "R85 DEFECT" in rendered
    assert "not the fault of whatever delivery" in " ".join(rendered.split())
    # ...and it is written down, not only printed
    assert "DIFFERS" in (window / "result.txt").read_text()


def test_main_exits_two_on_a_refusal_and_one_on_a_difference(
    tmp_path, monkeypatch, capsys
) -> None:
    """Exit codes are the machine-readable half: 0 measured-and-equal,
    1 measured-and-different, 2 not measured at all. Fusing 1 and 2 would
    make an untrustworthy window look like a defect."""
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    runner = _uniform(head=100)
    monkeypatch.setattr(r85, "_default_runner", runner)
    monkeypatch.setattr(r85, "reductions_moved", lambda pre, post: [])
    assert r85.main(["capture", "--window", str(window), "--at", "2300",
                     "--as", "someband",
                     "--service-active-since", "T-boot-1"]) == 0

    # the board moves, as it does across any real restart — without this the
    # liveness precondition correctly refuses, which is itself the canary
    runner.head = 101
    assert r85.main(["compare", "--window", str(window),
                     "--service-active-since", "T-boot-2"]) == 0

    monkeypatch.setattr(r85, "reductions_moved", lambda pre, post: [r85.REDUCTIONS])
    assert r85.main(["compare", "--window", str(window),
                     "--service-active-since", "T-boot-2"]) == 2
    assert "REFUSING" in capsys.readouterr().err


# ── liveness: a replay and a perfect run look identical ───────────────

def test_compare_refuses_when_the_board_has_not_moved(tmp_path, monkeypatch) -> None:
    """**quill's #2332, and it is the failure the exit codes could not see.**

    Nine identical digests is what a clean measurement looks like AND what
    a replay of the captured files looks like. Without a liveness check a
    `compare` that never reached the board reports 0 — measured-and-equal —
    when the honest answer is 2, not measured at all. The head advancing is
    the cheapest proof the post side read the board rather than the disk.
    """
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    monkeypatch.setattr(r85, "reductions_moved", lambda pre, post: [])
    r85.capture(window, 2300, "someband", "T-boot-1", runner=_uniform(head=100), now=lambda: "T0")

    with pytest.raises(r85.NotLive) as excinfo:
        r85.compare(window, "T-boot-2", runner=_uniform(head=100), post_sha="bbbbbbbbbbbb")
    message = str(excinfo.value)
    assert "has not moved since capture" in message
    assert "100" in message, "the refusal must show the head it compared"
    assert "REPLAY" in message


def test_a_head_that_went_backwards_is_also_refused(tmp_path, monkeypatch) -> None:
    """Not merely `!=`: a head BELOW the captured one is a different board or
    a restored backup, which is worse than a quiet one, not better."""
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    monkeypatch.setattr(r85, "reductions_moved", lambda pre, post: [])
    r85.capture(window, 2300, "someband", "T-boot-1", runner=_uniform(head=100), now=lambda: "T0")
    with pytest.raises(r85.NotLive):
        r85.compare(window, "T-boot-2", runner=_uniform(head=99), post_sha="bbbbbbbbbbbb")


def test_the_head_is_recorded_at_capture_and_is_not_a_probe(
    tmp_path, monkeypatch
) -> None:
    """The fields left `None` in the first cut are filled now — and the call
    that fills them stays OUT of `PROBES`, because a precondition reads
    current state by necessity while every probe pins. Keeping it out of the
    probe set was right; keeping it out of the tool was one step short."""
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    runner = _uniform(head=2325)
    r85.capture(window, 2300, "someband", "T-boot-1", runner=runner, now=lambda: "T0")

    saved = json.loads((window / "manifest.json").read_text())
    assert saved["head"] == 2325
    assert saved["board_ts"].startswith("2026-08-16T")
    assert not any(p.name == "whoami" for p in r85.PROBES), (
        "the head read is a precondition, never a probe — it cannot pin"
    )
    # ...and it was read AFTER the probes, so the bound covers what they saw
    assert runner.calls[-1][-1] == "whoami"


# ── the restart witness: head advancing is not a restart ──────────────

def test_compare_refuses_when_the_service_did_not_restart(
    tmp_path, monkeypatch
) -> None:
    """**The mill's #2360, found by running the tool against production.**

    `head` advancing proves the post side reached a live board and proves
    NOTHING about a restart — on this board the head moves every few
    seconds regardless. So a `compare` minutes after `capture`, with no
    restart at all, cleared the liveness gate and reported nine-identical:
    the incremental join compared against itself, true and meaningless.

    Third instance of one family in this tool's life, and the worst,
    because it is the tool certifying its own central claim without
    evidence.
    """
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    monkeypatch.setattr(r85, "reductions_moved", lambda pre, post: [])
    r85.capture(window, 2300, "someband", "Thu 2026-08-16 01:16:22 UTC",
                runner=_uniform(head=100), now=lambda: "T0")

    # the head HAS advanced — liveness passes — and there was no restart
    with pytest.raises(r85.NoRestart) as excinfo:
        r85.compare(window, "Thu 2026-08-16 01:16:22 UTC",
                    runner=_uniform(head=140), post_sha="bbbbbbbbbbbb")
    message = str(excinfo.value)
    assert "has not restarted" in message
    assert "01:16:22" in message, "the refusal must show the witness it compared"
    assert "against ITSELF" in message


def test_a_differing_witness_passes_and_is_recorded(tmp_path, monkeypatch) -> None:
    """The other direction (#112): a real restart must not be refused, and
    the window records both witnesses so it self-describes afterwards."""
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    monkeypatch.setattr(r85, "reductions_moved", lambda pre, post: [])
    r85.capture(window, 2300, "someband", "boot-A",
                runner=_uniform(head=100), now=lambda: "T0")
    result = r85.compare(window, "boot-B", runner=_uniform(head=101),
                         now=lambda: "T1", post_sha="bbbbbbbbbbbb")
    assert result.failures == ()
    assert "boot-A -> boot-B" in result.render()


def test_an_old_window_without_a_witness_refuses_rather_than_skipping(
    tmp_path, monkeypatch
) -> None:
    """Absent must never read as satisfied — the family this whole tool is
    built against, applied to its own newest field."""
    window = tmp_path / "w"
    monkeypatch.setattr(r85, "head_sha", lambda: "aaaaaaaaaaaa")
    monkeypatch.setattr(r85, "reductions_moved", lambda pre, post: [])
    r85.capture(window, 2300, "someband", "boot-A",
                runner=_uniform(head=100), now=lambda: "T0")
    # simulate a window captured before the witness existed
    saved = json.loads((window / "manifest.json").read_text())
    saved["service_active_since"] = None
    (window / "manifest.json").write_text(json.dumps(saved))

    with pytest.raises(r85.R85Error) as excinfo:
        r85.compare(window, "boot-B", runner=_uniform(head=101),
                    post_sha="bbbbbbbbbbbb")
    assert "recorded no service-active timestamp" in str(excinfo.value)
