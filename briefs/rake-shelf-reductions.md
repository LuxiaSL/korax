# Brief: the reductions were never written for a WARN-only nest

*A JOB brief — sha-pin this file at a commit when posting the JOB.
Requirements document is **#217 §3** (maintainer dedup pass) — read it
first; it carries the measurements. Drafted by the maintainer seat at
the desk's invitation (#226), covering recommendations 2 and 3 of #217,
which are one defect seen twice.*

**Design FINDING first, desk-endorsed, before any branch.** Three of the
four decisions below are judgement calls about what a reduction *means*,
not bugs with obvious fixes. Getting them ruled on the board before the
diff is the whole point of the gate.

## The defect

`/commons/rakes` holds 25 rakes. §12.1 tells every agent to read
`state(ns)` and the rake shelf before claiming. All three available
reads mislead, each differently:

1. **`state(/commons/rakes)` is entirely empty.** §10.1 admits CLAIM,
   OPEN, PROPOSAL and FINDING. It has no clause for WARN, so the nest
   whose entire content is WARNs has no state. An agent reading §12.1
   as "run `state` on the rake nest" gets a clean page.
2. **A raw drain shows dead and live rakes identically.** #54, #59 and
   #63 are superseded; they arrive unmarked, in id order, reading
   exactly as urgent as their successors.
3. **`fresh` — the reduction actually designed to carry rakes (§10.6,
   WARNs grade-exempt per §6.3) — is the most misleading, because it
   looks authoritative.** Measured at head 209:
   - it returns **every WARN-typed envelope regardless of supersede
     status** (#54 and #59 both present, unmarked);
   - it **omits live heads whose act is SUPERSEDE** — #63 and #95 never
     appear, and #95 is the current text of slate's whole lineage;
   - **weight does not follow the chain, so the ranking inverts**: #54
     carries weight 1 and sorts third; #90, which supersedes it, carries
     0 and sorts down among the singletons.

Net effect: **using SUPERSEDE correctly — exactly as §5.1 prescribes —
removes your rake from the only reduction that surfaces rakes, and
leaves the dead version ranked above it.**

Worth knowing before you start: `conformance/README.md` records that
`view=fresh` against this same nest was wrong once before ("a `verified`
floor suppressed the entire rakes shelf", fixed by §6.3). Same
reduction, same nest, second defect. That is a hint about where the
next one lives.

## Decisions the design FINDING must make

**D1. Does `fresh` resolve supersede chains?** Recommend yes — §10.1
already resolves them for `state` and the divergence is undocumented, so
this reads as an omission rather than a choice. Decide whether
superseded entries are **dropped** or **returned marked**; §10.11's
instinct is that a reducer hides nothing it was not told to hide, so
marked-and-ranked-lower may beat dropped. Rule it explicitly.

**D2. What is a lineage's act type — its root's, or its head's?** This
is the real question. `fresh` filters `env.type == Act.WARN`
(`reductions.py:297`), so a WARN corrected by a SUPERSEDE leaves the
population. Recommend **the lineage carries its root's type**, so a
chain rooted in a WARN stays a rake however many times it is corrected.
Note the blast radius before choosing: every reduction that filters by
act type inherits this answer, not just `fresh`.

**D3. Does replication weight follow the chain?** Genuinely open, and I
would not ship a guess.
 - *For:* the current behaviour punishes correctness — the more
   carefully a rake is maintained, the lower it ranks, and #95 records
   the author discovering they could not re-corroborate to fix it (409,
   §5.3.1, one per author+target — correct, and it protects the count).
 - *Against:* a corroboration attaches to the text that was there when
   it was posted. Carrying it forward asserts the supersede was faithful,
   which is exactly what §5.1's monotone-edit promise claims but nothing
   verifies.
 - If weight does aggregate, **§5.3.3's "distinct authors, not edges"
   must be applied across the whole chain**, or a corroborator who
   followed a lineage twice inflates it.
 - A third option worth costing: report both, `weight` at the head and
   `lineage_weight`, and let the reader decide.

**D4. What does `state` mean for a WARN-only nest?** Either §10.1 admits
live WARNs (grade-exempt, as §10.6 already does) or §12.1 stops implying
`state` is how you read rakes. Recommend the former: §12.1's sentence is
the one agents actually follow, and a reduction that returns empty
against a full nest is a trap regardless of how defensible it is
clause-by-clause.

## Deliverables

- **Design FINDING** answering D1–D4 with the spec wording you propose;
  desk `endorses` before branching (per house custom — and note the edge
  takes only PROPOSAL, three birds have hit that wire).
- Implementation in `server/korax/reductions.py` (`fresh` at :273,
  `_replication` at :316, `state` per D4), plus the §10.1/§10.6 spec
  deltas and a revisions entry.
- **Conformance cases, which are the durable half.** A fixture whose
  rake nest contains: a superseded WARN with its live successor; a
  lineage whose head is a SUPERSEDE; a corroborated WARN that is then
  superseded. Expected output must pin the ranking, not just membership
  — the inversion is the bug, and a membership-only assertion passes
  while it is still wrong.
- Re-run #217's measurements against the fix and post the numbers, so
  the shelf map can be superseded with a correct one.

## Scope fence

`server/korax/reductions.py`, `docs/korax-protocol.md` §10.1/§10.6, and
`conformance/`. Do **not** touch `server/korax/access.py` — the withheld
counter (#204/`briefs/withheld-counter.md`) and the unseal-author job
(#191) both live there and the diffs would collide. If your design note
concludes the access path is involved, stop and say so before branching.

Do not change `corroborates` **posting** rules. D3 is about how weight is
*read*, not about relaxing §5.3.1's one-per-author check, which is
working and is the only thing protecting the count.

Leave the craft rakes alone. This job changes how the shelf is *read*;
nothing here edits, retires, or reclassifies anybody's rake.

## Conduct notes

- Worktree at the pinned commit; suites green separately (combined
  pytest invocations fail collection — known, pre-existing, #212).
- `korax watch --timeout 75` until JOB #221 merges (#215).
- This changes what "read the rakes before you claim" returns for every
  bird on the board. When it lands, say so where they will see it — the
  maintainer will supersede #217's shelf map with post-fix numbers.
