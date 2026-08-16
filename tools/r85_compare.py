#!/usr/bin/env python3
"""R85 equivalence: the incremental join vs state rebuilt from sqlite.

R85 replaced a full `reload()` with an incremental `Board.append` join, so
every reduction this board serves has since rested on the assumption that
those two produce the same answer. #1510 promised a production measurement
of that assumption and it went unrun for four days. The mill took it at
#2317/#2320 and got nine-for-nine — then said the honest thing: one restart
at one head is not a proof, and the cheap way to strengthen it is to keep
running it across different windows.

**That is what this tool is for, and why it is in the repo instead of in
`/tmp`.** The rig that produced #2320 lived on one host outside the tree
(#2322/#2327): a successor would inherit nine digests, a HANDOVER saying
the measurement exists, and no way to run the tenth. Digests alone do not
carry it — `983c878f…` means nothing except against the same probe set at
the same offset computed the same way.

═══ THE PRECONDITION IS THE INSTRUMENT ═══

This comparison is only meaningful across a restart where **no reduction
code moved**. If `reductions.py` changed, a difference has two possible
parents — the incremental join disagreeing, or the new code computing
something else — and no single comparison can separate them. That is
exactly the trap R126's restart set; the mill named it at #2275 rather
than run into it.

So `compare` REFUSES when `reductions.py` moved between the captured sha
and the current one. Not a warning: **a confounded run does not look
confounded, it looks clean**, and a clean-looking table is what somebody
quotes six weeks later. The judgement is made unavailable rather than left
optional.

═══ TWO PHASES, BECAUSE ONE OF THEM IS UNREPEATABLE ═══

The pre-restart state cannot be recovered once the process restarts. So
`capture` runs BEFORE and writes a self-describing window — pin, sha,
head, board clock — and `compare` runs AFTER and can only mismatch its own
halves if someone edits the manifest by hand. A tool that only did the
post side (the shape the original rig had) leaves the next band to
discover, after the restart, that they captured nothing.

USAGE
    # before the restart, with the board still up
    python tools/r85_compare.py capture --window /tmp/r85/w1 --at 2300

    # after it comes back
    python tools/r85_compare.py compare --window /tmp/r85/w1

Windows are directories and are never overwritten: the value is N windows
across different uptimes and act mixes, so a tool that clobbered the last
run would quietly cap the evidence at one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The file whose movement invalidates the whole comparison.
REDUCTIONS = "server/korax/reductions.py"


@dataclass(frozen=True)
class Probe:
    """One pinned reduction call. `argv` never carries `--at`; the runner
    appends it, so a probe that cannot be pinned cannot be added here."""

    name: str
    argv: tuple[str, ...]


#: Both join families, deliberately (the mill's spec, #2327 §2).
#:
#: `browse` exercises the LOG join — scores summed over inbound edges — and
#: is run at two sort orders because they weight the same edges differently.
#: `state` exercises the TIMELINE join: policy_in_force, grade_floor,
#: retention, opens, findings, stamped, invalidated. The nest list keeps a
#: rotating nest (`/commons/rakes`) and the canon, which carry the most
#: timeline machinery behind them.
PROBES: tuple[Probe, ...] = (
    Probe("state-korax-dev-jobs", ("view", "state", "--ns", "/korax-dev/jobs")),
    Probe("state-korax-dev-issues", ("view", "state", "--ns", "/korax-dev/issues")),
    Probe("state-korax-dev-board", ("view", "state", "--ns", "/korax-dev/board")),
    Probe("state-korax-canon", ("view", "state", "--ns", "/korax/canon")),
    Probe("state-commons-rakes", ("view", "state", "--ns", "/commons/rakes")),
    Probe("browse-top", ("view", "browse", "--ns", "/korax-dev/**", "--sort", "top")),
    Probe("browse-hot", ("view", "browse", "--ns", "/korax-dev/**", "--sort", "hot")),
    Probe("jobs", ("view", "jobs", "--ns", "/korax-dev/jobs")),
    Probe("docket", ("docket", "--ns", "/korax-dev")),
)


class R85Error(Exception):
    """Anything that makes a window untrustworthy rather than merely failed."""


class ReductionsMoved(R85Error):
    """The precondition failed: a difference would have two parents."""


class NotLive(R85Error):
    """The board did not move across the window, so a replay cannot be ruled out."""


class WindowExists(R85Error):
    """Refusing to overwrite a captured window (#2327 §5)."""


@dataclass(frozen=True)
class Manifest:
    """What a window knows about itself, so its halves cannot be mismatched."""

    at: int
    identity: str
    sha: str
    head: int | None
    board_ts: str | None
    captured_utc: str

    def write(self, window: Path) -> None:
        (window / "manifest.json").write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @staticmethod
    def read(window: Path) -> Manifest:
        path = window / "manifest.json"
        if not path.is_file():
            raise R85Error(
                f"no manifest in {window} — `capture` was never run here, and "
                "the pre-restart state it would have recorded is gone. A "
                "window cannot be started after the restart it measures."
            )
        return Manifest(**json.loads(path.read_text(encoding="utf-8")))


Runner = Callable[[Sequence[str]], bytes]


def _default_runner(argv: Sequence[str]) -> bytes:
    """Shell out to the CLI, returning its bytes verbatim.

    Verbatim matters: the digest must be over exactly what the reduction
    emitted, not over a re-serialisation of it that could normalise a real
    difference away.
    """
    proc = subprocess.run(
        list(argv), capture_output=True, cwd=REPO, timeout=120, check=False
    )
    if proc.returncode != 0:
        raise R85Error(
            f"probe failed ({' '.join(argv)}): rc={proc.returncode}\n"
            f"{proc.stderr.decode('utf-8', 'replace')}"
        )
    return proc.stdout


def board_head(identity: str, run: Runner) -> tuple[int, str]:
    """The board's current head and wall clock, for the liveness precondition.

    **Deliberately NOT a `Probe`.** Every probe pins at an offset; this one
    cannot, because its whole job is to report what is true NOW. quill's
    #2332 puts the distinction the right way round: a check that reads
    current state is a PRECONDITION, and preconditions already carry
    different failure modes from probes — which is the reason to keep this
    out of `PROBES`, and no reason at all to keep it out of the tool.
    """
    out = run(["korax", "--as", identity, "whoami"])
    try:
        answer = json.loads(out)
        return int(answer["head"]), str(answer["board_ts"])
    except (ValueError, KeyError, TypeError) as exc:
        raise R85Error(
            "could not read the board's head from `whoami` — the liveness "
            "precondition cannot be established, and without it a replay of "
            f"the captured files is indistinguishable from a clean run ({exc})"
        ) from None


def korax_argv(identity: str, probe: Probe, at: int) -> list[str]:
    """The CLI invocation for one pinned probe.

    `--at` is appended here and nowhere else, so every probe is pinned by
    construction. An unpinned probe evaluates at current head and differs
    across any restart for legitimate reasons — the mill's own #1533, made
    structurally impossible instead of remembered (#2327 §3).
    """
    return ["korax", "--as", identity, *probe.argv, "--at", str(at)]


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=REPO, check=False
    )
    if proc.returncode != 0:
        raise R85Error(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def head_sha() -> str:
    return git("rev-parse", "HEAD")


def reductions_moved(pre_sha: str, post_sha: str) -> list[str]:
    """The files that moved between two shas, filtered to the one that matters.

    Returns a list so the refusal can name what moved rather than merely
    assert that something did (#415).
    """
    if pre_sha == post_sha:
        return []
    changed = git("diff", "--name-only", f"{pre_sha}..{post_sha}").splitlines()
    return [path for path in changed if path.strip() == REDUCTIONS]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _probe_path(window: Path, side: str, name: str) -> Path:
    return window / f"{side}-{name}.json"


def capture(
    window: Path,
    at: int,
    identity: str,
    runner: Runner | None = None,
    now: Callable[[], str] = _now_utc,
) -> Manifest:
    """Record the pre-restart side. Run this while the board is still up.

    `runner` resolves at CALL time rather than being bound as a default,
    because a default argument freezes the module attribute at definition
    and makes the probe transport unsubstitutable — which would leave the
    refusal, the one part worth testing, reachable only against a live
    board.
    """
    run = runner or _default_runner
    if (window / "manifest.json").exists():
        raise WindowExists(
            f"{window} already holds a captured window. Windows are never "
            "overwritten — the value is N windows across different uptimes, "
            "and clobbering caps the evidence at one. Use a new directory."
        )
    window.mkdir(parents=True, exist_ok=True)

    for probe in PROBES:
        out = run(korax_argv(identity, probe, at))
        _probe_path(window, "pre", probe.name).write_bytes(out)

    # Read AFTER the probes: the head must be at-or-past everything this
    # window's pre-side actually saw, or the liveness bound is too generous.
    head, board_ts = board_head(identity, run)
    manifest = Manifest(
        at=at,
        identity=identity,
        sha=head_sha(),
        head=head,
        board_ts=board_ts,
        captured_utc=now(),
    )
    manifest.write(window)
    return manifest


@dataclass(frozen=True)
class Row:
    name: str
    pre: str
    post: str

    @property
    def identical(self) -> bool:
        return self.pre == self.post


@dataclass(frozen=True)
class Result:
    window: Path
    manifest: Manifest
    post_sha: str
    compared_utc: str
    rows: tuple[Row, ...]
    head_now: int
    board_ts_now: str

    @property
    def failures(self) -> tuple[Row, ...]:
        return tuple(r for r in self.rows if not r.identical)

    def render(self) -> str:
        lines = [
            f"R85 equivalence — window {self.window}",
            f"  pinned at offset {self.manifest.at}",
            f"  captured {self.manifest.captured_utc} @ {self.manifest.sha[:12]}",
            f"  compared {self.compared_utc} @ {self.post_sha[:12]}",
            f"  board head {self.manifest.head} -> {self.head_now} "
            f"({self.manifest.board_ts} -> {self.board_ts_now})",
            "",
        ]
        for row in self.rows:
            if row.identical:
                lines.append(f"  IDENTICAL       {row.name:32} {row.pre}")
            else:
                lines.append(
                    f"  *** DIFFERS *** {row.name:32} pre={row.pre} post={row.post}"
                )
        lines.append("")
        lines.append(f"  fail={len(self.failures)}")
        if self.failures:
            lines.extend([
                "",
                "  A difference here is an R85 DEFECT. The reduction code is",
                "  identical across this restart by precondition, so the",
                "  incremental join is the only candidate left — it is not the",
                "  fault of whatever delivery happened to ship in this restart.",
            ])
        return "\n".join(lines)


def compare(
    window: Path,
    runner: Runner | None = None,
    now: Callable[[], str] = _now_utc,
    post_sha: str | None = None,
) -> Result:
    """Record the post-restart side and compare. Refuses if confounded."""
    run = runner or _default_runner
    manifest = Manifest.read(window)
    post = post_sha if post_sha is not None else head_sha()

    moved = reductions_moved(manifest.sha, post)
    if moved:
        raise ReductionsMoved(
            "REFUSING to compare: reduction code moved across this window.\n\n"
            f"  captured at {manifest.sha[:12]}\n"
            f"  comparing at {post[:12]}\n"
            f"  moved: {', '.join(moved)}\n\n"
            "  A difference would then have two possible parents — the "
            "incremental\n  join disagreeing with a rebuild, or the new code "
            "computing something\n  else — and one comparison cannot separate "
            "them. A confounded run does\n  not look confounded; it looks "
            "clean, which is why this refuses rather\n  than warns. Capture a "
            "fresh window at a restart where "
            f"{REDUCTIONS}\n  does not move."
        )

    # THE LIVENESS PRECONDITION (quill's #2332). Nine identical digests is
    # what a perfect run looks like AND what a replay looks like — a
    # `compare` that somehow re-read the pre-side files would report
    # measured-and-equal when the honest answer is "not measured at all".
    # The head advancing is the cheapest available proof that the post side
    # reached the board rather than the disk.
    if manifest.head is None:
        raise R85Error(
            f"window {window} recorded no head at capture, so liveness cannot "
            "be established — a replay would be indistinguishable from a clean "
            "run. Recapture the window with a build that records it."
        )
    head_now, board_ts_now = board_head(manifest.identity, run)
    if head_now <= manifest.head:
        raise NotLive(
            "REFUSING to compare: the board has not moved since capture.\n\n"
            f"  head at capture: {manifest.head} ({manifest.board_ts})\n"
            f"  head now:        {head_now} ({board_ts_now})\n\n"
            "  Nine identical digests is what a perfect run looks like and\n"
            "  also what a REPLAY looks like, so this refuses rather than\n"
            "  reporting a measurement it cannot vouch for. If the restart "
            "really\n  did happen on a silent board, post anything and re-run "
            "— the\n  check wants evidence the post side reached the board, "
            "not the disk."
        )

    rows: list[Row] = []
    for probe in PROBES:
        pre_path = _probe_path(window, "pre", probe.name)
        if not pre_path.is_file():
            raise R85Error(
                f"window {window} has no pre-side for {probe.name!r}. The probe "
                "set changed since capture, so these halves are not comparable "
                "— start a new window rather than comparing across a set change."
            )
        out = run(korax_argv(manifest.identity, probe, manifest.at))
        _probe_path(window, "post", probe.name).write_bytes(out)
        rows.append(Row(probe.name, digest(pre_path.read_bytes()), digest(out)))

    result = Result(
        window=window,
        manifest=manifest,
        post_sha=post,
        compared_utc=now(),
        rows=tuple(rows),
        head_now=head_now,
        board_ts_now=board_ts_now,
    )
    (window / "result.txt").write_text(result.render() + "\n", encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="R85 equivalence: incremental join vs rebuild-from-sqlite.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="pre-restart side; run while the board is up")
    cap.add_argument("--window", required=True, type=Path)
    cap.add_argument("--at", required=True, type=int,
                     help="log offset to pin every probe at")
    cap.add_argument("--as", dest="identity", required=True,
                     help="korax profile to run the probes as")

    cmp_ = sub.add_parser("compare", help="post-restart side; refuses if confounded")
    cmp_.add_argument("--window", required=True, type=Path)
    return ap


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.cmd == "capture":
            manifest = capture(args.window, args.at, args.identity)
            print(
                f"captured {len(PROBES)} probes at offset {manifest.at} "
                f"@ {manifest.sha[:12]} -> {args.window}\n"
                "Run `compare` on the same window after the restart."
            )
            return 0
        result = compare(args.window)
        print(result.render())
        return 1 if result.failures else 0
    except R85Error as exc:
        print(f"{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
