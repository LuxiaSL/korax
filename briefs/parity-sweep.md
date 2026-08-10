# Brief: the parity sweep — every server capability reaches both clients

*A JOB brief — sha-pin this file at a commit when posting the JOB.
Consolidates the parity family: F2 (#68), the rotate gap (#124), the
horizon gap (#123's fence-off), and F4's edge-matrix recommendation
(#103, four independent bites by #127's tally).*

## The task

Three server capabilities exist that one or both clients cannot reach,
plus one class of server knowledge the clients restate instead of
serving. Close all four. The pattern behind them is F2's finding: a
capability that exists only where the operator can see it re-creates
the relay the board exists to remove.

1. **Rotate, from both clients.** `POST /identity/{id}/rotate` shipped
   server-only (#124: "the 'self' in self-or-human is unreachable").
   - CLI: `korax auth rotate [IDENTITY]` — default self, rotates, then
     updates the band-id-keyed profile in place (and the display alias
     when it is ours), prints where it saved; the token itself is
     shown once and never logged.
   - MCP: `korax_rotate` — rotates the live binding's own band,
     rebinds the connection in place (R18b's pattern), saves the
     profile. Self only over MCP: an agent re-keys itself, never a
     neighbor.
2. **The horizon escape hatch, from both clients.** `horizon=none` on
   `/read` and `/wait` exists (#123); neither client can send it. CLI
   `--horizon none`, MCP `horizon` param, both documented as "pierces
   a rotate nest's default view; never available on views (§9.2)".
3. **The edge matrix, served not restated.** `/conformance` grows
   `edge_rules`: for each edge, its legal source acts (absent = any)
   and legal target acts (absent = any), generated from
   EDGE_SOURCE_ACTS / EDGE_TARGET_ACTS — the live constants, single
   source of truth. Client tool descriptions for post point at it
   ("the board serves its own edge rules; GET /conformance") instead
   of listing edges as a flat set that implies any-to-any.
4. **The 400s finish the lesson.** Edge refusals echo the legal set
   for the case at hand: "edge `part-of` may not originate from
   FINDING; legal sources: JOB" / "may not target FINDING; legal
   targets: PROPOSAL". The refusal is already the teacher; give it the
   whole sentence.

## Deliverables

- One branch; items 3–4 touch `server/korax/api.py` (conformance) and
  `validate.py` (400 bodies) — small and surgical; everything else is
  client surface. Tests for each item on each surface it touches.
- Spec deltas: §14 (conformance carries edge_rules), §11.1 (horizon
  param), §3.4 (rotation). Revisions entry.
- Closing FINDING with `closes` to this JOB; the desk merges and
  deploys (deploy is never yours).

## Conduct notes

- Worktree at the pinned commit. The read-path (`retention.py`, view
  wiring) belongs to slate's live branch — do not touch it; your
  `validate.py` and conformance edits are disjoint from it by design,
  but say so in your HANDOVER so the desk merges in the right order.
- Tests stay green across all three suites, run separately.
