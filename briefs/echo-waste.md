# Echo waste: input reflected back as output, measured, then fixed

Cut on the operator's word (2026-08-16 ~05:45Z), sharpening the
census (#2699): measure the PRECISE number of near-exact matches
between tool input and tool output — the canonical instance being
envelope posts whose result echoes the entire accepted envelope,
payload included, so the document is billed twice on one call — find
the other forms of the same shape, and evaluate whether general-use
ergonomics can improve. One claimable item (#2589): the measurement
FINDING and the ergonomics PROPOSAL are one continuous piece of work
by one hand, delivered as two envelopes.

## Part 1 — the measurement

The instrument is the census tool (`tools/transcript_census.py`,
delivered at `1ee40e9`, in the mill's gate queue at cut time).
Coordinate the base with the queue state at claim: if unmerged,
branch from the delivery sha and declare the dependency; do not
rebase anyone's branch (#2675).

Properties, not code (#2574):

1. **Per tool/verb, input↔output reflection measured two ways, both
   with denominators (#2667):** EXACT containment — an input field's
   text (a post's payload, an ack's note) appearing verbatim in the
   tool result; and NEAR match — normalized similarity above a
   stated threshold, the threshold printed beside every number that
   depends on it. Report: matched uses / total uses per verb,
   echoed bytes / total result bytes per verb, and the corpus-wide
   share of all tool-result bytes that are reflection.
2. **Known candidates to check, not assume** (read real records):
   `korax_post` results echoing the accepted envelope; `korax_ack` /
   `korax_bump` echoes; CLI `post`/`envelope` output; self-reads —
   a session draining envelopes it authored itself (the watch wakes
   you on your own thread's replies and the drain returns your own
   text); errors that quote the offending input back. Candidates
   the data refutes are reported as refuted.
3. **The census's own traps apply**: requestId dedup (the 2.54x
   naive-sum trap, #2699), exact-vs-estimated labeling, and the
   seam — similarity is computed in code and discarded; the report
   carries verb names, counts, and byte totals, never payload text.
   The existing structural-seam tests must stay green unmodified;
   if the new code paths touch text, they get their own planted-
   canary test in the same shape.
4. **Red-check the matcher both directions** (#2666): a fixture
   where the echo is known must count it; a fixture with no echo
   must count zero; and break the matcher deliberately and watch
   the fixture redden before believing the corpus numbers.

## Part 2 — the ergonomics PROPOSAL

On /korax-dev/board, options surveyed, ONE recommended (the
judge-panel shape, #2431 precedent), fed by part 1's numbers. Must
weigh at least:

- **Server-side minimal ack**: post-family results return
  `{id, ts, band, ns}` (the server-assigned facts the caller cannot
  know) with the full envelope available by explicit ask. The
  caller's own text is the one thing the caller already has.
- **Client-side shaping**: CLI quiet/terse modes; the MCP server
  trimming results before they reach the model.
- **Read-side forms** if part 1 finds them material: self-read
  suppression or summary-by-default on lanes that return the
  reader's own authored text.

Constraints in force: the MCP tool SURFACE is frozen at handshake
(#2621) — result-shape changes need no new verbs, but any client or
test relying on echoed fields must be surveyed and named (grep, with
the file list in the proposal); the never-fuse rule (#2393) if
identity fields are touched; flag-day statement per #2337 for
whatever the recommendation implies. What measurement would have to
exist before building is named explicitly (#2564 §4's lesson: no
unrun command as a load-bearing clause).

## Shared acceptance

Three suites green at the delivery sha; zero UU; branch pushed
before cited (#1936); `ext.korax.delivery = {sha, branch}` (#2073);
shas from `git rev-parse` (#2262). The measurement FINDING lands in
/korax-dev/jobs and closes the JOB; the PROPOSAL lands on
/korax-dev/board citing the FINDING and awaits adoption — building
it is a separate cut on the desk's or operator's word.
