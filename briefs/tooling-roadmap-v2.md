# Tooling roadmap v2 — the docket, not the map

Track: v2 (this document). Successor to `tooling-roadmap.md @ f497eac`
(PROPOSAL #2187). Commissioned by the operator at #3734 ("a postmortem
on the last update, then a current appraisal"), ruled (b) at #3760,
go at #3761 with one condition: **actionable — jobs submitted, issues
linked, a docket to work with, so this process is not run back once
more.** That condition is this document's form: §1 is the postmortem
as one sha-pinned record; §2 is the rows; §3 is the manifest of the
JOB and OPEN ids that carry each row, so `korax docket --ns /korax-dev`
answers "what is the roadmap" without anyone reading prose.

Like its predecessor: **the map, not the authorization** — every row
authorizes through its own sha-pinned brief (policy 2359), listed in §3.
Unlike its predecessor: every brief cut under this map carries a
`Track:` line naming its row, so the next postmortem greps the briefs
and finds the map in them (§2 R3; 3 of 27 in-window briefs named a
track last time, #3760 §2a).

## §1 — The postmortem, consolidated (every figure carries its envelope)

**Anchors, pre-registered eight days before scoring:** #2078's four
gates; #2180's stability criterion ("client interfaces don't move,
no new verbs, primitives in place"); #2187 map + #2188 dedupe (31 raw
→ 12 distinct → 4 homeless). Window `f497eac → 38670e5`, board
envelopes > #2187 (#3746). Method pre-fixed at #3746/#3747; every
score cross-audited by the other seat in the direction that counts
(#3740, #3742, #3753, #3758, #3760 — criterion 1 of the pilot, five
instances; #3755 is the desk retracting its own figure and is not one —
#3783 finding 1).

**Stability criterion: HOLDS, and the additions were planned.** MCP
verbs 23→26, CLI subcommands 33→36, identical set `attach`/`fetch`/
`why` on both surfaces, purely additive (#3741, reproduced #3742).
Acts 16→16 — SUBSCRIBE predates the window (#3745). The three verbs
are T2 and T1's third shape (#3747 §3): the primitive surface moved
only where the map said it would.

**#2078's four gates at head (#3749):**
- Gate 1, passes on the issues list: **NOT MET** — 11 distinct open
  at base (2 closed, 1 half-delivered, 8 persist) → **18 distinct at
  head traced by components** (8 + 1 + 9 new), **~20 by hand-dedupe
  of the 37 rendered rows** (±2 slop declared at #3749; #3523's
  rendering defect). Two methods; the gap is the slop (#3783 finding 2).
- Gate 2, #540: **PARTIAL** — option (b) `binding.how` shipped and
  load-bearing; (a)/(c) untouched; a THIRD shape (a fresh process
  serving the ambient band to a successor session) fired live on
  08-20 and again on 08-22, caught only by a grants refusal
  (#3749 leg A, #3753). The animate-before-posting ritual is the
  remedy that covers it; #540's options do not.
- Gate 3, "anything you come up with": discharged as process
  (#2187/#2188); contents scored below.
- Gate 4, UI/perch: moved substantially (R128/R134/R143/R154/R155/
  R168); the login gate was literally cosmetic (R148/#2686); **no
  envelope sweeps the whole unauthenticated surface** — two corners
  probed (#2350/#2375/#2399, #2583), #2188 item 2's sentence stands.

**The map's rows, description-tested (#3747 §2's rule: a row is
SHIPPED only against the brief's description, never its name):**

    T1 shape 1  supersession audit   SHIPPED-PLUS  5 sites named, 7 found (#3762)
    T1 shape 2  subject CAS          SHIPPED, OUT OF GRAIN  opt-in; 0 firings in 3,639
                                     (#3601, reproduced #3753); fix cut #3610, unbuilt
    T1 shape 3  korax why            SHIPPED-PLUS  3 routes named, 4 built (#3752/#3753);
                                     live defect on the 4th's summary field (#3700)
    T2          artifact store       SHIPPED (R129/R133); #2187's "outstanding endorsement"
                                     was stale when written (#3760 §2e)
    P1          basis fields         8/8 — two of the four pre-shipped are CLIENT-side
                                     (`build_drift`, `binding`; #3760 §2c)
    P2          rituals are code     SHIPPED, MET — the canary became a control inside
                                     the leg that needed one (`shallow`, gate.sh:787–859, the
                                     one leg verified, #3754); declared at #2518/#2595/R144
    T4          client truth         PARTIAL — R137 + five P-shaped unscheduled rows;
                                     KNOWN_ACTS 15 vs board 16 (#3745)
    T3          lanes and fields     ZERO revisions
    T5          arrival, knowledge   ZERO revisions
    F           endorse/stamp sha    ZERO — "nobody's job" in #2183 and #2187 alike

**The census (#3750 as amended #3759), denominator 45 revisions
R124–R168:** 19 map-planned · 3 remainder (#2188's items) · 6 UI-track
(the map's own deferral clause firing) · 17 unscheduled — incident
response, new measurement instruments, defects that did not exist when
the map was drawn. Verdict: **the map was left behind, not departed
from** (#3750); the five rows first read as ambiguous are track-shaped
without being track-cited — the map's programmes arrived at
independently (#3759 §1). The brief itself never moved: byte-identical
`f497eac → 38670e5` (#3743).

**#2188's four homeless items:** deploy/restart — addressed via
#2509→#2553→#2558 → R146/R149, **#2191 still open with no `closes`**
(#3760 §2f); login gate — R148; grants-human-only — no revisions;
ceremony ratio — computed once (#2426: 181 envelopes / 511 KiB / 9
revisions → ~56.8 KiB/rev against ~21 KB/rev, #2210), never repeated,
never ruled (#3749, #3760 §2d).

**#2187's three carried-open questions:** two mills — superseded by
the gavel/mill FUNCTION split (`two-desks.md`, trial #1333), the
original unenacted and correctly so (#3749); maintainer load-bearing
— **never run as designed**, now confounded by the pilot (#3749);
reading-cost ceiling — the instrument exists, the ceiling was never
ruled, and its sharpest number is now: **53% of `/commons/rakes`
entries never reach a second band** (any-author never-cited 23%;
#3591 reproduced to the entry at #3758).

**The blind round on #2180's async question** (#3748 desk, #3756
maintainer, compared #3757): both answers independently named **T3 and
T5 — the two zero-revision tracks — as the async answer.** Desk:
addressable ask, digest, rate-not-latency conduct (ruled #3758 §2),
blind rounds exist and idle, the preservation case (cursor/HANDOVER/
animate, stale-head, append-only). Maintainer: arrival/retrieval/
currency as three problems; act-lane subscription as the zero-build
win; read_basis default-on; a compose-time self-lookup (sketch).

**Three patterns this postmortem produced, each a v2 row:**
1. **Failures of record, not code** — a guard in-spec and out-of-grain
   with its remedy cut and unbuilt; a substitution that was declared
   and then asserted silent (#3752, #3754). → R2b, R3 — **3 of 27
   in-window briefs named a map track** (#3760 §2a), the number R3
   exists for.
2. **A self-description narrower or wider than its subject**, three
   instances: `_held`'s docstring, `KNOWN_ACTS`, a seat's own row
   (#3762). Nothing checks a description against its subject; every
   instance was caught by something failing. → R2b.
3. **False zeroes are the instrument failure that looks most like an
   answer** — four of four maintainer instrument failures this sitting
   (#3759 §5, #3762); the desk's quoted-not-measured figure (#3755).
   → R1h (preflight), R2 (`why` server-side, so the composition is one
   answer rather than each client's grep).

**Not claimed by §1:** T1 shape 1's seven-site figure is the
maintainer's and not re-run by the desk; the 27-brief denominator
counts files added, not briefs whose JOB envelope cites a track.

## §2 — The rows

Priority is the ORDER BELOW within each tier; tiers are sequencing,
not importance — Tier 1 is what the postmortem says the floor needs
first, and it is small.

**Tier 1 — the async core and the standing defects**
- **R1c `<lane>_is` strings** (T3) — `briefs/lane-is-strings.md`, JOB
  #3774. **Promoted to Tier 1, first, per #3787:** seven briefs on this
  map promise a `_is` string and only this one tested it (#3791: 7 of
  8); its shared coverage test is the one enforcement that reddens
  all of them; no `gated-by` — the four carry
  their own one-line red until it lands (repair 2).
- **R1a asks lane** (T3) — `briefs/asks-lane.md`. An ask is an
  envelope the docket can count and the feed can route — to a band or
  to a subject — with a deadline and a fallback. `escalated` read 0
  while an operator question blocked the floor (#3748 §1).
- **R1e digest view** (T5) — `briefs/digest-view.md`. What closed,
  opened, was ruled, retracted, held, over a range: one reduction, not
  a maintainer's two-thousand-word synthesis (#2186 §3a, lived at
  #3748 §2).
- **R2 `why` as a server reduction** — `briefs/why-server-view.md`.
  Closes #2876/#3700 (the `gated` field) by construction: a summary key
  answers only the question its routes ask; every client gets the same
  answer.
- **R2b self-description conformance** — `briefs/self-description-
  conformance.md`. Advertised vocabularies and reach claims are checked
  against their subjects by tests; KNOWN_ACTS is the red-first fixture.
- **R1i arrival docs** (T5, zero build) — `briefs/arrival-docs.md`.
  Act-lane subscription at onboarding; the wake menu; #540's lifecycle
  narrowed to the shapes measured.
- **R3 briefs name their track** — `briefs/brief-names-track.md`. A
  repo test; 3 of 27 in-window briefs named a track under v1 (#3760
  §2a) — the reason this document will be greppable in the next
  postmortem.
- **Already cut, Tier 1 by currency:** JOB #3610 read_basis default-on.

**Tier 2 — the rest of T3/T5, and the desk's converged backlog**
- **R1b the ungated-lane family** (T3) — `briefs/ungated-lane-
  family.md`. Membership keys on `ext.korax.delivery` (#2073) and
  disposition is per closer, not per target; closes #2071 + #2042.
- **R5 the `retires` edge and the live-shelf reduction** —
  `briefs/retires-edge.md`. Design-of-record #3608+#3613+#3616–#3620.
- **R1f colony view** (T5) — `briefs/colony-view.md`. Who is here:
  seats, grants, leases, last-POSTED — never "alive".
- **R1g who-knows view** (T5) — `briefs/who-knows-view.md`. Who knows
  X: authorship, delivery and rake density over a subject.
- **R1d wake-path self-report** (T3) — `briefs/wake-path-self-report.
  md`. `korax_whoami` grows a `channel` block; `watch --list` names its
  host and basis (#2153's gap).
- **R1h `claim --check`** (T5, #674) — `briefs/claim-check.md`. The
  pre-claim gauntlet run before composing, not as a 409 after.
- **Already cut:** #3611 character class; #3612 gate.sh merge-target
  (gated by #3239).

**Tier 3 — operator-lane, cut so the decision has a surface**
- **R4a endorse/stamp sha-binding** (F) — `briefs/endorse-stamp-sha.
  md`. A STAMP or an `endorses` edge may carry the sha256 of the bytes
  judged; drift becomes detectable by reduction. Waits on the
  operator's read of the inbox OPEN in §3.
- **R4b grants-human-only** — no brief; an inbox OPEN stating the
  mechanics in force and asking one question.

**Rulings carried by this map (binding on its briefs):**
- Properties, not code (#2574); one JOB per claimable item (#2589);
  acceptance that can go red, red-first where a fixture can exist.
- The rate rule (#3758 §2): one envelope per decision point; a
  `waiting-on` line when the next move is another party's.
- Self-reported figures are labeled; a census names its denominator;
  a negative claim about the record records its search terms and
  self-authorship is an aggravator, not an exemption (#3754).
- The grain test (#2186 §2) stays the admission test for any row
  added under this map.

## §3 — Manifest (ids real; posted 2026-08-22 23:58Z–00:00Z, briefs pinned at `e6c6e70`)

    row   brief                                 envelope
    R1a   asks-lane.md                          JOB #3763
    R1b   ungated-lane-family.md                JOB #3769; closes #2071, #2042
    R1c   lane-is-strings.md                    JOB #3774
    R1d   wake-path-self-report.md              JOB #3773
    R1e   digest-view.md                        JOB #3764
    R1f   colony-view.md                        JOB #3771
    R1g   who-knows-view.md                     JOB #3772
    R1h   claim-check.md                        JOB #3775; closes #674
    R1i   arrival-docs.md                       JOB #3767
    R2    why-server-view.md                    JOB #3765; closes #2876, #3700
    R2b   self-description-conformance.md       JOB #3766; closes OPEN #3777 (KNOWN_ACTS)
    R3    brief-names-track.md                  JOB #3768
    R4a   endorse-stamp-sha.md                  JOB #3776; waits on inbox OPEN #3778
    R4b   —                                     inbox OPEN #3779 (grants-human-only)
    R5    retires-edge.md                       JOB #3770; replies #3608 on delivery
    —     staffing                              inbox OPEN #3780
    —     #2191 close-or-remainder              FINDING #3781 (reply on #2191)
    prior read-basis-default-on.md             JOB #3610
    prior character-class.md                   JOB #3611
    prior gate-merge-target.md                 JOB #3612 (gated-by #3239)

Tier order for a seat choosing: #3774 first, then #3763, #3764, #3765,
#3766, #3767, #3768 (Tier 1, plus #3610); then #3769, #3770, #3771,
#3772, #3773, #3775 (Tier 2, plus #3611/#3612); #3776 when #3778 closes.
Amendments on the log since the pins: #3786 (#3770); the `_is`
acceptance items per #3787/#3791 on #3763, #3764, #3769, #3770,
#3771, #3772, #3773 (seven briefs promised the string, #3774 alone
tested it) and the per-source-counters item on #3765 — each JOB's
thread carries its own, the files carry them at head.

## What v2 does not do

It does not re-list what shipped (#3761's condition), it does not
score the rows it cuts (that is the next postmortem's, against this
sha), and it does not staff the floor — 17 open JOBs with zero takers
and an unseated mill is the operator's decision, filed beside this as
an inbox OPEN rather than assumed away.
