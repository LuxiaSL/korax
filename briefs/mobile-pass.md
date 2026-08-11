# Brief: the mobile pass — the perch fits a phone

JOB for the operator's #1342 §3 ("control this from my phone and see
what's going on"), sequenced at #1365 behind the dev loop and due now:
the loop's mechanics are live (#1346), its docs are delivered at the
gate (#1363 @ 3183e9f), and the shell (R82/#1385 D5) placed exactly
where this work lands — responsive rules in `css/base.css` and
`css/pages/*`, nav behavior in the shell. No tab logic in the diff.

## Deliverables

1. Every tab usable at phone width (390px reference; 360px should not
   break): no horizontal scroll on the page body, wide content
   (tables, cards, id chips) scrolls inside its own container, touch
   targets at sane sizes, the nav reachable one-handed (builder's
   call on pattern — wrap, scroll, or collapse — stated in the
   delivery).
2. The token dialog and reply/compose affordances usable on a touch
   keyboard.
3. Verified in a real mobile viewport (devtools emulation is fine;
   name the widths and browsers checked). Screenshots in the delivery
   at phone width for: Feed, Inbox, the flightboard, Browse.

## Constraints

Style tokens stay in `variables.css` untouched except where a size
must become relative — the style pass (#1342 §4) is a SEPARATE
follow-on and this JOB does not restyle, it reflows. Perch-only:
merge is the deploy, no restart, no WARN (R84's standing rule).

## Notes for the gate

Structural tests where they fit (the manifest test already guards
refs); visual acceptance is by the named screenshots — a reflow
cannot be fully asserted in pytest and the delivery should not
pretend otherwise.
