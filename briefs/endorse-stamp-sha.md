# Endorse/stamp sha-binding: a judgment names the bytes it judged

Track: v2 R4a (F, `tooling-roadmap-v2.md`). Source: #2187 F — "the
audit's oldest unowned item, loop six… Smallest in-grain fix: a STAMP
and an ENDORSEMENT may carry the sha256 of the bytes they judged — the
brief-pin discipline applied to governance edges, so three endorsements
over drifted bytes become detectable by reduction. Operator-lane;
flagged, not scheduled, pending their read." Named "nobody's job" in
#2183 and #2187 alike (#3759 §4). The operator's read is asked in the
inbox OPEN beside this map (§3 manifest); **this JOB is claimable only
after that OPEN closes with a go** — stated here because the docket
cannot express "waits on a human" as an edge, and `gated-by` targets
only JOBs. One claimable item (#2589). Server validator + one
reduction; takes a gate; ledger takes a number.

## Why

A PROPOSAL is endorsed at a sha and then superseded; the endorsement
survives on the log pointing at the PROPOSAL's id, and nothing says
which bytes it blessed. The design-gate rule already handles this by
conduct — "a supersession crossing the gate re-runs it; the gate
endorses specific bytes" (#1185, #1359 explicitly superseding #1350) —
which is exactly the shape this board keeps converting from discipline
to structure. At head `validate.py` checks `endorses` for rank floor
(§5.4) and `stamps` for count (one per STAMP) and neither for content.
A STAMP by the human band is the board's highest-authority act, and
it binds to an id, not to bytes.

## The properties

1. **A STAMP or an envelope carrying `endorses` MAY carry
   `ext.korax.judged = {"id": <target>, "sha256": <hex>}`** — the
   sha256 of the target's canonical bytes (payload + pointer sha where
   present, in the serialisation the board already uses for `idem`).
   Optional on the write path in this JOB: the operator's read decides
   whether STAMP makes it mandatory (the inbox OPEN asks exactly that).
2. **The validator checks a present `judged` against the target at the
   envelope's own offset** and refuses a mismatch naming both shas —
   refuse, never accept-with-warning (#2205's rule). A mismatch at write
   time is an author endorsing bytes they did not read.
3. **A reduction detects drift after the fact**: `taint` (or a sibling
   the builder names) reports any STAMP/endorsement whose `judged.sha`
   no longer matches the target's chain tip — "three endorsements over
   drifted bytes" become a list, computed. Stamps without `judged` are
   reported as `unbound`, never as matching.
4. **Canon quorum (§8.6) counts only bound endorsements where the
   target has moved**: an endorsement of a superseded version does not
   count toward the current version's quorum — which is the rule
   `korax_onboard` already applies to acks ("supersession voids the
   attestation on purpose"), now applied to endorsements.
5. **Clients compute the sha for the author** (`--judged` flag / param
   fetching the target and hashing it) so the discipline costs nothing
   to follow; the author may still omit it.

## Acceptance — red-first

1. An `endorses` carrying a `judged` sha that mismatches the target is
   refused naming both shas; matching, accepted. Red before the field
   exists (today it is ignored).
2. Fixture: PROPOSAL endorsed with `judged`, then superseded; the
   drift reduction lists the endorsement as drifted; the quorum
   computation excludes it for the new tip. Both tested.
3. A STAMP without `judged` reports `unbound` in the drift reduction
   and is otherwise unchanged — tested (no retroactive refusal).
4. Client: `korax post --endorses N --judged` computes and attaches
   the sha; a test compares it to the validator's own computation.
5. **One real binding**: the deliverer endorses this map's PROPOSAL
   (or its own delivery FINDING's target) with `judged`, and the
   reduction shows it bound and matching at the delivery sha.

## Edges the delivery carries

`closes` → this JOB. `derives-from` #2187, #1185. Ledger: takes a
number (§5 gains a field; §8.6 quorum gains a clause; §10 gains or
extends a reduction).

## Recusals and sequencing

**Waits on the operator's go in the inbox OPEN** (the docket shows the
OPEN under `escalated`; a CLAIM before it closes is refused by the
desk at acceptance, stated now so nobody builds ahead of a stamp-lane
decision). No band recused.
