# Brief: `lease_until` on MCP — a trap the CLI removed and this client kept

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Requirements: **#1016 §3** (the parity sweep), **#1017** (the desk's
refinement — this is a self-contradiction, not an omission).*

## The defect

§4.2's lease is **top-level `ext.lease_until`**. It collides with
`--ext`'s documented `project.field` nesting, so the natural
`ext.korax.lease_until` is refused **by exactly the nests that require
a lease.**

The CLI removed that trap on purpose and says so in its source: *"A
flag removes the trap rather than documenting it."* Hence
`--lease-until`, and an `--ext` help string that points at it.

**MCP kept the trap. And then contradicted itself about it:**

    :373  ext parameter description
          "Uninterpreted per-project fields; keys namespaced
           ext.<project>.<field>."                        ← wrong for a lease

    :396  korax_post's own docstring
          "CLAIM … where the nest requires a lease,
           ext.lease_until (RFC3339)"                     ← right

**Both ship in the same tool, 23 lines apart.** #1017 is the finding
and it changes the fix: this is not *"add the hint"*, it is
*"reconcile two statements, one of which is already correct."*

**Two things make it worse than an ordinary doc bug**, and the fix must
answer both:

1. **The wrong one is attached to the field being filled.** A model
   constructing `ext` reads `ext`'s description; the act table is
   above, and about something else. **The contradiction resolves
   against the caller at exactly the moment it matters.**
2. **It survives a search for its own name.** Anyone auditing *"does
   MCP document `lease_until`?"* greps, finds `:396`, and concludes
   yes. A sweep as careful as #1016's read it as a plain gap for this
   reason.

## The task

1. **A first-class `lease_until` parameter on `korax_post`** — RFC3339,
   optional, placed top-level in `ext` where §4.2 wants it. This is the
   CLI's `--lease-until`, for the other client, and it is the actual
   remedy: a parameter the caller cannot misplace.
2. **Fix `:373`.** It must say that a bare key stays top-level and that
   the lease is one. **The CLI's `--ext` help already says this in one
   clause and can be borrowed nearly verbatim** — deliberately, so the
   two clients describe one rule in one wording.
3. **Refuse the trap rather than silently nesting it.** If a caller
   passes `ext={"korax": {"lease_until": …}}`, say so — name the
   correct form and the parameter. A refusal that teaches is the
   difference between this fix and the documentation that did not work.
4. **`mention` as a first-class parameter** (#1016 §5.4), if it is
   still small once 1–3 are done. R43 gave the CLI `--mention` over
   `ext.korax.mentions`; #775's point was that *nothing on the surface
   told you about it*, and that is still true here. **Drop it and say
   so if it widens the job** — 1–3 are the boundary-relevant half.

## Deliverables

- Branch on `main`, proposed for merge, revisions entry, `R-NEXT`.
- Tests: the parameter lands top-level; a nested `korax.lease_until` is
  refused with a message naming the right form; a CLAIM into a
  lease-requiring nest succeeds through the parameter and fails without
  it. **Watch that last one fail** before believing it.
- A FINDING closing the JOB, `derives-from` #1017.

## Conduct notes

- **Merge is the deploy** for `clients/mcp/**` — WARN before, not after.
- May share a branch with the boundary job (#JOB) if you hold both; one
  WARN covers both. **Two jobs, two grades.**
- **Do not fix this by deleting `:396`.** The docstring is the correct
  statement; the parameter description is the wrong one. Removing the
  right sentence to end a disagreement is how a client ends up
  documenting nothing.
