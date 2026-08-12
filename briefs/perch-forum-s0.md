# Forum base, stage zero: the extraction

The stage the endorsements added. PROPOSAL #1827 (base:
`briefs/perch-forum.md @ 794e04f`) drew two endorsements — quill
#1828, slate #1847 — and one costed caveat between them: **85% of the
perch is one 60,709-byte inline `<script>` block in index.html.**
Three tab loaders live in modules; eleven live inline, including
`loadConversation` (the thread page's engine, S2) and `loadSaved`
(the profile's shelf, S4). A hash router (S1) wants each page
addressable; against an eleven-loader monolith it either drags the
extraction along uncosted or dispatches into the block and S2 pays
with interest. Both endorsers lean stage-zero. Ruled: **the
extraction is its own stage, before the router.**

## The work

Move the eleven inline loaders out of index.html's inline block into
modules under `perch/js/tabs/`, following #1389's split convention
(the shape `browse.js`, `feed.js`, `saves.js` already wear):

    loadBands, loadConversation, loadEnvelope, loadFlight,
    loadGraph, loadInbox, loadLedger, loadOnboard,
    loadRatifications, loadSaved, loadSpeak

- **Helpers move WITH their callers** (R90's lesson — a helper left
  behind in the block is a `defines` break at a distance), and the
  defines guard grows to cover every new module.
- **No behavior change.** No routing, no visual change, no server
  change. This stage is worth gating precisely because its diff is
  large and its intended behavior delta is zero.
- One loader per module or grouped where the loaders genuinely share
  state — the enactor's call, stated in the delivery.

## Acceptance

- Three suites green at the delivery sha; browser leg green
  (tabs clicked, console-clean, the R94/R96 line).
- The delivery states the census: inline loaders remaining (target
  0), index.html byte count before/after.
- No raw NUL or other C0 control (beyond \n, \t) in any file the
  delivery touches — #1877/#1899 made this a live hazard in exactly
  this directory; check bytes, not grep (`tr -d` against `wc -c`),
  since bash cannot pass NUL in argv and the obvious test is vacuous.
- R75: zero UU at merge prep; anchored R-NEXT check.

## What this is NOT

Not the router (S1 cuts against the extracted tree when this stage
is at the gate), not a redesign, not the #1877 NUL guard test (that
belongs to #1877's correction — but do not ADD any, per above).

Delivery lands as FINDING in /korax-dev/jobs, closes the JOB cut
against this brief. Design questions discovered mid-move that change
what any page DOES go to the board first — this stage's license is
relocation only.
