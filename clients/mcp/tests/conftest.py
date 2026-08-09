"""A seeded board in-process, reached over ASGI.

The world fixture follows server/tests/test_api.py: a `:memory:` store, an
operator identity registered out of band as §8.4's genesis key, and
`seed_board` for the commons and the first rakes. The client layer then
talks to it through `httpx.ASGITransport` — real requests, real
validation gauntlet, no socket.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from pydantic import SecretStr

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from korax_mcp.client import KoraxClient
from korax_mcp.config import KoraxConfig

BOARD_URL = "http://board.test"


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class World:
    board: Board
    store: Store
    app: object
    operator: str
    op_token: str

    def client_for(self, identity: str, token: str) -> KoraxClient:
        """A KoraxClient bound to this board, authenticated as one identity."""
        return KoraxClient(
            KoraxConfig(url=BOARD_URL, token=SecretStr(token), identity=identity),
            transport=httpx.ASGITransport(app=self.app),
        )

    def register(self, display: str) -> tuple[str, str]:
        """A fresh identity with no grants beyond the board defaults."""
        return self.store.create_identity(display)

    def grant(self, identity: str, ns: str, band: str) -> None:
        """A POLICY from the operator granting one band in one subtree.

        Grants are posted, not configured out of band (§3.4), and the
        operator's own human grant has to be restated because a POLICY at
        `/` supersedes the genesis grants wholesale.
        """
        self.board.append(self.operator, {
            "proto": PROTO,
            "author": self.operator,
            "ns": "/",
            "type": "POLICY",
            "grade": "n/a",
            "refs": [],
            "payload": {"grants": [
                {"identity": self.operator, "ns": "/**", "band": "human"},
                {"identity": identity, "ns": ns, "band": band},
            ]},
            "ext": {},
        })


@pytest.fixture()
def world() -> World:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    return World(
        board=board,
        store=store,
        app=create_app(board),
        operator=operator,
        op_token=op_token,
    )


@pytest.fixture()
async def operator_client(world: World):
    """The operator's connection — human band everywhere (§8.4)."""
    client = world.client_for(world.operator, world.op_token)
    try:
        yield client
    finally:
        await client.aclose()
