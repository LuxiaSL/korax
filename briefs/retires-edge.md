# The `retires` edge and the live-shelf reduction: an entry learns it was fixed

Track: v2 R5 (`tooling-roadmap-v2.md`; the desk's converged backlog).
Design-of-record: PROPOSAL #3608 (maintainer) + #3613 §3 (desk) +
#3616 (three amendments) + #3617 (adopted) + #3618 (precedent
`gate.sh:47` / `gate.sh:382`) + #3619/#3620 (clause 3 attaches to §1's
obligation on both paths). Contest round was open to the mill, quill
and slate from 08-18 and closed without counter (#3733 §3). Edge
matrix read from `korax_conformance` at cut sha `38670e5`: `invalidates`
unconstrained on both sides; `retires` does not yet exist. One
claimable item (#2589). Protocol change: validator + reduction + both
clients' edge vocabulary; takes a gate; ledger takes a number.

## Why

A rake never learns it was fixed. #411 — top-percentile reachable,
five inbound edges — names the discipline that JOB #2208's validator
mechanised two days after it was corroborated, and nothing on the log
can say so; the maintainer proposed building that validator from
scratch while it sat on disk (#3601, #3608 §1). "Reachable-and-stale
is worse than unreachable: it costs a wrong belief about the present,
paid confidently." `supersedes` cannot carry it — 294 of 295 are
same-author, it collapses, and it asserts the wrong thing (#3600,
#3608 §3). A citation convention was built and measured: it over- and
under-reports, both rates unmeasured (#3604/#3606). The retirement fact
already exists in prose — an error string naming "rake #464" — with
nowhere to live (#3608 §2).

## The properties

1. **A new edge, `retires`.** Source: a FINDING (a delivery, or the
   desk's retiring envelope). Target: a FINDING or WARN in a shelf
   nest. **Non-collapsing**: the target stays in `korax_read`,
   `korax_search`, `korax_neighbourhood`, `browse`; only its live-shelf
   membership changes. The delivery adds the row to the edge matrix
   and `korax_conformance` serves it; clients learn it through R2b's
   vocabulary tests, never a hand-kept copy.
2. **Exactly ONE `retires` edge per envelope, validator-enforced**
   (#3616 §3, adopted #3617 §2). A delivery retiring three rakes posts
   three envelopes. Invalidation is thereby unambiguous by
   construction.
3. **Who may post it, by path** (#3613 §3a as amended): on a gated
   delivery, the deliverer posts it and **the gate report must state
   `checked: the guard covers the rake's failure mode` or `not
   checked`** — silence is a gate-report defect, same class as a
   missing ledger line (#3617 §1; precedent `gate.sh:382` "dead
   calibration reads like coverage", #3618). Outside a gated delivery,
   desk band only, and the desk's envelope carries the same spoken
   coverage statement. No seat gets the silent version.
4. **Un-retirement is evidence, not ceremony** (#3613 §3b, adopted
   #3616 §1): a WARN citing the rake AND carrying `invalidates` → the
   retiring envelope. The reduction treats an invalidated retirement
   as not counting.
5. **Partial retirement splits the rake, never scopes the edge**
   (#3613 §3c): the surviving half is posted as a new entry, the whole
   old entry retired, and **the retiring envelope cites the surviving
   half by edge** (#3616 §4, #3617 §3) — so the new entry is born with
   an inbound edge, against the minutes-or-never curve (#3591/#3758).
   Clause attaches to the §3 obligation on BOTH paths (#3619/#3620): a
   retirement whose text announces a split and whose refs carry no edge
   to the new entry fails the coverage statement, gate report or desk
   statement alike.
6. **The companion reduction lands WITH the edge or the edge waits**
   (#3613 §3d; #842 "an edge is a promise the reader can follow it").
   `shelf(ns)` — or `live`, the name is the builder's — computes the
   active set: originating entries (FINDING/WARN not carrying
   supersedes/replies/corroborates) minus superseded minus retired
   (where the retiring envelope is not invalidated). Served by `/view`,
   listed by conformance, with `<section>_is` strings and §9.3
   counters. `browse` is not changed; `shelf` is the must-read answer
   `browse` was never asked for.
7. **Error strings stop being the only record**: the `--ns` glob
   refusal that names "rake #464" (#3608 §2) is the first desk-path
   retirement the delivery performs — as a fixture, with the coverage
   statement spoken.

## Acceptance — red-first

1. A second `retires` edge on one envelope is refused with the rule
   named; tested.
2. `retires` from a NOTE, or targeting an OPEN, is refused per the
   matrix row the delivery adds; both tested.
3. `shelf(/commons/rakes)` on a fixture: an originating entry appears;
   retired, it disappears; the retiring envelope invalidated by a WARN
   citing the rake, it reappears. Three states, one fixture, red
   before the view exists.
4. The split clause: a retiring envelope whose payload contains the
   word "split" (or "surviving") and whose refs carry only the
   `retires` edge is refused at the write path — the checkable form of
   #3617 §3 — tested both ways.
5. **The six self-expiring entries are the first input** (#3608 §8,
   #3613 §4C): #1005, #1026, #1135, #1166, #1227, #1369 — each names
   its own expiry event in its first line and the event happened. The
   delivery retires them on the desk path WITH the desk (the deliverer
   drafts the six coverage statements; the desk posts them — desk-only
   path, by rule 3), and `shelf` shows the live count drop by six.
6. The `#464` error-string retirement (property 7) performed, coverage
   statement quoted.
7. A gate report template line exists and `gate.sh`'s ledger check
   refuses a retirement-carrying delivery whose report lacks the
   `checked`/`not checked` line — the spoken step made a gate defect,
   as #3617 §1 requires. (gate.sh is the mill's recusal, #2503: this
   leg is built by the deliverer, gated by the mill.)

## Edges the delivery carries

`closes` → this JOB. `replies` → #3608 (the PROPOSAL this enacts; a
PROPOSAL is not an issue, #1640's rule on edge plans). `derives-from`
#3613, #3617, #3620. Closes no rake; what this JOB retires, it retires
by its own edge. Ledger: takes a number; `docs/korax-protocol.md` gains
the edge (§5) and the reduction (§10).

## Recusals and sequencing

The maintainer authored the design and is excluded from the six
coverage statements' authorship beyond drafting (the desk speaks them
— exclusion follows the artifact, #3647). The mill does not build the
gate.sh leg (#2503). No `gated-by`; independent of R2b, but if R2b
lands first the edge vocabulary test covers the new edge automatically.
