"""`korax attach` / `korax fetch` — JOB #2325, artifact-store.md's B2
stage, against B1's live blob store (R129).

Round trip through the real request path (ASGI transport, no socket),
per this suite's own convention (`conftest.py`'s docstring): the CLI's
HTTP layer takes an injected transport so tests exercise the real code
that ships, not a mock of it.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from conftest import Invoke, grant, register

from korax_cli import PROTO

ARTIFACTS_NS = "/korax-dev/artifacts"


def _govern_artifacts(cli: Invoke, world: dict) -> None:
    """B1's own activation step (#2311/#2314, done by hand on the live
    board): the nest needs a POLICY before any anchor can land."""
    envelope = json.dumps({
        "proto": PROTO, "author": world["operator"], "ns": ARTIFACTS_NS,
        "type": "POLICY", "grade": "n/a", "refs": [],
        "payload": {"acts": ["NOTE"], "grades": False,
                    "grants": [{"identity": "band:*", "band": "poster"}]},
        "ext": {},
    })
    result = cli("post", "-", token=world["op_token"], stdin=envelope)
    assert result.exit_code == 0, result.stderr


@pytest.fixture()
def uploader(cli: Invoke, world: dict) -> tuple[str, str]:
    identity, token = register(cli, world, "uploader")
    grant(cli, world, identity, "/korax-dev/**", "claimant")
    _govern_artifacts(cli, world)
    return identity, token


def test_attach_then_fetch_round_trips_the_exact_bytes(
    tmp_path, cli: Invoke, uploader: tuple[str, str]
) -> None:
    identity, token = uploader
    src = tmp_path / "evidence.txt"
    src.write_bytes(b"the R85 comparison, or whatever this test needs it to be")

    up = cli("attach", str(src), "--caption", "a fixture blob",
             "--media-type", "text/plain", token=token, identity=identity)
    assert up.exit_code == 0, up.stderr
    assert up.json["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert up.json["bytes"] == src.stat().st_size
    assert isinstance(up.json["anchor"], int)

    dst = tmp_path / "out" / "fetched.txt"
    dst.parent.mkdir()
    down = cli("fetch", up.json["sha256"], "--out", str(dst),
              token=token, identity=identity)
    assert down.exit_code == 0, down.stderr
    assert down.json["path"] == str(dst)
    assert down.json["sha256"] == up.json["sha256"]
    assert dst.read_bytes() == src.read_bytes()
    assert down.json["media_type"].startswith("text/plain")


def test_the_caption_lands_on_the_anchor_envelope(
    tmp_path, cli: Invoke, uploader: tuple[str, str]
) -> None:
    identity, token = uploader
    src = tmp_path / "f.bin"
    src.write_bytes(b"\x00\x01\x02anchored")

    up = cli("attach", str(src), "--caption", "measured at deadbeef",
             token=token, identity=identity)
    assert up.exit_code == 0, up.stderr

    anchor = cli("envelope", str(up.json["anchor"]), token=token, identity=identity)
    assert anchor.exit_code == 0, anchor.stderr
    assert anchor.json["ns"] == ARTIFACTS_NS
    assert anchor.json["type"] == "NOTE"
    assert anchor.json["payload"] == "measured at deadbeef"
    assert anchor.json["pointer"]["sha256"] == up.json["sha256"]


def test_attach_of_a_missing_file_is_a_local_refusal_not_a_traceback(
    tmp_path, cli: Invoke, uploader: tuple[str, str]
) -> None:
    identity, token = uploader
    missing = tmp_path / "does-not-exist.txt"
    result = cli("attach", str(missing), "--caption", "c", token=token, identity=identity)
    assert result.exit_code == 1
    assert result.error["code"] == "local", (
        "a file the client never sent must be LOCAL, never the server's refusal"
    )


def test_fetch_of_an_unknown_sha_surfaces_the_servers_404(
    cli: Invoke, uploader: tuple[str, str]
) -> None:
    identity, token = uploader
    result = cli("fetch", "f" * 64, "--out", "/tmp/should-not-be-written.bin",
                 token=token, identity=identity)
    assert result.exit_code == 1
    assert result.error["code"] == 404


def test_the_per_blob_cap_refusal_is_surfaced_verbatim(
    tmp_path, cli: Invoke, uploader: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server names the cap in its refusal; the client must not
    swallow or reword it — the CLI has no cap logic of its own to test,
    only that it gets out of the server's way."""
    import korax.api as api_module
    monkeypatch.setattr(api_module, "MAX_BLOB_BYTES", 8)

    identity, token = uploader
    big = tmp_path / "too-big.bin"
    big.write_bytes(b"x" * 9)
    result = cli("attach", str(big), "--caption", "c", token=token, identity=identity)
    assert result.exit_code == 1
    assert result.error["code"] == 413
    assert "8" in result.error["message"]


# -- content-integrity check, exercised directly (no transport can be made
# -- to lie about bytes it never carried, so this drives the client
# -- function against a stubbed KoraxClient instead) ------------------------


def test_a_mismatched_fetch_is_refused_before_anything_is_written(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import io

    from korax_cli.cli import Config, Runtime, cmd_fetch
    import argparse

    class _StubClient:
        async def fetch_blob(self, sha256: str) -> tuple[bytes, str | None]:
            return b"not what you asked for", "text/plain"

    out, err = io.StringIO(), io.StringIO()
    rt = Runtime(stdout=out, stderr=err, stdin=io.StringIO(""))
    target = tmp_path / "should-not-exist.bin"
    args = argparse.Namespace(sha256="a" * 64, out=str(target))

    code = asyncio.run(cmd_fetch(args, _StubClient(), Config(url="http://x", token=None,
                                 identity=None, timeout=1.0), rt))
    assert code == 1
    assert "local" in err.getvalue()
    assert not target.exists(), "a hash mismatch must not leave a wrong file on disk"
