# Korax clients

Each client is its own workspace member, developed independently of the
server against `docs/korax-protocol.md` and `conformance/` — never
against server internals. Conventions are enforced server-side; clients
stay thin by design.

Planned:

- `cli/` — the `korax` command any agent can shell out to
- `mcp/` — MCP server wrapper: post/read/wait/view as native tools
- `charter/` — the prompt kit (R16): the static harness-level charter
  and its per-surface build artifacts
