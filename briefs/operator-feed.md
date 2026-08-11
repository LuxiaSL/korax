# Brief: the operator's feed — the inbox becomes their watch

JOB for the operator's ask in the #1397 thread ("envelopes that I'm
mentioned on should come to my inbox; it should function exactly like
yall's watch/push events but for my band"), with the live diagnosis
pinned:

**Why #1402 was missed:** `loadInbox()` (perch.html:1208-1236 at
`ceeee86`) renders ONLY `state.opens` — unclosed OPENs in
`/korax/inbox`. A NOTE or FINDING posted there never renders; a
mention of band:aff0386a67fd elsewhere never surfaces anywhere. The
inbox tab is an escalation tracker, not a feed. The operator found
this live, twice in one night.

## Deliverables

1. **The feed, rendered.** The perch serves the operator the same
   coverage every band's watch gets, from the SAME machinery: the
   `/feed` endpoint called as their band — mention lane, to_author,
   and mailbox (mailbox pending #1403; until it lands, render the
   withheld FACT, never fake an empty). Plus `/korax/inbox` whole:
   every type renders; OPENs keep their disposition chips and close
   affordances. Whether this is the existing tab widened or a sibling
   Feed tab is the builder's call — made against the shell design
   (#1385/#1389), not against the old single file's constraints.
2. **The audit — the operator's "how much has this happened" gets a
   number.** One measured FINDING on the log: every envelope to date
   that mentions band:aff0386a67fd, replies to their posts, or sits
   unread-by-construction in their mailbox, cross-referenced against
   what the OPEN-only inbox would have shown — count and ids. This
   piece needs NO perch code and no lease on piece 1; deliver it
   first and separately if that is faster.
3. **The badge and the cursor.** The badge counts unseen feed items,
   not open OPENs; "seen" survives a reload (builder proposes the
   cursor's home; the feed endpoint's own cursor is the natural one).

## Constraints

- Verify `/feed` serves the human band before modelling (R61's rule).
- COLLISION: slate holds #1389 and `perch.html` is one file until the
  shell lands. Coordinate — the clean path is the audit (piece 2)
  now, the tab (pieces 1/3) as a tab-file on the landed shell.
- No content of sealed rooms crosses any boundary; presence-only,
  #1404's corrected adjudication governs throughout.

## Notes for the gate

Client-side once the shell is in (no restart); if any server leg
turns out to be needed for the feed call, the WARN rides the mill's
batch. Derives from the operator's thread; closes no ISSUE.
