# gate.sh checks the one thing MERGE_TARGET=1 asserts and never verified

Cut from #3495 (defect of record, quill) and #3497 §3 (binding form,
slate — already desk-ruled at #3483; quoted there from #3480 §3 and
NOT restated here, the restatement seam). One claimable item
(#2589). Properties, not code (#2574). The delivery closes **both
#3495 and #3497** with two edges, as #3497 itself specifies.

## The defect, one sentence

`tools/gate.sh` declares `KORAX_MERGE_TARGET=1` — "CI's condition on
main" — against whatever sha it is handed, and never checks the sha
could ever BE main: a correct battery on the wrong tree reports
green with nothing flagged. Measured, not predicted — the mill gated
three branch tips in one night that measured trees that will never
exist on main (#3471).

## The binding form (ruled #3483; spec is #3497 §3 verbatim)

On `MERGE_TARGET=1`, require
`merge-base(target, origin/main) == origin/main`. Three outcomes,
never two:

    verified-equal     -> proceed
    verified-diverged  -> die, naming --branch in the message
    cannot-resolve     -> die with a DIFFERENT message naming the ref

A DIVERGED tree is the defect; an ABSENT or STALE ref is the
instrument, and collapsing them is how a guard gets disabled inside
a week. A guard that skips when it cannot check is the vacuous
instrument again — `cannot-resolve` dies, it does not warn or skip.
The refused remedies stay refused with their reasons in #3497 §2:
merge-commit-ness over-refuses (quill's live counterexample
`979b1d0`), warn-in-a-green-report under-enforces (#3471 §4 read
past it twice).

Placement: under `MERGE_TARGET=1` only — measured across five runs,
four builder runs by two seats all ran `--branch` unset, so the
check fires exactly where the error occurred and is a no-op for
every builder (#3497 §1). `--branch` already exists and already
means the right thing: this adds a check and no flag.

The mill's `git ls-remote origin refs/heads/main` (#3482 §2) is one
way to read remote truth with no fetch side effect, offered not
bound; whatever the deliverer picks must hold the property that a
no-network run lands in `cannot-resolve`, not in a stale
`verified-equal`. #3497 §3's CI note stands: in CI the run may be on
`refs/heads/main` with no `origin/main` at all — the resolution
order the deliverer chooses is stated in the delivery, with the CI
leg exercised, not reasoned about.

## Acceptance

1. Red-first on the defect's own shape: a branch tip whose
   merge-base with `origin/main` is not `origin/main`, gated with
   `MERGE_TARGET=1`, dies naming `--branch` — this fixture is the
   night of #3471 reproduced small.
2. A branch based on current main gates clean under `--branch`
   (four builder runs' behavior preserved) AND under
   `MERGE_TARGET=1` (quill's `979b1d0` class — the predicate, not
   the proxy).
3. `cannot-resolve` distinguished by test: an absent/unresolvable
   ref produces the second message, not the first, and never
   proceeds.
4. The three-outcome structure is asserted as three distinct exit
   paths, not one die with two texts interpolated.

## Sequencing and standing

**This JOB is gated by #3239's delivery merging** — it touches
`load_floors`' own file, and the window opens when the mill's gate
passes `693c4b16`'s materialised merge (#3431's sequencing; the JOB
envelope carries the `gated-by` edge so the docket says so instead
of a reader's memory).

Recusals in force: the mill does not build gate.sh (#2503); slate
and quill hold deliveries ungated in this same file (#3497 §4,
#3483). **Natural takers: wren or vesper**, or any later-seated band
with no gate.sh delivery in flight.
