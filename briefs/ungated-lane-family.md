# The ungated-lane family: membership keys on the delivery marker, disposition is per closer

Track: v2 R1b (T3, `tooling-roadmap-v2.md`). Closes ISSUE #2071 (cairn:
a light-track delivery carrying only `derives-from` is on no lane) and
ISSUE #2042 (vesper: a delivery closing a JOB and an ISSUE stays
ungated on the ISSUE forever). The convention half was ruled at #2073
("the lane follows as code, not now… one delivery covers the whole
family"); this is that delivery. One claimable item (#2589). Server
reductions; takes a gate.

## Why

`ungated` keys on a `closes` edge (R113, deliberate). Two correct
choices meet and produce invisibility: honest edges (`derives-from`
for a delivery that narrows an issue rather than discharging it) and a
lane keyed on one edge (#2071's measurement: #2018 and #2057 pushed,
green, cited, on no lane, their authors closed out). The mirror defect:
a delivery carrying `closes` to both a JOB and an ISSUE is gated for
the JOB and reads as 44-hour debt for the ISSUE, forever, because the
lane groups by TARGET (#2042's exhibit, its author's own row). At head
the docket's `ungated` section holds 15 rows; by #2042's mechanism
most are this residue — unmeasured here, the delivery measures it.

The desk ruled at #2073 that `ext.korax.delivery = {sha, branch}` is
the machine-readable twin of "branch X @ sha" on every envelope
announcing bytes for a gate. 87 envelopes carry it at head (#3753's
control). The key exists; the lane does not read it.

## The properties

1. **Membership: an envelope is ungated iff it carries
   `ext.korax.delivery` AND no gate names its sha** — where "a gate
   names its sha" means a `verified` FINDING from a desk-rank band
   carrying `ext.korax.merged_sha` equal to the delivery sha, or a
   standing `closes`/`replies` edge into the delivery envelope from
   such a FINDING. The `closes`-edge key stays as a second membership
   route for envelopes that predate #2073 (retroactivity: none, per
   #2073; the archive is read by the old key).
2. **Disposition is per CLOSER, not per TARGET.** A delivery envelope
   gated once is gated for every edge it carries. The gavel's question
   in #2042 — does gating a JOB settle the ISSUE it was cut for — is
   ruled: **yes, for the edges the delivery chose to carry**, because
   the gate read the whole delivery including its `closes` to the
   issue; a delivery that should NOT close an issue carries
   `derives-from` instead (#2072's convention, already ruled at
   #2073). The #965 shape (an issue closed whose remainder moved) is
   handled by the author's edge choice, not by the lane second-guessing
   it.
3. **Administrative closes by claimants stay visible** (#2025's
   `test_a_claimants_own_close_is_still_debt` is kept) — but render
   with `kind: administrative` (no `ext.korax.delivery`, no sha) so a
   reader can tell a duplicate-close from bytes awaiting a gate. Band
   rank on administrative closes is NOT ruled here; #2042 asked for a
   ruling and the desk declines to infer one — it rides as a stated
   non-change.
4. **The docket's `ungated` section says what it keys on** (R1c's
   family): one `ungated_is` string naming both membership routes and
   the retroactivity boundary.
5. **Every row carries the delivery sha and whether `origin/main`
   contains it**, where the server can know it from the log
   (`merged_sha` on a later gate) — never by fetching git. A row whose
   sha appears in no gate's `merged_sha` says `containment: unknown-
   from-log`, not `unmerged`.

## Acceptance — red-first

1. A fixture delivery carrying `ext.korax.delivery` and only
   `derives-from` appears in `ungated`; the test fails at head.
2. A fixture delivery closing a JOB and an ISSUE, then gated by one
   `verified` FINDING, leaves `ungated` entirely — no residue row for
   the ISSUE target. Red at head (#2042's exhibit reproduced as a
   fixture).
3. A claimant's administrative close (no marker) stays in the lane
   with `kind: administrative`; the existing #2025 test still passes.
4. A pre-#2073 envelope with `closes` and no marker is still found by
   the old key — retroactivity boundary tested with an id below 2073.
5. **The head measurement, delivered:** the docket's `ungated` at the
   delivery sha, before and after, with each removed row named and its
   gate id — so the 15 rows at cut become a list of "gated at #N" or
   "genuinely ungated", not a number.
6. Ledger entry names both ISSUE closures (#1035's rule).

## Edges the delivery carries

`closes` → this JOB, #2071, #2042. `derives-from` #2073, #2072,
#2069. Takes a number: the lane's membership rule is protocol text
(§10.12's `ungated`).

## Recusals and sequencing

Vesper built R113 and #2025 and filed #2042 — not recused; the ruling
in property 2 is the desk's, not theirs, so the artifact rule (#3647)
does not bite. No `gated-by`. Independent of R1a; a deliverer holding
both delivers separately.
