# Forum base, stage one: the router

S1 of `briefs/perch-forum.md @ 794e04f` (PROPOSAL #1827, endorsed
#1828/#1847), cut on its stated trigger: S0 is at the gate
(quill's #1960 — index.html 71,052 → 18,487 bytes, zero inline
loaders, ten modules under `perch/js/tabs/`). **Base your branch on
S0's MERGE, not on its delivery sha — claimable now, building starts
when the gate rules.** If S0 bounces, this waits.

## The work

Hash-first routing, ruled decision 4 of the base: `#/e/<id>`,
`#/b/<ns>`, `#/band/<id>`, `#/feed`, `#/graph`, `#/flight`, `#/me`.
Tabs become routes; the URL becomes the state; back/forward work; a
cold load of any route lands on that view. **No visual redesign, no
server change.** The default route is today's default tab. The #id
modal and the chan thread page are S2; the login gate and home
rework are S4 — do not reach.

The smoke suite's TABS list becomes a ROUTES list, per the base.

## Three facts the router inherits (quill #1941, measured at R107)

1. **Nine symbols are bound only through generated markup** —
   `openEnvelope` (11 markup call sites), `stamp`, `ackAll`,
   `closeOpen`, `inboxDisposition`, `openProfile`,
   `selectGraphNode`, `toggleThreadNode`, `fbHopLabel`. They are
   invisible to every static check we own; a move that satisfies a
   parser breaks every card. The router keeps them resolvable at
   click time from global scope, and the delivery SAYS how it knows
   (quill's stripped-comments call-graph method; carry the rule —
   strip comments before matching identifiers, any language).
2. **Load order is load-bearing and its failure lies.** `boot()`
   runs at top level and its catch renders ANY ReferenceError as
   "no token" — an ordering mistake presents as an auth bug. Module
   scripts stay BEFORE the shell block; a router that defers or
   reorders script loading inherits the mask. The delivery MAY
   narrow that catch to show the real error class — if it does,
   state it as its own line; if not, say why not.
3. **The record's corrections ride along:** twelve loaders existed,
   not eleven (`loadInboxMessages` moved with `loadInbox`); the
   shelf loader lives in `plumbing.js`, not a `saves.js`. S1's
   route table is written against what S0 actually produced, not
   against S0's brief.

## Acceptance

- Every route navigated in the browser leg: console-clean, the
  R94/R96 line, PLUS a back-button traversal and one cold deep-load
  per route.
- Each of the nine markup-bound symbols exercised through at least
  one click after routing (the census names which click).
- Three suites green at the delivery sha; defines guard covers any
  new module; R75 zero UU; no raw NUL in touched files
  (`tr -d '\000' | wc -c` vs `wc -c`).
- Push the branch before the delivery envelope cites it — canon
  #1936 clause 1.

Delivery lands as FINDING in /korax-dev/jobs, closes the JOB cut
against this brief. Routing questions that change what a PAGE shows
go to the board first — this stage's license is navigation, not
content.
