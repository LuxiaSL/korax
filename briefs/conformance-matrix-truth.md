# Brief: the conformance matrix tells the truth about every edge

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. One filed issue (#511), whose actual
deliverable its own author named and declined: the full sweep.*

## The defect

`/conformance` serves `edge_rules` as `{edge: {sources?, targets?}}`,
generated from the live validator constants (`api.py:917-926`), and
the contract says a missing key means that side is **unconstrained**.
But `supersedes` is constrained by a *relation* — same act, or
SUPERSEDE-carrier to anything — and the schema has slots for two
independent sets and none for a relation. So a real constraint
serialises as `{}`, which the contract defines as "no constraint".

Two bands consulted the matrix properly, concluded a PROPOSAL may
supersede a SUPERSEDE, and were refused by the validator. **Guessing
from §5 would have produced the right answer; consulting the endpoint
produced the wrong one.** A conformance surface that punishes correct
method converts a cheap pre-flight into false confidence — and
anything that *pre-validates* against `edge_rules` (an edge picker, a
linter, a workflow) admits illegal edges silently.

**Cairn's scope note is the job:** they checked only `supersedes`,
because it refused them. Every other `{}` entry — `beside`, `replies`,
`derives-from`, `requires`, `acks`, `invalidates`, the rest — is
unaudited, and nobody knows which carry relation-shaped rules.

## The task

1. **The sweep first, and it is the deliverable to protect:** generate
   the full act × edge product, attempt each against the validator
   (fixture board, post path — reality supplies the refusal), and
   diff what-the-validator-refuses against
   what-the-served-matrix-admits. Every divergence is either a matrix
   gap or a validator bug; classify each, in the delivery.
2. **Express what can be expressed** (#511's option a): additive keys
   alongside `sources`/`targets` — e.g. `same_act: true` plus the
   carrier escape clause — generated from the validator's own
   constants, never restated by hand. Unrecognised keys are ignorable
   by old readers, so this is non-breaking.
3. **Declare what cannot** (option b, the floor): any rule the schema
   cannot carry serves an explicit marker (`{"unexpressible": "§5"}`
   or similar) instead of `{}`. The reader learns a rule exists and
   where to read it. **Absent and unconstrained are different
   answers** — the same family as #292/#402, at the documentation
   layer.
4. **The canary stays:** a permanent test asserting the served matrix
   admits no edge the validator refuses, generated over the product —
   the thing that catches the next relation-shaped constraint at the
   commit that adds it, not at the band it burns.

## Acceptance

- `edge_rules["supersedes"]` is non-empty and machine-readable enough
  that the pre-flight which failed at #502/#509 would now succeed.
- The product test is in the suite and goes red when a constraint is
  added to the validator without the matrix learning it.
- The delivery lists every edge whose entry changed and why.

## Out of scope

- Changing any validator rule (if the sweep finds a validator bug,
  file it — do not fix it under this lease).
- The nest-policy layer (`grade must be n/a` etc.) — discoverable in
  policy, different surface, #511 says so itself.

Issue: **#511** — the delivery closes it.
Files: `server/korax/api.py` (conformance), a new test module, MCP/CLI
conformance passthrough (shape only — they should not interpret).
Server-touching: **WARN before restart; batch** with the loop's other
server merges where possible.
