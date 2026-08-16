"""ISSUE #2363 / JOB #2508 item 4 — the cursor commits after it emits,
never before.

`korax watch` (and the single-shot `read`/`wait` paths, which invert the
same way inside one expression) used to persist the cursor to disk as a
side effect of BUILDING the printed body, before that body ever reached
`emit`. A process killed between the two lines left the cursor advanced
past envelopes nobody had received.

The fix (`_stage_cursor_file` / `_commit_cursor_file`, `cursor.py`'s
`stage_cursor` / `commit_cursor`) splits persistence into a harmless
scratch-file write (staging, safe to do before emit — it never touches
the real cursor path) and the atomic rename that actually advances the
cursor a resumed watch reads (committing, done only after emit).

Both directions (#112): a rig that kills the process between emit and
commit proves the real cursor file was never touched; the control proves
a completed run still commits exactly once.
"""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any

import httpx
import pytest

import korax_cli.cli as cli_module
from korax_cli.cli import run

from conftest import BASE_URL


class _Killed(Exception):
    """Stands in for a process termination landing between emit and
    commit — anything NOT one of `run()`'s handled exception types, so
    it propagates instead of being converted into a clean exit code."""


def _invoke(argv: list[str], world: dict[str, Any], out: io.StringIO) -> int:
    err = io.StringIO()
    transport = httpx.ASGITransport(app=world["app"])
    return asyncio.run(
        run(
            argv,
            transport=transport,
            stdout=out,
            stderr=err,
            stdin=io.StringIO(""),
            env={"KORAX_URL": BASE_URL, "KORAX_TOKEN": world["op_token"]},
        )
    )


def test_a_kill_between_emit_and_commit_leaves_the_real_cursor_untouched(
    world: dict[str, Any], tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state" / "commons.cursor"
    out = io.StringIO()

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise _Killed

    monkeypatch.setattr(cli_module, "commit_cursor", _raise)

    with pytest.raises(_Killed):
        _invoke(["read", "--ns", "/commons/rakes", "--cursor-file", str(path)], world, out)

    # The kill fired AFTER commit_cursor was reached, which is only
    # possible if staging (and everything before it) already ran — and
    # the envelopes are on stdout as proof emit ran first.
    printed = json.loads(out.getvalue())
    assert len(printed["envelopes"]) >= 5
    assert printed["cursor_file"]["written"] is True  # staging succeeded

    # The real cursor path was never created: commit_cursor is where the
    # atomic rename onto it happens, and it never ran to completion.
    assert not path.exists(), (
        "the cursor advanced even though the process was killed before "
        "persisting — exactly the failure ISSUE #2363 describes"
    )


def test_a_completed_run_commits_exactly_once(
    world: dict[str, Any], tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "cursor"
    out = io.StringIO()
    calls: list[tuple[object, object]] = []
    real_commit = cli_module.commit_cursor

    def _tracking(temporary: object, target: object, warn: object) -> bool:
        calls.append((temporary, target))
        return real_commit(temporary, target, warn)

    monkeypatch.setattr(cli_module, "commit_cursor", _tracking)

    code = _invoke(["read", "--ns", "/commons/rakes", "--cursor-file", str(path)], world, out)

    assert code == 0
    assert len(calls) == 1
    assert path.exists()
    assert path.read_text().strip() == str(json.loads(out.getvalue())["cursor"])


def test_stage_precedes_commit_in_the_watch_loop_too(
    world: dict[str, Any], tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-shot paths are covered above; this is the loop
    (`cmd_watch`) itself, the instrument every band's wake runs on."""
    path = tmp_path / "watch.cursor"
    out = io.StringIO()

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise _Killed

    monkeypatch.setattr(cli_module, "commit_cursor", _raise)

    with pytest.raises(_Killed):
        _invoke(
            ["watch", "--ns", "/commons/rakes", "--cursor-file", str(path), "--since", "-1"],
            world,
            out,
        )

    printed = out.getvalue()
    assert printed.strip(), "the page must have been emitted before the kill fired"
    assert not path.exists()
