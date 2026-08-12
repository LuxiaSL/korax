# The grant console — approve from the perch, machine-verified

**JOB shape:** perch + tests. The operator's ask, verbatim: "this
type of thing should be entirely automatable from the web view." A
grant-request OPEN sits in the inbox tab today as a card the
operator can only act on by dropping to a CLI whose profile name
they had to be told. **The delivery closes the issue this brief
rides with.**

## The fix

The inbox tab's grant-request cards (`ext.korax.grant_request` is
already structured — identity, display, band/ns pairs) gain an
**Approve** flow:

1. Fetch the policy in force for the requested nest's root
   (`/policy?ns=/` — the perch can already read it).
2. Compose the successor: identical payload, requested grant pairs
   appended. **Show the machine-verified diff before anything
   posts** — fields changed, grants removed (MUST be none), grants
   added — the #1782 discipline as UI. A POLICY replaces its nest
   wholesale (#1198); the diff is not decoration, it is the
   safety.
3. One click posts it as the operator's own band (the perch is
   their session; human-authored POLICY is self-stamping, §8.5 —
   in force immediately), then closes the OPEN citing the POLICY id.
4. **Staleness guard:** re-fetch the policy just before posting; if
   it moved since compose, re-diff and re-show rather than post — a
   wholesale replace over a policy that changed underneath silently
   reverts someone else's grant.

A **Decline** affordance closes the OPEN with a typed reason and no
POLICY. Both paths render in the card's disposition chip like every
other inbox ruling.

## Constraints

- Human-band session only: the buttons render only when the bound
  identity's band is human — for anyone else the card stays
  read-only, exactly as today.
- Zero server diff expected — every read and write used exists. If a
  seam is genuinely needed, argue it in the delivery.
- The defines guard and the browser leg grow with any new helpers
  (R90/R94 line); the browser leg exercises approve end-to-end
  against a subprocess board: request posted → approve clicked →
  diff shown → POLICY landed → grant queryable → OPEN closed.

## Allocation

Quill's by announcement — fresh off the perch token layer (R102) and
free; wren fallback; any band otherwise (#1610's shape).
