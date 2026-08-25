"""A seeded board in-process, reached over ASGI.

The world fixture follows server/tests/test_api.py: a `:memory:` store, an
operator identity registered out of band as §8.4's genesis key, and
`seed_board` for the commons and the first rakes. The client layer then
talks to it through `httpx.ASGITransport` — real requests, real
validation gauntlet, no socket.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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

# ── cross-tree import guard (ISSUE #2286, ruled light-track at #2287) ──
# A suite must test the tree it was collected from. From a worktree with
# the shared checkout's venv active, `python -m pytest` collects THESE
# files and imports the packages from THAT checkout — the run is a hybrid
# of two revisions and nothing says so. The implementation is shared in
# `tools/tree_guard.py` and loaded BY PATH, because loading it by name
# would resolve it through the very import system under suspicion.
_TREE = Path(__file__).resolve().parents[3]
#: This client and the server package it is built against — a client
#: suite genuinely exercises both, so both must come from one tree.
_PACKAGES = ("korax_mcp", "korax")


def _tree_guard():
    import importlib.util  # noqa: PLC0415
    import sys  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location(
        "korax_tree_guard", _TREE / "tools" / "tree_guard.py")
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec_module: a module loaded this way is absent
    # from sys.modules while it executes, which makes deferred annotation
    # resolution fail opaquely (the mill's #2232 §3, applied not cited).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pytest_configure(config: pytest.Config) -> None:
    guard = _tree_guard()
    try:
        guard.enforce(_TREE, _PACKAGES)
    except guard.CrossTreeImport as exc:
        raise pytest.UsageError(str(exc)) from None


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """State which tree was measured, on every run (#2290's addition).

    Here rather than in `pytest_report_header` (silent under `-q`, the
    invocation this floor uses) or in `pytest_configure` (global capture
    is active that early, so the line is written into a discarded
    buffer). Terminal summary runs after capture is released and puts
    the paths beside the counts a delivery is about to quote.
    """
    _tree_guard().announce(terminalreporter, _TREE, _PACKAGES)



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


@pytest.fixture(autouse=True)
def _isolate_read_basis_ledger(tmp_path_factory, monkeypatch) -> None:
    """Keep JOB #3610's ledger out of the developer's real home.

    `korax_mcp.server` resolves the ledger path from `os.environ` at CALL
    time — correct for a wrapper whose configuration is its environment,
    and the CLI's injected `args._env` has no equivalent here. Without
    this fixture the suite wrote real files into
    `~/.config/korax/read-basis/`: **measured, not feared** — a run left
    two ledgers there carrying `{"subjects": {"1": 17}}`, in-process board
    ids, from `korax_why` calls in tests that never mentioned a ledger.

    Autouse and unconditional, because the tests that pollute are the ones
    that are not about this feature at all, and those are exactly the ones
    nobody will remember to isolate.
    """
    monkeypatch.setenv(
        "KORAX_CONFIG_DIR", str(tmp_path_factory.mktemp("korax-config"))
    )
