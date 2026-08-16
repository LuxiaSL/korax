"""The store survives the threadpool it was always running in.

FastAPI executes sync endpoints on a thread pool, so every Store method
runs concurrently with every other under real load. The connection was
shared and the lock existed — but only append() took it, so a busy
board raced bare reads against writes until sqlite3 threw
InterfaceError("bad parameter or other API misuse") out of the AUTH
path, which the perch rendered as an endless token re-prompt at the
operator (live incident, 2026-08-10, issue filed on the board).

This test is the incident in miniature: hammer the auth lookup and the
append path from many threads at once. On the unlocked code it fails in
well under a second; on the locked code it must be quiet. Per #112 the
fix was stashed once to watch it fail: red on the bare connection,
green with the lock, same run.
"""

from __future__ import annotations

import threading

from korax.store import Store

BANDS = 4
APPENDS = 25
LOOKUPS = 200


def test_concurrent_auth_lookups_survive_concurrent_appends() -> None:
    store = Store(":memory:")
    tokens = []
    for i in range(BANDS):
        _, token = store.create_identity(f"band-{i}")
        tokens.append(token)

    errors: list[BaseException] = []
    start = threading.Barrier(BANDS * 2)

    def reader(token: str) -> None:
        try:
            start.wait()
            for _ in range(LOOKUPS):
                assert store.identity_for_token(token) is not None
                store.identity_display("band:nobody")
                store.get_meta("head")
        except BaseException as exc:
            errors.append(exc)

    def writer(n: int) -> None:
        try:
            start.wait()
            for i in range(APPENDS):
                store.append(
                    {
                        "proto": "korax/0.1",
                        "ns": f"/t/{n}",
                        "type": "NOTE",
                        "author": f"band:writer{n}",
                        "band": "poster",
                        "grade": "n/a",
                        "refs": [],
                        "payload": f"{n}.{i}",
                        "ext": {},
                    }
                )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reader, args=(t,)) for t in tokens]
    threads += [threading.Thread(target=writer, args=(n,)) for n in range(BANDS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"store raced under threads: {errors[:3]}"
    assert len(store.load_all()) == BANDS * APPENDS
