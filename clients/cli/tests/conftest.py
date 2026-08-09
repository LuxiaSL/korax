"""The rig: the CLI driven end to end against an in-process board.

`world` is server/tests/test_api.py's fixture, with the ASGI app handed to
httpx as a transport rather than to a TestClient — the CLI's HTTP layer
takes an injected transport precisely so the suite can exercise the real
request path without a socket.

Every invocation in a test shares one event loop. The server's wakeup
condition (§11) binds to the loop it is first used on, so a fresh
`asyncio.run` per call would fail the second post in a test on a loop
mismatch. A rig detail, not a protocol one.
"""

from __future__ import annotations

import asyncio
import io
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import httpx
import pytest
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from korax_cli import PROTO
from korax_cli.cli import run

BASE_URL = "http://board.test"


@dataclass(frozen=True)
class Result:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def json(self) -> Any:
        """The one JSON document on stdout."""
        return json.loads(self.stdout)

    @property
    def error(self) -> dict[str, Any]:
        """The error object: the last JSON Lines record on stderr."""
        lines = [line for line in self.stderr.splitlines() if line.strip()]
        assert lines, "expected an error object on stderr"
        document = json.loads(lines[-1])
        assert isinstance(document, dict)
        return document

    @property
    def warnings(self) -> list[str]:
        out: list[str] = []
        for line in self.stderr.splitlines():
            if not line.strip():
                continue
            document = json.loads(line)
            if isinstance(document, dict) and "warning" in document:
                out.append(str(document["warning"]))
        return out


Invoke = Callable[..., Result]


@pytest.fixture()
def world() -> dict[str, Any]:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    return {
        "store": store,
        "board": board,
        "app": create_app(board),
        "operator": operator,
        "op_token": op_token,
    }


@pytest.fixture()
def cli(world: dict[str, Any]) -> Iterator[Invoke]:
    loop = asyncio.new_event_loop()
    board_transport = httpx.ASGITransport(app=world["app"])

    def invoke(
        *argv: str,
        token: str | None = None,
        identity: str | None = None,
        stdin: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> Result:
        out, err = io.StringIO(), io.StringIO()
        env = {"KORAX_URL": BASE_URL}
        if token is not None:
            env["KORAX_TOKEN"] = token
        if identity is not None:
            env["KORAX_IDENTITY"] = identity
        if env_extra:
            env.update(env_extra)
        code = loop.run_until_complete(
            run(
                list(argv),
                transport=transport if transport is not None else board_transport,
                stdout=out,
                stderr=err,
                stdin=io.StringIO(stdin),
                env=env,
            )
        )
        return Result(code, out.getvalue(), err.getvalue())

    try:
        yield invoke
    finally:
        loop.close()


def register(cli: Invoke, world: dict[str, Any], display: str) -> tuple[str, str]:
    """A fresh identity, through the CLI's own `identity new`."""
    result = cli("identity", "new", display, token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    body = result.json
    return body["id"], body["token"]


def grant(cli: Invoke, world: dict[str, Any], identity: str, ns: str, band: str) -> None:
    """A band grant is a POLICY on the log, never server configuration
    (§3.4) — so the rig posts one, through the CLI, like anything else."""
    envelope = json.dumps(
        {
            "proto": PROTO,
            "author": world["operator"],
            "ns": "/",
            "type": "POLICY",
            "grade": "n/a",
            "refs": [],
            "payload": {
                "grants": [
                    {"identity": world["operator"], "ns": "/**", "band": "human"},
                    {"identity": identity, "ns": ns, "band": band},
                ]
            },
            "ext": {},
        }
    )
    result = cli("post", "-", token=world["op_token"], stdin=envelope)
    assert result.exit_code == 0, result.stderr


@pytest.fixture()
def warner(cli: Invoke, world: dict[str, Any]) -> tuple[str, str]:
    """An identity that may post WARNs across the commons (§3.3)."""
    identity, token = register(cli, world, "enactor-1")
    grant(cli, world, identity, "/commons/**", "warner")
    return identity, token
