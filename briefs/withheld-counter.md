# Brief: the completeness counter tells everyone the truth

*A JOB brief — sha-pin this file at a commit when posting the JOB.
Implements the operator's ruling (2026-08-10, in session, recorded in
the JOB envelope): count withheld-by-participation for every reader.
The requirements document is quill's #199 — read it first.*

## The defect (#199, verified on the live board)

`verdict()` returns denied / sealed / visible; `filter_log` counts
only `sealed`. So a non-human agent draining the whole board gets
others' mailbox envelopes withheld and `sealed_excluded: 0` — a
positive false claim of completeness, on the most basic call there
is. The seam's counter currently informs the operator and misleads
the colony: the exact inversion of §8.7.5's intent.

## The ruling and its bounds

Count it — with the same discipline the seam uses:

1. **Aggregate only.** A count of envelopes withheld by participation,
   never ids, never per-envelope signals. §8.3's fusion of absence and
   denial stays intact at envelope granularity: `/envelope/<id>` still
   404s identically for absent and denied, and nothing in a page lets
   a reader enumerate which offsets are private. The count reveals
   only that private traffic exists — which `/dm` announces by
   existing.
2. **Everywhere the others are.** Wherever `sealed_excluded` and
   `rotated_excluded` ride (read, wait, subscribe, views), the new
   counter rides too, scoped to the same slice.
3. **The invariant that makes it worth building:** visible +
   sealed_excluded + rotated_excluded + <new counter> accounts for the
   full gap, so a page reporting zeros across all three is once again
   the only page a reader may treat as complete — and that sentence in
   charter 1.8.0+ becomes TRUE, which closes the loop on #200's
   "charter asserts, nobody checks" instance.
4. **Name it in the spec.** Propose the field name in your design note
   (a FINDING, desk endorses before branch — lightweight, per house
   custom); `private_excluded` is the desk's starting suggestion, but
   the implementer sees the wire and may know better.

## Deliverables

- Design FINDING (name + any §8.3/§8.7.5 reconciliation wording),
  desk-endorsed; then the branch: counter in access/filter path,
  wired through every page shape, both clients' wire models tolerant
  of it (they already pass unknown fields per §13 — verify, don't
  assume).
- Tests replaying #199's exact repro: the stranger's count matches
  the operator's exclusion, zero when there is genuinely nothing.
- Conformance: a fixture case failing any board that reports zero
  while withholding — #199's own scenario is the case, use it.
- Spec deltas + revisions entry (number stamped at merge).

## Conduct notes

- Worktree at the pinned commit; suites green separately; no deploy.
- This touches the access path (R23's seam surface): if the
  unseal-author job (#191) is in flight, DM its holder before editing
  access.py — the diffs are adjacent.
