"""The goodbye must fire on a REAL SIGTERM to a REAL server process (#921).

`test_goodbye.py` proves the mechanism in process by calling
`begin_shutdown()` directly. It was green for the entire time the feature
did not work, because the thing that was broken was **who calls it and
when** — and an in-process test supplies both.

WHAT WAS ACTUALLY WRONG. `uvicorn.Server.shutdown()` awaits
`_wait_tasks_to_complete()` BEFORE `lifespan.shutdown()`. The parked
long-polls uvicorn waits for were waiting for the call lifespan shutdown
makes, so the goodbye was unreachable by construction. Measured: a parked
call returned 23s after shutdown on its own poll timeout, `system_notice:
null`, `board.shutting_down` still False after the process exited. In
production `timeout_graceful_shutdown` is None — wait forever — supervised
watches re-armed faster than the wait could drain, systemd SIGKILLed at
90s, and `force_exit` skipped lifespan entirely.

So the goodbye is armed on the SIGNAL now, and only a real signal to a real
process can tell the difference. Hence a subprocess: `signal.signal` binds
the main thread, and a threaded rig silently installs nothing — which is
how the first attempt at this test produced a dead process and no result.

SEVERAL PARKED CLIENTS, NOT ONE (vesper's #923). Production had five
supervised watches and the failure was about what happens when they all
re-arm; a one-client test is a special case wearing the behaviour's name.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "server"
PARKED_CLIENTS = 4

_SERVER = """
import sys
sys.path.insert(0, sys.argv[1])
import uvicorn
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store
store = Store(":memory:")
operator, token = store.create_identity("operator")
store.set_meta("genesis_identity", operator)
board = Board(store); seed_board(board, operator)
open(sys.argv[2], "w").write(f"{operator}\\n{token}\\n{board.head}\\n")
uvicorn.run(create_app(board), host="127.0.0.1", port=%d, log_level="error")
"""


def _free_port() -> int:
    # bind-then-close: the OS will not hand out this port to another
    # `bind(0)` caller until it is released, and we release it only
    # microseconds before uvicorn's own bind — #1418, this test's own
    # fixed 8987 was colliding across the four to six bands this loop
    # runs in parallel on one shared host.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_real_sigterm_releases_every_parked_call(tmp_path) -> None:
    port = _free_port()
    script = tmp_path / "serve.py"
    script.write_text(_SERVER % port, encoding="utf-8")
    info = tmp_path / "info.txt"

    proc = subprocess.Popen([sys.executable, str(script), str(SERVER_DIR), str(info)])
    try:
        for _ in range(80):
            if info.exists():
                break
            time.sleep(0.25)
        else:
            pytest.skip("server did not start; not a statement about the goodbye")
        time.sleep(2.0)
        operator, token, head = info.read_text().split()

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        results: list[dict] = []
        lock = threading.Lock()

        def park() -> None:
            # a selector that CANNOT wake on ordinary traffic, so the only
            # thing that can end this call is the goodbye or its own timeout
            url = (f"http://127.0.0.1:{port}/wait?ns=/korax/notices&type=WARN"
                   f"&since={head}&timeout=60")
            request = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {token}"})
            try:
                with opener.open(request, timeout=90) as response:
                    body = json.loads(response.read())
            except Exception as exc:  # noqa: BLE001 — the failure IS the result
                body = {"error": repr(exc)}
            with lock:
                results.append(body)

        threads = [threading.Thread(target=park) for _ in range(PARKED_CLIENTS)]
        for thread in threads:
            thread.start()
        time.sleep(2.5)  # let them all actually park

        started = time.time()
        proc.send_signal(signal.SIGTERM)
        for thread in threads:
            thread.join(timeout=90)
        elapsed = time.time() - started
        exit_code = proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()

    assert len(results) == PARKED_CLIENTS

    # EVERY parked call gets one — not the first, not most of them.
    for body in results:
        assert "error" not in body, body
        notice = body.get("system_notice")
        assert notice, (
            "a parked call was severed rather than told. Before #921's fix "
            "this returned an ordinary empty page on its own timeout, which "
            "is 200 OK in an access log and indistinguishable from a goodbye"
        )
        assert notice["kind"] == "restart"
        assert isinstance(notice["retry_after_s"], int)
        assert body["envelopes"] == []
        assert body["cursor"] == int(head), "the goodbye advanced a cursor"

    # PROMPTLY, and this bound is what separates the fix from the defect.
    # The old build also ended these calls — after their full 60s poll — so
    # a test without a clock passes on the broken version.
    assert elapsed < 15, (
        f"the calls took {elapsed:.1f}s with a 60s poll budget: they ended "
        "because the poll expired, not because the shutdown released them"
    )
    # -15 is SIGTERM handled and exited. The production failure was systemd
    # SIGKILLing at 90s after the wait never drained.
    assert exit_code in (0, -signal.SIGTERM), (
        f"server exited {exit_code}: it did not shut down cleanly"
    )
