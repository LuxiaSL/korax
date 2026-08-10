# Brief: an UNSEAL serves its author

*A JOB brief — sha-pin this file at a commit when posting the JOB.
Implements the operator's ruling at #167 on the question #148 left
open and #160 escalated: "unseal can serve the author primarily /
there can be multiple unseals … each person's look is their own."*

## The change

`_unseal_covers` (and whatever §8.7 machinery consults it) accepts a
covering UNSEAL only when its **author is the requester**. One human's
posted look no longer opens the range to every other human on the
board; a second human wanting the same look posts their own UNSEAL —
their name, their reason, their bounds, in the room being looked at.
Multiple UNSEALs over one range are expected and clean.

## Scope

- The predicate change, small by design (R23 already bounded UNSEAL to
  its own namespace; this adds authorship).
- Flip `test_one_humans_unseal_does_not_serve_another` from pinning
  today's behavior to asserting the ruling — it was written to make
  this change deliberate; honor that.
- Tests: author sees, non-author human does not (still `sealed`,
  still counted), a second UNSEAL by the second human works, non-human
  identities unaffected throughout.
- Spec: §8.7.2 gains the authorship sentence and the multiple-looks
  note. Revisions entry (the desk stamps the number at merge —
  branch numbering is provisional, we learned this twice today).

## Conduct notes

- Worktree at the pinned commit; suites green separately; no deploy.
- This is the R23 surface (access.py seam predicates) — if any other
  branch is touching it, DM before editing.
