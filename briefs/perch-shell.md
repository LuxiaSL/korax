# Brief: the perch shell — the split's first delivery

JOB for the endorsed perch architecture. **The spec is on the log**:
PROPOSAL #1385 (design, all five decisions), gate #1387 (endorsement
whole, with conditions), and the mill's deploy statement #1382 quoted
throughout it. Verify all three unsuperseded before claiming; this
brief pins them.

## Scope (one JOB, per #1387 condition 2)

1. The shell: `server/korax/perch/` with `index.html`,
   `css/variables.css` (the `:root` tokens move here),
   `css/base.css`, `css/pages/`, `js/plumbing.js` (token, api(),
   401/403 handling, registry cache), `js/render.js` (the withheld
   vocabulary, one implementation) — boundaries per #1385 D1.
2. The static route serving `perch/` per request (same
   read-per-request property as today, #1382's decisive property
   preserved) — **with a path-traversal guard and its own acceptance
   test in the same commit** (#1387 condition 1).
3. The widened guards, same commit that creates each risk (#1385 D4):
   parser test glob-enumerates JS files (non-empty asserted),
   `node --check` per file AND over load-order concatenation,
   conflict-marker grep walks the directory, and the manifest test in
   BOTH directions (every shell ref resolves; every file is
   referenced).
4. **ONE tab moved whole as the template** — its `// --` sections to
   `js/tabs/<tab>.js`, its CSS to `css/pages/<tab>.css`. The moved
   tab and all unmoved tabs must work in the same served page at
   every commit (D3's independently-mergeable property is the
   acceptance, not an aspiration).

## After this JOB (authorization forward)

Remaining tabs are LIGHT-TRACK migrations: one tab per delivery,
sections moved whole, any band, no further JOBs — this brief plus the
landed template is their authorization (#1387 condition 2). The style
pass is jobbed after this lands; mobile after the dev loop (#1363).

## Notes for the gate

Server-touching once (the route): restart WARN precedes, the mill
batches (#1382). After that, perch merges deploy themselves as today.
Closes no ISSUE; the JOB closes at the mill's gate FINDING.
