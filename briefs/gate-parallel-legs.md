# gate.sh: concurrent legs, browser isolated

Track: throughput family (#3884; ruled #3887 §4). Standalone — not part of
the v2 manifest. Server tooling; takes a gate; changes `tools/gate.sh`
bytes, so its own gate runs **alone, dual-arm** (#3881's criterion, by
construction).

## Why

R170's battery: 558.95s serial, wall clock ≈ sum of legs, on a 16-core
host. `gate.sh:304` backgrounds each leg and immediately waits on its
pid — the `&` feeds the reaper, it overlaps nothing (#3884 §1, measured
from the battery's own report). The browser leg is 277.82s (49.7%); the
rest sum to ~281s, dominated by `suite-server` at 101.82s.

Batching (#3887 §1) cuts batteries per delivery; this cuts seconds per
battery. They compose and neither replaces the other.

**The 380s figure that motivated this JOB is an upper bound, not a
target** — arithmetic over measured leg times assuming perfect overlap
and zero contention among the non-browser legs (#3884 §5, the mill's own
caveat). The delivery's job includes finding out what the real number
is.

## Properties

1. **Legs run concurrently, EXCEPT the browser leg, which runs with no
   other leg in flight** — strictly before or strictly after the
   concurrent phase. Isolation is load-bearing, not an optimisation:
   the browser flake is core-sensitive as a *mechanism*, not a rate —
   probe-to-probe, 32 runs at 16 cores → 0 events; 24 runs at 2 cores
   → 1 event (#2930 §1, carried with its population caveat per #3886,
   adopted #3891). A concurrent phase running beside the browser leg
   manufactures the scarcity condition inside the battery that #3887
   §3 refuses to manufacture across batteries.
2. **Report semantics preserved.** Every leg named with its own status
   and duration; `legs ran / skipped / not reached` and `fail` counts
   computed as today. Composes with #3883's merge-target completeness
   properties: whichever delivery lands second rebases, and both
   red-first sets must pass on the composed tree.
3. **Failure isolation.** One leg's red neither truncates another
   leg's run nor drops its report row; the battery completes and
   aggregates, as the serial battery does today.
4. **The decided leg keeps its ordering guarantee.** The floors leg
   runs to completion before any guarded leg starts —
   `test_the_floors_leg_is_declared_and_runs_before_the_guarded_legs`
   stays green unmodified. Calibration precedes measurement under
   concurrency exactly as it does under serial.
5. **Serial escape hatch.** `KORAX_GATE_SERIAL=1` restores today's
   serial behaviour with an equivalent report — for debugging, and for
   hosts where concurrency is the wrong call. Cheap, and the control
   arm for acceptance item 1.

## Acceptance — red-first where the property can go red

1. **Measured wall clock, before and after, on the SAME tree, both
   reports quoted whole** (leg table plus total). The deliverable is
   the measured number, not the bound. **Pre-registered honesty
   clause: if the measured saving is under 15%, the delivery says so
   plainly and the desk re-prices the JOB rather than the delivery
   dressing the number** — a small true saving is a finding, not a
   failure.
2. **Browser isolation demonstrated from the report itself** — phase
   markers or per-leg start/end times showing zero overlap with the
   browser leg. Red-first: a deliberately overlapped configuration
   shown failing the check that enforces isolation.
3. **All 12 legs present and named; M unchanged at 12; per-leg counts
   identical to the serial battery on the same tree.** No coverage
   moves as a side effect of scheduling.
4. **Existing suite green at delivery** (`test_gate_sh.py` whole,
   including the floors-ordering test unmodified); new scheduling code
   carries its own refusal tests per cause.
5. **Composition with #3883** (strict merge-target), whichever order
   lands: its fixture behaviour intact on the composed tree — a
   skipped or unreached leg under `KORAX_MERGE_TARGET=1` still exits
   non-zero with the INCOMPLETE-leading report, concurrency
   notwithstanding.
6. **Serial escape hatch equivalence:** same leg set, same counts,
   same pass/fail verdicts as the concurrent run on the same tree.

## Recusals and sequencing

The mill is recused from building `gate.sh` (#2503) and gates this
delivery — which, changing harness bytes, runs **alone and dual-arm**
under #3881, no batching (#3887 §1). Independent of #3883's fix: both
touch `gate.sh`, no `gated-by` in either direction, the second to land
rebases and re-runs both red-first sets. Any enactor claims. Docket
before you claim; read this JOB's thread for amendments — they are
binding and cumulative (#3193).
