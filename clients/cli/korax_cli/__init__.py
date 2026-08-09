"""korax — the command any agent can shell out to (clients/README.md).

Written against `docs/korax-protocol.md` and `conformance/`, never against
server internals. The protocol version is declared here rather than
imported: a client that took its `proto` from a server package would be
that server's client, not the protocol's.
"""

from __future__ import annotations

PROTO = "korax/0.1"

__all__ = ["PROTO"]
