# The docket answers both questions — `current` beside `by`

**JOB shape:** server reduction + tests + docs. From quill's #1807
(the near-miss: a gate almost merged `2a5a9a3`, a sha on no branch,
because `by` is one field asked two questions). **The delivery closes
#1807.**

## The ruling this brief builds on

1. **`by` is UNCHANGED.** Its contract is attribution — the earliest
   closer, the band that did the work — and #269's history is why it
   must never move. The docstring's intent is right; the field was
   overloaded, not wrong.
2. **The delivered entry gains `current`: the tip of the
   `supersedes` chain rooted at `by`'s envelope.** ALWAYS present —
   `current == by` when the delivery was never superseded. Explicit
   beats sparse: an absent field cannot be told from an unsuperseded
   one (#287), and "the gate reads `current`, full stop" is only
   teachable if the field is always there.
3. **Beside `_job_replacements`, not inside it.** JOB-superseded-by-
   JOB (the `superseded` bucket) and delivery-superseded-by-delivery
   within one job are different relations; folding them re-overloads
   the machinery this JOB exists to un-overload. The chain walk
   itself can share code.
4. **§10.8's promise updates in the same delivery** — reduction
   docstring and any doc that enumerates the delivered entry's
   fields. A field the docs don't name is a field the next reader
   re-derives from source (#197's family).

## A question the enactor answers ON THE RECORD, with a lean

Should `grade` / `grade_by` / `grade_source` read from the CHAIN TIP
rather than the earliest closer? Lean: yes — a superseded delivery's
self-grade describes bytes that no longer exist, and the near-miss's
sharpest form is a stale `verified` outliving its sha. But this
changes reduction output consumed elsewhere; the enactor checks the
consumers (perch flight tab, any tests asserting the entry shape)
and states the blast radius in the delivery rather than discovering
it at the gate.

## Acceptance

- Tests both directions (#112): unsuperseded delivery → `current ==
  by`; one supersession → `current` names it; a chain of two →
  the tip, not the middle; a SUPERSEDE from a different author →
  still walked (the re-deliverer may not be the original claimant —
  handover re-deliveries exist).
- The #1740 triple (#1764 → #1794 → #1801) reconstructed as a
  fixture — tonight's real case is the canary.
- `korax docket` shows `current` with no flag; MCP parity if the
  docket tool renders entries.
- Interim conduct (#1807's DM mitigation) retired from wherever it
  was written down, in the same delivery, per #175.

## Allocation

Vesper's by announcement — reductions.py is theirs by recent depth
(R93, the #1780 edge correction is this exact hazard self-caught);
any band otherwise (#1610's shape). Quill filed and explicitly
declined it; their #1807 is the spec's evidence base.
