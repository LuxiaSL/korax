"""Server operations CLI: `korax-server init` and `korax-server serve`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .board import Board
from .store import Store


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.db)
    if path.exists():
        print(f"refusing: {path} already exists", file=sys.stderr)
        return 1
    store = Store(path)
    operator_id, token = store.create_identity(args.display)
    store.set_meta("genesis_identity", operator_id)

    from .seed import seed_board

    board = Board(store)
    seed_board(board, operator_id)

    print(f"board:    {path}")
    print(f"operator: {operator_id} ({args.display})")
    print(f"token:    {token}")
    print(f"log:      {board.head + 1} envelopes (genesis + commons + rakes)")
    print("\nThe token is shown once. Store it safely.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    store = Store(Path(args.db))
    app = create_app(Board(store))
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="korax-server")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create and seed a new board")
    p_init.add_argument("--db", default="korax.db")
    p_init.add_argument("--display", default="operator")
    p_init.set_defaults(func=cmd_init)

    p_serve = sub.add_parser("serve", help="serve an existing board")
    p_serve.add_argument("--db", default="korax.db")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=7420)
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
