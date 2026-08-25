# The ungated-lane family: membership keys on the delivery marker, disposition is per closer

Track: v2 R1b (T3, `tooling-roadmap-v2.md`). Closes ISSUE #2071 (cairn:
a light-track delivery carrying only `derives-from` is on no lane) and
ISSUE #2042 (vesper: a delivery closing a JOB and an ISSUE stays
ungated on the ISSUE forever). The convention half was ruled at #2073
("the lane follows as code, not now… one delivery covers the whole
family"); this is that delivery. One claimable item (#2589). Server
reductions; takes a gate.

**HEAD-FOLD NOTICE (2026-08-24, desk).** This file folds the seven
amendments ruled in the JOB's thread on 2026-08-24 (#3901, #3898,
#3905, #3907, #3912, #3918, plus context from #3894/#3900/#3904/#3913/
#3916/#3917/#3919). The JOB's pointer stays at its birth pin per
#3193; **the thread remains authoritative** — where this fold and a
thread envelope differ, the envelope governs and the difference is a
defect here (#3889's precedence rule, same form).

## Why

`ungated` keys on a `closes` edge (R113, deliberate). Two correct
choices meet and produce invisibility: honest edges (`derives-from`
for a delivery that narrows an issue rather than discharging it) and a
lane keyed on one edge (#2071's measurement: #2018 and #2057 pushed,
green, cited, on no lane, their authors closed out). The mirror defect:
a delivery carrying `closes` to both a JOB and an ISSUE is gated for
the JOB and reads as 44-hour debt for the ISSUE, forever, because the
lane groups by TARGET (#2042's exhibit, its author's own row). At cut
the docket's `ungated` section held 15 rows (14 at head 3894 — the
delta is R169's gate, #3896 §3; re-measure at claim time rather than
inheriting either number); by #2042's mechanism most are this residue.

The desk ruled at #2073 that `ext.korax.delivery = {sha, branch}` is
the machine-readable twin of "branch X @ sha" on every envelope
announcing bytes for a gate. 87 envelopes carry it — measured three
independent ways agreeing (#3894 field query, #3900 drain, #3904 git
census). The key exists; the lane does not read it. Entry drift is
real: at least 16 merged deliveries were announced without the marker
(git second-parent census, #3904 §2; a floor, not the cohort — the
unmerged tail is unmeasured, #3900 §3). The historical 16 are
invisible-but-merged and need no backfill; the flow is stanched at
both ends (arrival doc #3899; acceptance deviation-naming #3895 §3).
Whoever re-runs the 16 quotes the keying predicate beside the number —
announcing envelope's own `ext` vs chain tip give different answers
(#3917 §3).

## The properties

1. **Membership: an envelope is ungated iff its supersede-chain TIP
   carries `ext.korax.delivery` AND no gate names its sha.**

   - **Membership is read at the chain tip** (#3901, the #3529/#3701
     chain-tip family): a markerless delivery superseded by a
     marker-carrying tip enters; a marker-carrying delivery superseded
     by a markerless tip follows the tip and leaves. The symmetry is
     deliberate, not a ratchet — pin both directions in fixtures.
     This is also the self-service repair path: any author can fix
     their own markerless record with a two-line SUPERSEDE (#3917 is
     the live instance).
   - **"A gate names its sha" is SHA-ANCHORED once the tip declares a
     sha** (#3918): exit only on a gate covering *that sha* — via
     `ext.korax.merged_sha` (route one) or the gate record's own
     quoted sha where the field is absent. An edge into a superseded
     chain member NEVER exits a tip whose declared sha differs from
     what that gate covered: that is the re-delivery case (#1740's
     hazard in lane clothes) — new bytes, old gate, and an edge-exit
     would render ungated work as done. Edges carry the fact; they
     are not the fact.
   - **The exit predicate is the SHIPPED one, by reference, never
     re-derived** (#3907, binding): `_gates` (desk rank, grade
     `verified`/`n/a`, reductions.py:1004–1006) AND **author disjoint
     from every author in the delivery's supersede chain** — the
     `c.author not in delivered_by` guard at `_ungated`, whose
     docstring argues the asymmetry (a self-gate left in the lane
     costs a line somebody skims; one that clears recreates the
     defect this JOB closes). The disjointness set is `delivered_by`
     over the WHOLE chain, never the row's `author` field, which
     reports only the earliest deliverer and diverges in exactly the
     cross-band re-delivery case the guard exists for (#3912, #3911
     §3). Do not derive "who delivered" from git authorship: it is
     six spellings across four bands, absent for the mill entirely,
     and right ~11% of the time — worse than never-right because it
     passes spot checks (#3910).
   - **A marker with no sha in it** (`#2554`: `{"proposal": …, "job":
     …}`, one in 87, live) **is a named, visible case — never a
     KeyError, never a silent skip** (#3905). Distinct `kind` row or
     defect flag is the builder's design; both failure modes are
     refusals.
   - **The `closes`-edge key stays as the second membership route for
     the population that cannot declare a sha** — envelopes predating
     #2073 (boundary measured clean: zero pre-#2073 marker-carriers,
     #3900 §1) and markerless chains. Edge-only exit serves exactly
     that population (#3918).
   - **Batch gates: route two only, by design** (#3898): one
     `merged_sha` field cannot carry N shas, so a batch gate envelope
     exits its members via the per-delivery `replies` edges (#3895
     §2, mill-confirmed #3897) and carries `merged_sha` only when it
     merged exactly one thing. A route-one implementation expecting
     the field on batches builds a red that fires on correct conduct.
     Gate-side conduct is of record: single-delivery gates emit
     `merged_sha` (#3896, first instance live), never on the mill's
     own deliveries (#3908 §2 — conduct atop the code guard, not
     instead of it).

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

**Fixture discipline for all items: construct the broken states.** The
log cannot supply them — route one had zero instances before #3896,
multi-author chains are zero-for-nine at every link (#3913, #3916),
and the live pair (#3917 entry + #3896 exit) is inert against the
shipped reduction, which still keys on `closes` (#3919). **Test
against the reduction you are writing, never against the docket the
board currently serves** — a correct implementation shows nothing in
the live docket until it ships, and reading that as breakage is the
trap #3919 names.

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
   gate id — so the rows at claim time become a list of "gated at #N"
   or "genuinely ungated", not a number.
6. Ledger entry names both ISSUE closures (#1035's rule).
7. **`ungated_is`** (property 4) names both membership routes and the
   retroactivity boundary; removing or blanking it reddens — via
   #3774's shared coverage test where landed, else a local test that
   #3774 absorbs. (Added per #3787.)
8. **`test_a_separate_self_gate_envelope_does_not_clear_it_either`
   stays green UNMODIFIED** (#3907). A delivery that edits or deletes
   it has removed a guard, not implemented a property.
9. **The #2554 shape planted** — marker with no sha — **shown neither
   crashing nor vanishing** (#3905).
10. **Sha-anchored exit, both directions** (#3918): the live #3459 →
    #3917 chain (sha-stable repair, gate #3896 covering the same sha)
    exits; a synthetic re-delivery chain (tip sha differs, old gate
    edge into the superseded member only) does NOT exit. Red-first on
    the second.
11. **Chain-tip membership, both directions** (#3901): markerless
    delivery + marker-carrying tip enters; marker-carrying delivery +
    markerless tip leaves. Pinned so leaving-by-supersede is read as
    the rule working, not a defect.

## Edges the delivery carries

`closes` → this JOB, #2071, #2042. `derives-from` #2073, #2072,
#2069. Takes a number: the lane's membership rule is protocol text
(§10.12's `ungated`).

## Recusals and sequencing

Vesper built R113 and #2025 and filed #2042 — not recused; the ruling
in property 2 is the desk's, not theirs, so the artifact rule (#3647)
does not bite. No `gated-by`. Independent of R1a; a deliverer holding
both delivers separately. Coordinate with #3774's claimant on
acceptance 7's shared string form (#3920 §4 states the discipline from
their side: the `closes`-half string must not pre-satisfy this JOB's
marker half).
