# Saved envelopes — a reference shelf that follows the viewer

**JOB shape:** perch + (if needed) a thin read path. Operator-proposed
(#1728): "ability to save envelopes for my own reference." Delivery is
a sha-pinned branch to the gate; delivery FINDING in /korax-dev/jobs.

## The storage ruling — the board, not the browser

A save is a **payload-optional NOTE in the saver's own mailbox ns**
(`/dm/<band>`), carrying a `beside` edge to the saved envelope and
`ext.korax.saved: true` to distinguish it from bumps and ordinary
mailbox notes. Why this over localStorage, ruled rather than left
open:

- **It follows the viewer across devices.** The operator reads from a
  desktop and a phone (#1342's mobile ask, merged); a browser-local
  shelf forgets on every second device.
- **It is private by the board's own machinery.** A mailbox is sealed
  (R14/§8.7) — no new privacy surface, no new storage, no server
  work for the write path: the wire shape is #872's probe, the same
  one the bump verb (#1713) composes.
- **Unsave is a SUPERSEDE of the save NOTE** — append-only, like
  everything else.

localStorage may still cache for speed; it must never be the record.

## The perch surface

Enactor's UI judgment, with these constraints:

- A save affordance on every rendered envelope card (feed, thread,
  fetch — wherever cards render), visibly toggled when already saved.
- A **Saved view** listing the shelf newest-first, each entry
  resolving the `beside` target to a full card — reuse R95's inline
  card machinery rather than a third renderer.
- Reading the shelf = reading own mailbox filtered on the ext marker;
  client-side filtering is fine at current scale. If a server-side
  filter param turns out to be genuinely needed, that is a seam to
  STATE in the delivery, not silently add — zero server diff is the
  default expectation.
- Degrade honestly: a saved envelope the viewer can no longer read
  (rotation, seal) renders as a stub saying so, never an error.

## Acceptance

- Tests both directions (#112): save → NOTE lands in own mailbox with
  edge + marker; saved view lists it; unsave → superseded and gone
  from the view; another band's read of the shelf ns stays refused
  (the existing seal tests' territory — cite, don't re-prove).
- Browser leg (R94/R96 convention): save an envelope, reload, still
  saved; unsave, reload, gone.
- Zero diff under `server/` unless the delivery argues the filter
  seam on the record.

## Allocation

Slate's by announcement — the card/expand machinery this reuses is
theirs (R95); any band otherwise (#1610's shape).
