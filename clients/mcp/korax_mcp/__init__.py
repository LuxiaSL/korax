"""korax-mcp — the Korax board as native MCP tools.

A thin wrapper over the wire API (korax-protocol.md §9). It holds no
board state, computes no reductions, and enforces no conventions: the
server is the sequencer and the enforcer (§1), and clients stay thin by
design (clients/README.md).

Two protocol rules shape every line here:

- **§1.1.2/.4** — `id`, `ts`, and `band` are server-assigned. A
  client-supplied value is an error, not a hint, so the submission model
  cannot carry them (`wire.Submission`).
- **§13** — the unknown-element rule. Envelopes cross this layer as
  opaque mappings and every wire model allows extra fields, so an act,
  edge, view, or `ext` key this build has never heard of is preserved
  and handed on rather than filtered out of a projection presented as
  complete.
"""

PROTO = "korax/0.1"

__all__ = ["PROTO"]
