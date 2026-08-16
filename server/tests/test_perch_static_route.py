"""The perch static route — serving split assets without serving the
filesystem (JOB #1389; #1387 condition 1: the guard and this test land
in the same commit as the route).

The guard under test is resolve-then-containment: whatever `..`,
percent-encodings or symlinks produce, the resolved path either sits
under `perch/` or the answer is 404 — the same fused absence/denial the
board's read path uses (`/envelope/<sealed>` answers 404 exactly as an
absent id does), so probing this route maps nothing about what exists
outside it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store


@pytest.fixture()
def client() -> TestClient:
    store = Store(":memory:")
    op, _tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    return TestClient(create_app(board))


def test_the_shell_serves_at_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "/perch/js/plumbing.js" in r.text, "the shell must load its own assets"


def test_the_banner_discloses_the_signing_stub(client: TestClient) -> None:
    """ISSUE #2261, item 1 of JOB #2507 — v0 attribution rests on the
    token table, and the `/` banner says so rather than leaving the gap
    to STATUS.md alone. A disclosure, not a fix: closes nothing."""
    r = client.get("/")
    assert r.status_code == 200
    assert "token table" in r.text
    assert "signing is stubbed" in r.text
    # No wording claiming signing exists or is verified.
    lowered = r.text.lower()
    for claim in ("signature verified", "signed by", "cryptographically"):
        assert claim not in lowered


def test_assets_serve_with_their_media_types(client: TestClient) -> None:
    for path, media in [("/perch/css/variables.css", "text/css"),
                        ("/perch/js/plumbing.js", "text/javascript"),
                        ("/perch/js/render.js", "text/javascript")]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith(media), (path, r.headers["content-type"])


def test_traversal_goes_nowhere(client: TestClient) -> None:
    """`../` in any coat resolves outside the base and answers 404 — the
    api source itself is the canary target because it provably exists."""
    for probe in ("/perch/../api.py",
                  "/perch/../../korax/api.py",
                  "/perch/..%2Fapi.py",
                  "/perch/%2e%2e/api.py",
                  "/perch/css/../../api.py",
                  "/perch/js/./../../korax/store.py"):
        r = client.get(probe)
        assert r.status_code == 404, (probe, r.status_code)
        assert "korax" not in r.text or "no such asset" in r.text


def test_absent_and_denied_are_the_same_404(client: TestClient) -> None:
    """A file that does not exist and a path that escapes answer
    identically, so the route cannot be used to map the tree.

    The escape probe is the ENCODED one deliberately: a literal
    `/perch/../api.py` is normalized away before routing and never
    reaches the handler (the router's 404, also fine) — `..%2F` is the
    one that arrives as a path param and exercises THIS guard."""
    missing = client.get("/perch/js/definitely-absent.js")
    escaped = client.get("/perch/..%2Fapi.py")
    assert missing.status_code == escaped.status_code == 404
    assert missing.json() == escaped.json()


def test_a_directory_is_not_servable(client: TestClient) -> None:
    """`is_file()` is half the guard: a directory listing is a map."""
    assert client.get("/perch/js").status_code == 404
    assert client.get("/perch/js/").status_code == 404
