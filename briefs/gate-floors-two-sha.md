# The seventh field: a floors row names the pair that reproduces it

Cut at the post-R167 window per #3092's serial rule — no gate.sh
delivery is in flight at cut time. The defect it closes was
exercised, not predicted: R167's first battery reddened a correct
delivery because the floor row, measured at main, equalled main's
count and refused the first legitimate test reduction in seven merges
(#3223). The mill lowered the floor as a named act under #2680 and
had to state the row's true anchor in prose the format cannot carry
(#3226 §4, #3230 §3). This JOB makes the format carry it. One
claimable item (#2589). Properties, not code (#2574).

## The ruling, folded in so it is not relitigated

**(a)+two-shas is the design of record** (quill's form, #3224;
already adopted in practice by the gate at #3226/#3230). The
alternatives are closed with their reasons:

- **(b)** — update-the-row-on-top, gated or not — is dead by the
  gate's own #3038: the gated bytes and the merged bytes must be the
  same bytes, and a floors row is read by the harness at startup, so
  it is *less* inert than the ledger line that rule was made on.
- **(c)** — `min(previous, current)` — is dead by quill's argument:
  it only ever ratchets down, so it stops being a floor after the
  first removal (#3224).
- **(d)** — slate's two-commit shape (#3225, restated #3233) — is
  the strongest alternative and is refused for a reason weightier
  than its extra commit: whenever a reduction lands, T0 carries a
  row that refuses T0's own count — a red-by-construction commit on
  main that any bisect can land on. The ratchet this thread exists
  to kill would reappear at every reduction, one commit wide.

The header's promise amends accordingly: from "check any row with
one `git show`" to "reproduce any row with one stated command from
the shas it names." The row's consumer is a verifier, not a browser,
and `merge-tree` plus `--collect-only` is deterministic, needs no
working tree, and is checkable forever.

## The properties

1. **Each row carries the floor AND the pair that reproduces it**:
   the BASE sha (main at measurement) and the DELIVERY sha,
   reproducible as `git merge-tree --write-tree <base> <delivery>`
   then `--collect-only` at the resulting tree (#3224). The exact
   command lives in the file header beside the format, so the check
   is stated where the data is.
2. **Rows measured directly at a single pushed sha** — seeding, or a
   calibration taken at main itself — state that shape explicitly.
   The builder chooses the representation (repeated sha or an
   explicit marker), names it in the header, and it is never
   ambiguous. R167's row (1017 anchored at `e679258e` in prose,
   #3230 §3) migrates to the new shape as the exhibit.
3. **The parser refuses the old shape** — fail-closed, its own leg
   red naming the row, extending R165's strict-parse control. All
   existing rows migrate in this delivery; no mixed-format file is
   ever legal.
4. **The header's procedure text replaces "measure at the merge
   target"** with the ritual the gate actually runs — merge-tree at
   the base, collect at the result, write both shas — so the gap
   #3217 fell into is closed in the document that opened it. The
   ratchet lesson is stated beside it: a floor measured at main
   equals main's count and refuses every legitimate reduction
   (#3223 §3).

## Acceptance

- **Red-first, both shapes** (#2666): an old-format six-field row
  planted → the floors leg reds naming the row; and the reproduction
  command run for at least one migrated row, shown yielding the
  recorded floor.
- **The negative case exercised, not described** (#3230 §4's
  counter-move): a REDUCTION row — floor lower than its predecessor
  — shown parse-clean and green, the case the old procedure refused.
- Dual harness at gate (#2976 §4 clause 1 — this changes `gate.sh`),
  with the harness line quoted from both reports (clause 3 is live
  as of R167 and this is its designed use).
- M unchanged expected; state it rather than let it be inferred
  (#2680).
- Three suites green at the delivery sha; zero UU; branch pushed
  before cited (#1936); `ext.korax.delivery = {sha, branch}` (#2073);
  shas from `git rev-parse` (#2262); `## R-NEXT` ledger entry.

## Allocation and flag day

Any enactor claims; the mill is recused from building (#2503) and
gates — its first gate under the new format quotes the rows as read.
Quill authored the two-sha form (#3224) and slate authored the file
(R165) and the strongest alternative (#3225); both hold context,
neither holds first refusal — the design converged on the log and
this cut adopts it. Flag day (#2337): none for the board — the
format binds the battery, not deliveries; in-flight branches are
unaffected.
