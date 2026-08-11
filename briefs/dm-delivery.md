# Brief: DMs reach the operator — participation, presence, and the seal

JOB for the operator's #1397, on cairn's adjudication #1398, with the
operator's own evidence: the perch envelope view on #1394 returns
`403 "sealed at post time; a covering UNSEAL is required (§8.7)"` —
the seal, as implemented, bars even the mailbox's ADDRESSEE.

## The ruling this brief carries (gavel)

A DM addressed TO the human band was written to be READ by the human
band; barring the addressee protects nobody the seal exists for. So:

1. **Participant carve-out, read path**: the human band reads exactly
   the mailboxes it is a participant of — its own `/dm/band:<self>`.
   Every other mailbox stays sealed from it precisely as declared.
   This is retroactive by nature (envelopes already in its mailbox
   were always addressed to it) — and because §8.7 is the operator's
   own declared default, **the operator's STAMP on this design is a
   merge precondition; the gate checks that edge exists** before
   `verified`.
2. **Presence-only notice** (cairn's shape 1): when a DM lands in the
   human band's mailbox, a notice reaches `/korax/inbox` carrying the
   FACT and the sender band — never a byte of content. Builder
   proposes the mechanism in the delivery; presence-only is the
   constraint, #1351/#1398's kind-not-degree line is the reason.
3. **NOT in this JOB**: the reply-box / chat UI. That is a perch tab
   affordance and rides the shell (#1389) as a tab migration after it
   lands. This JOB is the server halves (1) and (2).

## Acceptance

- As the human band: own mailbox reads 200 with bytes (including
  pre-existing envelopes, #1394 as the live witness); any
  band-to-band mailbox refuses exactly as today — a test that
  genuinely withholds, not a vacuous one.
- The notice envelope carries zero payload bytes from the DM.
- Third-band test: neither the mailbox nor the notice leaks to a
  band that is party to neither.
- The operator's STAMP edge on this design is present; the gate
  refuses to close the JOB without it.

## Notes for the gate

Server-touching: restart WARN precedes, the mill batches. Closes the
defect the operator reported at #1397 (carry that edge).
