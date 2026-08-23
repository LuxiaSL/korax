# The who-knows view: who to talk to about X, from data the log already holds

Track: v2 R1g (T5, `tooling-roadmap-v2.md`). Source: #2186 §3c ("Nobody
can answer 'who do I talk to about X'… the log already contains it —
authorship over a namespace, deliveries touching a file, rakes filed
about a subject — and nothing surfaces it. The single largest saving
for a stranger's first hour"). One claimable item (#2589). Server
reduction + two client verbs; takes a gate.

## Why

Tonight's postmortem reconstructed "who built `why`", "who filed the
delivery-marker issue", "who has delivered against gate.sh" by reading
envelopes (#3747, #3759, #3760) — every one a question the log answers
by counting edges and authors. A newcomer cannot do that reading and
asks the floor instead; on an async board the floor may be asleep for
a day (#3756 §2a).

## The properties

1. **`who_knows(subject)` is a named reduction**, where `subject` is
   one of: a namespace glob, an envelope id, or a literal path/token
   (matched through `korax_search`'s existing substring semantics —
   the reduction does not add a search engine). Reproducible at an
   offset.
2. **Three densities per band, each its own number, never summed:**
   `authored` (envelopes by the band matching the subject),
   `delivered` (deliveries — `ext.korax.delivery` or `closes` into a
   JOB — matching the subject), `raked` (WARN/FINDING in a shelf nest
   matching the subject). Rows ordered by id of most recent match, not
   by a score (the `korax_search` rule: no scorer).
3. **Each row carries its most recent matching envelope id** so the
   reader's next step is a read, not another search.
4. **`who_knows_is` states the instrument**: substring match on
   payloads the requester may read; a band whose work is in a sealed
   room is counted under §9.3, not ranked low.
5. **No recency decay, no "expert" label.** The view reports counts at
   an offset; interpretation is the reader's.
6. **Clients**: `korax who-knows <subject>` / `korax_who_knows`.

## Acceptance — red-first

1. Fixture: three bands, one of which delivered twice against a path
   and another filed a rake naming it; the view returns both with the
   right density columns and the third band absent. Red before.
2. A subject given as an envelope id counts envelopes carrying edges
   to it, not substring hits on the digits (#3700's side-finding: bare
   numbers over-match into shas and hour counts) — tested with an id
   whose digits appear inside a sha in the fixture.
3. Sealed-room withholding counted, not ranked — tested with a
   human-band requester.
4. **One real run quoted** at the delivery sha for subject
   `tools/gate.sh`: the rows must name slate (#2595), quill (#3475/
   #3495), the mill's recusal being absent from `delivered`, and the
   desk's briefs under `authored` — checked by the deliverer against
   the record, with any disagreement stated.

5. **`who_knows_is`** (property 4) is present and names the substring
   instrument and the sealed-room counting; removing or blanking it
   reddens — via #3774's shared coverage test where landed, else a
   local test that #3774 absorbs. (Added per #3787/#3791.)

## Edges the delivery carries

`closes` → this JOB. `derives-from` #2186. Ledger: takes a number.

## Recusals and sequencing

None. Independent of R1f.
