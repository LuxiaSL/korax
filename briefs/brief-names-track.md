# Briefs name their track, or say none: the map enters the working language by test

Track: v2 R3 (`tooling-roadmap-v2.md`). Source: #3759 §2 / #3760 §2a —
the map's vocabulary appeared in 3 substantive of 27 briefs written
during its life; "a JOB is cut from a brief; if the brief does not name
a track, nothing downstream can, and the ledger line inherits the
silence." One claimable item (#2589). Repo test only; no server, no
client; gate owed for the server suite (where repo tests live).

## Why

The v1 map was sha-verified, cited by both seats throughout, never
amended, and never entered the briefs. The next postmortem should grep
the briefs and find the map in them — or find `Track: none` and know
the work was deliberately off-map. Either is a record; silence is the
thing this postmortem spent a sitting reconstructing.

## The properties

1. **Every brief added at or after the v2 sha carries a `Track:` line
   in its first ten lines**, of the form `Track: v2 R<n>[<letter>]
   (...)` naming a row in `tooling-roadmap-v2.md` — or `Track: none —
   <one-line reason>`. Briefs that predate v2 are exempt by date, not
   grandfathered by edit: touching an old brief does not oblige a line.
2. **The row named must exist** in the current `tooling-roadmap-v2.md`
   §2 (or its successor, when one supersedes it — the test reads the
   map's own row list, not a copy).
3. **`none` is a reason, not an exemption.** The reason is free text
   and the test only checks it is non-empty; the point is that the
   choice was made where a reader can see it.
4. **The test is in the server suite** beside `test_revisions_ledger.
   py`, parses the map's rows out of the map file (no duplicate list,
   #2595's rule), and names the offending file and line on failure.

## Acceptance — red-first

1. A planted brief with no `Track:` line under `briefs/`, dated after
   the v2 sha, reddens the test with its path; removed, green.
2. A planted brief naming `Track: v2 R99` reddens (row does not
   exist); `Track: none — spike` is green.
3. Every brief in this map's §3 manifest passes as committed (they
   carry the line from birth); the pre-v2 exemption is tested with one
   existing brief lacking the line (e.g. `gate-scope.md`) staying green.
4. The row list the test reads is the map's: renaming a row in §2 and
   not in a brief reddens that brief — tested once by mutation, quoted.

## Edges the delivery carries

`closes` → this JOB. `derives-from` #3759, #3760. Ledger: disclosed
commit, no number (a test; nothing the design doc describes changes).

## Recusals and sequencing

None. Smallest item on the map; a first pick for a seat proving its
write path.
