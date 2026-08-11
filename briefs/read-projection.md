# Brief: the read projection — structure without rhetoric

JOB for remedy 3 of the perf pass (#1431; quill's #1396 measured the
motivating case: the perch pulls 4.36 MB — the whole visible log —
on first paint to compute ~20 namespace strings, because the read
path cannot return envelopes without their payloads).

## Deliverable

1. `/read` (and `/search` if the same seam serves both cheaply) gains
   a projection — `fields=` or a `summary` mode — returning
   id/ts/ns/type/author/grade/refs/ext-presence and OMITTING
   `payload` (and pointer bodies). §9.3 is untouched: the projection
   filters FIELDS of envelopes the requester may already read; it
   never widens what is visible, and the exclusion counters ride
   unchanged.
2. Both clients can ask for it (CLI flag; MCP parameter) — the
   #1177 lesson rides: the parameter's description says what it
   bounds and what it does not.
3. The perch's `nsIndex` (and any boot-path caller that wants
   structure, per #1396's list) switches to it — expected ~95% cut
   on the boot transfer. The `loadLedger`/`loadGraph` per-click
   re-pull caching is NOT this JOB (light-tracked separately).

## Acceptance

- Byte measurement before/after on the boot path, same method as
  #1396 (curl, sizes on the log).
- A projection response for a mixed visible/withheld slice carries
  identical counters to the full read of the same slice.
- The projected shape round-trips through both clients' surfaces.

## Notes for the gate

Server-touching: restart WARN, mill batches. Design note: this is a
read-surface ADDITION with §9.3 contact, so the gate reads the
counter tests hardest; #1431's ranking says it is a bandwidth fix,
not the latency fix — the herd (#1431 remedy 1) stays a separate,
design-gated thread.
