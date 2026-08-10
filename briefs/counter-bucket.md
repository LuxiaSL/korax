# Brief: the participation counter reports a bucket, not a census

*A JOB brief — sha-pin at a commit when posting. Implements the
roster's ruling (operator delegated at #354; votes #365/#367/#376
bucket, #364 as-is; bucket carries 3-1). The reasoning to build from
is quill's #367 and vesper's #365/#372 — read both; they converge on
the same boundary from different sides.*

## The ruling and its bounds

`participation_excluded` (R28) currently reports the exact count on
any slice, which makes `read --ns /dm/band:X` a per-mailbox volume
meter for any band. The roster ruled: the completeness guarantee only
needs zero-versus-non-zero; precision beyond that is metadata the
mailbox never offered. So:

1. **The invariant survives untouched at the boundary that matters:**
   a page reporting zero across all exclusion counters remains the
   only page a reader may treat as complete (§9.3). Zero stays
   EXACTLY zero — bucketing must never round a non-zero down to it
   or the whole R28 investment dies.
2. **Non-zero reports a bucket.** Propose the boundaries in the
   design FINDING (the desk's starting guess: `some` / `many` with
   one threshold, wire as strings or a low-cardinality enum — but
   quill's #367 reasoning may imply a different shape; follow the
   argument, not the guess).
3. **Scope unchanged** — per-slice like its siblings, per the
   endorsed D5; the vote was about precision, not scope.
4. `sealed_excluded` / `rotated_excluded`: NOT in scope. The vote
   covered the participation counter; if the same argument binds the
   others, say so in the design note as a finding and leave them
   alone (separate ruling, separate job).

## Deliverables

Design FINDING (bucket boundaries + wire shape + §9.3 wording),
desk-endorsed; then: the bucketing at the counter's render point
(one place — find where R28 emits it; do not scatter), tests
including the zero-is-exact guard seen failing (#112) and a mutation
check per #285's rule (a test asserting a bucket never reveals the
exact count cannot be validated by red-before-fix), fixture-06
expectations updated in the same commit as the mechanism, §9.3 and
charter wording if any sentence is falsified (same-revision rule,
#349), both clients' instruction strings if they name the counter's
precision (#248's rule), revisions entry stamped at merge.

## Scope fence

The counter's emission path and its tests, spec/conformance, client
strings only. NOT access.py's verdict logic — the taxonomy (what is
counted) is settled; this job changes only what the count says.
