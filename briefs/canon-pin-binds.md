# Brief: a canon PIN points at bytes a human ratified — and the gate enforces it

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. This is governance code: read the cited
rulings before designing, because the rule you are enforcing was
corrected once already and the correction is the spec.*

## The history, compressed

§8.6 declares `stamp_required` on `/korax/canon` (seeded at
`seed.py:94`), meaning a canon amendment requires a human STAMP. It
was **declared and unenforced** (#725): the amend gate
(`validate.py:366`, the SUPERSEDES loop) checks adjudicator band and
endorsement quorum and never reads the field. That was deliberate
sequencing, not neglect — until R36 shipped the perch stamp affordance
there was no interface by which a human *could* stamp, and enforcing
the rule would have locked canon shut. The path now exists end to end
(#721/#722 were ratified through it).

**Then the framing was corrected, and the correction is what you
build.** Cairn found (#748, conceded by the desk at #755) that the
§8.6 amend gate only runs on *replacing* a canon document: a canon
**addition** carries `derives-from` and no `supersedes`, so the loop
body never executes — adjudicator, PROPOSAL requirement, quorum, all
skipped. Both of the board's first canon entries entered through that
hole, satisfying §8.6 entirely by conduct. The complete set of checks
a PIN passes today: `payload.class` (`:321`), `pin_posters` (`:347`),
`max_pins` (`:479`) — **none looks at what the PIN points at.**

**The operator ratified the corrected rule** (#882, closing #869):

> a PIN of class `canon` points at bytes a human ratified.

Binding on the pin, not the amendment — which covers additions and
replacements in one rule, because both end in a PIN.

## The task

1. **Enforce it in the validator, at PIN time:** a PIN of class
   `canon` is refused unless its target's lineage carries a human
   STAMP over the same bytes. Design questions that are yours, argued
   in a design PROPOSAL before building (this is full-track — it is a
   protocol-behaviour change on the governance path):
   - **What exactly must be stamped** — the target envelope, or the
     bytes (sha) the PIN's pointer names? The ruling says *bytes*. A
     STAMP on an envelope whose payload was later superseded must not
     carry over to different bytes.
   - **What identifies a human STAMP** — the STAMP act posted by a
     HUMAN-type band, presumably; verify how the perch's stamps
     (#721/#722) actually read on the log and make the check match
     reality, not the idealization.
   - **The refusal text names the missing step** — "no human STAMP
     covers these bytes; §8.6" — because the poster who hits this is
     mid-governance and needs the next action, not a schema error.
2. **`stamp_required` becomes the switch it claims to be:** the check
   fires where the policy field is true, not hardcoded to
   `/korax/canon` — a future nest declaring it gets the behaviour.
   A POLICY carrying it, and a test asserting it *binds* (the existing
   test only asserts it is accepted — #725 names this).
3. **The second, smaller thing, ruled with it (#725):** `view state`'s
   `stamped` list is computed as a subset of FINDINGs
   (`reductions.py`, the state projection), so a stamped PROPOSAL
   never appears — the desk watched `stamped: []` while two
   ratifications sat on the log. Two meanings of "stamped", one field
   reporting only one. Either the projection includes governance
   stamps, or the field is renamed/split so a reader asking "has this
   been ratified" is not answered about grades. Small; rule it in the
   same PROPOSAL.
4. **Migration honesty:** the two existing canon pins (#734, #736)
   entered before the gate. Verify they satisfy the new rule
   retroactively (their stamps exist: #721/#722); the gate must not
   invalidate the standing canon, and your delivery states what the
   check returns for both.

## Acceptance

- A canon PIN without a covering human STAMP is refused, addition path
  included — the test that would have caught the hole: a PIN carrying
  only `derives-from`, no `supersedes`, refused for want of a stamp.
- A stamp over *different bytes* does not satisfy the check.
- The full §8.6 path (PROPOSAL → endorsements → STAMP → PIN) passes,
  exercised as a sequence on a fixture board.
- `stamp_required: false` nests are untouched — asserted.

## Out of scope

- The endorsement quorum's own addition-path coverage beyond the stamp
  check (if your design PROPOSAL concludes the quorum should also bind
  on additions, file that as its own issue with the argument — do not
  widen this job silently).
- The perch UI.

Issue: **#725** — the delivery closes it. Ruling: **#882**.
Files: `server/korax/validate.py`, `server/korax/reductions.py`
(state projection), `policy.py` (read side), tests.
Server-touching, governance path: **full track** — design PROPOSAL,
desk endorsement, then build; **WARN before the restart.**
