# Brief: the perch smoke — a real browser clicks every tab

JOB for ISSUE #1597 (the DOM-runtime sweep), requested with a brief
at #1614 because the gate will lean on this infrastructure. The
shape questions are RULED here so the build starts settled:

## The rulings

1. **Real headless Chrome over CDP — not jsdom, not a stub DOM.**
   The two rejected shapes both simulate; a simulation of a DOM can
   lie in exactly the dimension this guard exists for. The CDP
   pattern has prior art on this host twice tonight (#1431's browser
   lane, #1491's click-through) with zero installs (Node 22's
   built-in WebSocket). The R82-split bug was a RUNTIME error in a
   REAL browser — the guard runs what the operator runs.
2. **The test**: seed a local board (tools/seed_dev_board.py —
   determinism is the point), serve it, drive Chrome through EVERY
   tab (enumerated by glob over js/tabs/ plus the shell's nav, with
   a non-empty assertion so a stopped glob fails loudly), and
   **fail on ANY console error or uncaught exception** — the general
   guard, not a known-identifier list. The #1597 class
   (called-but-undefined) is one instance of "the console is clean";
   assert the class's superset.
3. **Residency**: a pytest integration test, marked (e.g.
   `browser`), living in server/tests. MANDATORY in the mill's gate
   ritual for any delivery touching perch/**; in CI if the runner
   has Chrome — the builder VERIFIES what ubuntu-latest ships and
   states the answer in the delivery rather than assuming (#1422's
   lesson: CI's environment is a measurement, not an inference).
   If CI lacks Chrome, the gate leg is the backstop and the delivery
   says so plainly.
4. **Canary both directions** (canon v6 #112): plant an undefined
   call in a scratch tab file, watch it fail naming the tab; remove,
   green. The seeded corpus must light every tab non-empty — a tab
   that renders nothing exercises nothing, and the seeder's corpus
   is amended in this delivery if any tab starves.

## Notes for the gate

Test-infrastructure only: no served-code changes, no deploy leg. The
gate's own ritual gains a step (run the browser suite on perch
deliveries) — the mill amends its manual on the gate FINDING, per
its own #1613 instrument-limitation practice. Closes ISSUE #1597.
