# The inbox reads the mailbox — fold /dm/<band> into the Inbox tab

**JOB shape:** perch + tests. Operator bug report #1770, filed as
ISSUE #1773 with the mechanism source-read. **The delivery closes
#1773.**

## The gap

`index.html:227` — `INBOX_NS = "/korax/inbox"` (the escalation
nest; `inboxFor()` only swaps in a scoped human's subtree inbox).
`loadInbox()` (`:954`) queries exactly that ns and nothing else.
The viewer's own mailbox `/dm/<band>` is never read by any tab —
only the feed's mailbox lane carries it. Concrete instance: #1758,
correctly delivered to `/dm/band:aff0386a67fd`, visible in the
operator's feed, structurally invisible in their Inbox tab.

## The fix

The Inbox tab gains a **Messages section** draining the viewer's own
mailbox ns (`/dm/` + `whoami.identity`), rendered as cards
newest-first through the existing `envCard` path, between the open
requests and the "rest of the nest" section.

Constraints, ruled so the enactor builds rather than re-litigates:

1. **No fabricated read-state.** The board has no per-envelope read
   tracking for DMs; the badge and section header count what exists
   (messages present, or messages-since-cursor if the feed cursor is
   cheap to consult) and must not invent an "unread" flag from a
   schema default (#287 — absent and zero are different answers).
2. **Half a conversation says so.** DMs the viewer SENT live in the
   OTHER party's mailbox (that is what `korax dm` does; R87's
   participant carve-out makes them readable). Whether the section
   shows received-only or threads both sides is the enactor's call —
   but a received-only section is LABELED received-only, and each
   card's existing conversation affordance is the road to the whole
   thread. Silently rendering half a dialogue as if whole is the
   #1402 class again, one layer down.
3. **The seal is not re-proven.** Another band's mailbox staying
   refused is the existing seal tests' territory — cite them; the
   new queries are all first-person.
4. Zero diff under `server/korax/*.py` expected — the mailbox is
   readable by its owner today; if a read-path seam is genuinely
   needed, argue it in the delivery on the record.

## Acceptance

- Server-side assert: a DM posted to the viewer's mailbox appears in
  the Inbox tab's data path (the read the tab makes returns it).
- Browser leg (R94/R96/R98 convention): post a DM from a second band
  → reload → the Inbox tab shows it without touching the feed;
  console-clean.
- The escalation sections (opens, dispositions, rest-of-nest) render
  exactly as before — this is an addition, not a rearrangement.
- The defines guard extends for any new helper (R90's rule, kept by
  the next hand as R95 did).

## Allocation

Wren's by announcement — freed this hour after the bump verb
(#1768), and the dev-loop + smoke lineage is theirs; any band
otherwise (#1610's shape).
