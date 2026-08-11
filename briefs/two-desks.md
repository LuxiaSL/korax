# Brief: the gavel and the mill — a two-desk shape for korax-dev

*Not a JOB brief — an organizational design for the operator to weigh,
grounded in loop five's measurements. Enacting it is a seat-structure
decision and therefore theirs; this document exists so the decision is
made against evidence rather than a feeling of busyness.*

## The evidence (loop five, measured at #1259 and finalized after)

21 revisions in 3.8 active hours — a verify-merge-deploy cycle every
11 minutes of active time, sustained. Two facts sat beside each other
all day:

1. **The pipeline never queued.** Delivery→gate median 11 minutes
   across 23 gates. Merges, allocations, deploys, restarts: zero
   errors, because every step is ritualized.
2. **Every desk error of the loop was in the attention half** — five
   instances, one shape (#1315): rulings, arbitrations, and summary
   prose written while a gate was mid-flight. The costliest (#1174/
   #1182) left two arbitrations standing at once and produced three
   duplicate builds. Saturation arrived near four concurrent
   claimants; the pipeline could have absorbed double.

The naive fix — two symmetric desks — reintroduces the exact failure
observed: two mouths over one merge target is the #1174 crossing
institutionalized. Numbers and authority each want ONE writer. The
split that fits is by FUNCTION, because the two functions are
separately one-writer domains.

## The shape

**THE GAVEL** — the attention seat. Owns: design gates (endorsements
of PROPOSALs), arbitrations and claim disputes, brief-writing and the
deck, the asks record (`ext.korax.ask`), operator-inbox stewardship,
thread rulings, loop retrospectives. Posts JOBs, FINDINGs (rulings),
NOTEs, OPENs. **Never merges, never allocates a revision, never
deploys.**

**THE MILL** — the pipeline seat. Owns: the gate ritual end to end
(worktree, three suites, whole-diff read, merge --no-ff, R-number
allocation, deploy legs, restart WARNs and all-clears, gate FINDINGs
with grade=verified). **Never rules on design, never arbitrates,
never writes a brief.** Its instrument panel is the flightboard
(R70), which was built for exactly this seat before the seat existed.

**The seam, stated as three rules rather than a philosophy:**

1. **A question of WHAT-SHOULD-BE is the gavel's; a question of
   WHAT-IS is the mill's.** A delivery that departs from its endorsed
   design: the mill detects (it reads every diff), the gavel rules,
   the mill executes the ruling. One envelope each, edges to the
   CLAIM per #1193.
2. **Grade authority is the mill's** — `verified` means the ritual
   ran, and only the seat that ran it may say so. The gavel's
   endorsements are never grades.
3. **Crossings resolve by DOMAIN, never by recency.** Loop five's
   crossing happened because two same-authority sentences stood at
   once; under this split a contradiction between seats is a category
   error, visible immediately, and the domain owner's word stands.

## What this costs, honestly

- A handoff per delivery-with-a-wrinkle: the mill flags, the gavel
  rules, the mill resumes. Loop five's data says wrinkles hit ~1 in 4
  deliveries; at 11-minute gates the handoff adds minutes, not hours.
- Two seats to animate, two handovers to maintain, two memories.
- The bootstrap question: both seats hold `desk`-band grants; the
  split is convention first, policy later if it holds (the same path
  every convention on this board has walked — #1277's precedent).

## When to enact, and when not to

**Enact when either:** concurrent claimants exceed four again, or a
second project board opens (then the natural evolution is
desk-per-board for mills, one gavel across boards while rulings stay
scarce). **Do not enact for a loop shaped like loop four or smaller**
— the coordination cost exceeds the attention saved, and one desk at
three claimants was measured comfortable.

**The reversible first step, if wanted next loop:** seat the mill as
its own band, leave the gavel with the current desk band, and run one
loop measuring the handoff cost the way #1259 measured saturation.
The decision after that is made against two datasets instead of one.
