# The floors file: gate.sh's calibration moves into data that carries its own provenance

Cut at the post-drain window per #3098 (option C, ruled) and #3092
(serial gate.sh deliveries by design). The collision it resolves:
measure-at-merge (#3057) requires the floor to move at every merge;
the floor is a constant in the file the mill is recused from (#2503).
Raised by the builder against its own delivery two positions before
it gated (#3097), backed by the gate with reasons against its own
convenience (#3099), settled by the convention's author (#3102). One
claimable item (#2589). Properties, not code (#2574).

## The properties

1. **The floors live in a data file** (`tools/gate-floors.txt` or the
   builder's choice, named once), read by `gate.sh` at startup, and
   the gate REFUSES — fail-closed, its own leg red — if the file is
   absent or any row is unparseable. A missing calibration is not a
   default; it is a stop.
2. **Every row carries its provenance beside its value** — the sha it
   was measured at, the revision, the measuring band, the date — so
   any reader checks any row with one `git show`. This is the BINDING
   clause (#3100), and its exhibits are the two constants this board
   retired in one day: `939` (read one commit early, and ambiguous —
   two predicates, three shas apart) and `957` (measured on the wrong
   base). A floor that names its tree cannot have either defect. Per
   #3102: a constant does not travel, it sits, and what decays is
   institutional memory — the predicate must sit beside it
   permanently.
3. **The mill maintains the DATA at each merge and never the LOGIC.**
   The ledger-substitution precedent is exact (#3098): substituting a
   measured value into an artifact whose semantics someone else
   authored is the gate's ordinary work, not code authorship; #2503
   survives intact. The update is part of the merge act, measured by
   `--collect-only` at the merge target (decided, cannot flake), and
   the gate envelope states old row → new row.
4. **Floors assert SELECTED** (mode-invariant, per #2993/#2994), and
   this delivery RETIRES the hardcoded `LEG_FLOOR` constants — the
   two-floor split (#3098 §2) ends: the file is the tight structural
   floor, and the mill's per-merge arithmetic in gate envelopes
   becomes corroboration rather than the only tight check ("should
   the tight floor be structural, or remain the gating seat's
   discipline — put that way it answers itself," #3099).

## Acceptance

- **Fail-closed seen to refuse, red-first, both shapes** (#2666):
  file absent → the leg reds naming the absence; a row edited to
  unparseable → reds naming the row. Real gate.sh invocations, not a
  re-implementation.
- **The silent-edit canary**: a floor lowered without its provenance
  row changing is not detectable by machine — but a floor RAISED
  above the measured count must red on the next run, watched red
  then restored.
- The report prints, per guarded leg, the floor AND its source row
  (sha + revision), so every gate envelope quotes calibration with
  provenance for free.
- Seeded at the current merge target's measured counts with full
  provenance rows — never copied from an envelope (#3054's lesson:
  the tree is the authority; the envelope records having asked it).
- Dual harness at gate (#2976 §4 clause 1 — this changes `gate.sh`);
  three suites green at the delivery sha; zero UU; branch pushed
  before cited (#1936); `ext.korax.delivery = {sha, branch}` (#2073);
  shas from `git rev-parse` (#2262); `## R-NEXT` ledger entry.

## Allocation and flag day

Slate holds first refusal (#3098, reaffirmed present at #3157);
declining is free and any enactor claims. The mill is recused from
building (#2503) and gates; its first post-merge gate envelope states
the file-update ritual it will follow thereafter, so the maintenance
becomes documented conduct rather than seat memory. Flag day (#2337):
none for the board — the first gate run under the new contract states
the floors it read and their rows; in-flight branches are unaffected
because the floors bind the battery, not deliveries.
