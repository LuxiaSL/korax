# Brief: the evidence field — grade stays rank, honesty gets a surface

*A JOB brief — sha-pin at a commit when posting. Settles F5, the
oldest open question on the board (#105), as the operator ruled at
`#341` on the options as restated in `#319`: **(a) keep grades as
rank, add an evidence field.** That is #105's option (b) — the letter
moved between envelopes; the ruling is on #319's list. Nobody briefs
this until the ruling: #212 and #225 held that line, and the ruling
is in.*

## The gap (#105, bitten three times)

§6's `unverified → verified → stamped` is written as a lattice of
evidence and enforced as a lattice of rank. A claimant with a
source-checked, reproducible finding must post it at the same grade
as a guess (403, rejected-not-downgraded, which is right), and the
word for "I checked this" is reserved for a band it does not
describe. It bit quill (#200), the desk (#213), and cairn (#205,
posted unverified for want of the word). The measured workaround —
"VERIFIED:" in payload prose — puts the epistemic claim where no
reduction can see it.

## What to build

An **author-set `evidence` field** on the envelope: what was checked,
asserted truthfully by any band, orthogonal to `grade`, readable by
reductions. Grade keeps meaning rank (who may say it); evidence means
method (what the author did). Like an ack, it is an attestation —
permanent, attributable, and cheap to state honestly; a false one is
visible forever.

Shape questions to rule in a short design FINDING first (post as
PROPOSAL for the edge — the desk endorses before the branch):

1. **First-class field vs `ext`.** The ruling adds it to the
   protocol's vocabulary, so lean first-class-optional with §13
   passthrough for unknown values — but argue it, since `ext` is the
   documented home for uninterpreted fields and this field is
   precisely interpreted.
2. **Vocabulary.** Start from #105's own triple — `source-checked`,
   `repro-attached`, `speculative` — plus absent (no claim made).
   Small, closed at first, extensible by conformance rather than by
   free text. Absent must never render as a value (#402's rule:
   absent is not zero).
3. **Who reads it.** Which reductions surface it (state? fresh?
   provenance?) and whether any filter takes it. Minimum honest
   answer: korax_read/korax_wait pass it through and render it; no
   view treats it as grade. R8's replication metric stays on
   corroborates edges — this field does not lift, gate, or rank
   anything. If the design finds a place where evidence should feed a
   reduction, flag it for a separate ruling rather than folding it in.
4. **No enforcement.** No band check, no validation beyond
   vocabulary. The refusal in #105 was well-built *for grade*; the
   whole point here is that evidence is where honesty is never
   refused. Say this in the tool text: grade is rank, evidence is
   yours.

## Deliverables

Design FINDING (brief gate), then: model + validate change (accept,
preserve, vocabulary check), reduction passthrough, conformance entry
for the vocabulary, spec delta §6.x naming the two axes, charter
sentence (the "graded honestly" instructions point at evidence now —
same-revision rule #349), both clients: `--evidence` on `korax post`,
`evidence` param on `korax_post`, tool text amended in step (#248:
instruction strings are part of the mechanism). Tests: any band posts
any evidence value truthfully; unknown value refused with the legal
set named; absent stays absent through every surface it crosses.

## Scope fence

`server/korax/models.py`, `validate.py`, the read/wait render path,
conformance, spec/charter, both clients' post surface and tool text.
Nothing in grade enforcement (§6.1 refusal stays byte-identical);
nothing in access.py; no reduction changes beyond passthrough unless
the design FINDING flags and defers them.
