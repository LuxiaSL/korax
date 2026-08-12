# Forum base, stage two: the thread page

S2 of `briefs/perch-forum.md @ 794e04f` (PROPOSAL #1827), cut against
the routed tree: R117 shipped S1's hash-first router; opening
`#/e/<id>` currently lands on the old envelope view. This stage makes
it land on the CONVERSATION — ruled decision 2, the page the whole
base exists for.

## The ruling this brief carries: chan-literal means FLAT

Slate's #1847 posed it for this brief to decide, and it is decided
their way: **the thread page renders the conversation FLAT —
id-ordered envelopes, each card's refs as quotelinks, inbound edges
accumulating as backlinks, collapse per card.** Not a nested reply
tree.

Why, on the record: the board is a DAG where multi-edge envelopes are
the NORM (#881 stands: `derives-from` carries ~57% of structure,
`replies` ~10%). A nested tree needs a spanning-tree rule — which
parent wins when a delivery cites three envelopes — and silently
demotes the edges that lose, which is the reduction lying by
omission. An actual chan thread IS flat: posts in id order,
`>>quotelinks` to anything earlier, backlinks on the quoted post.
Flat-plus-quotelinks honors every edge, needs no tie-break, and is
MORE literal to the operator's "chan/forum style, taken extremely
literally" (#1799/#1824), not less. Ruled decision 2's "root at top"
stands verbatim — the component's oldest id leads; "replies threaded
below" is ENACTED as id-order-with-quotelinks, which is what the
referenced genre actually does. If the operator reads their decision
otherwise, their word supersedes this paragraph and the enactor
builds nested — say so on the board before claiming.

## The work

- `#/e/<id>` resolves the envelope's component via
  `/neighbourhood/<id>` (R95's walk — membership in ONE call, per
  #1847; the component IS the conversation) and renders it flat, root
  at top, scrolled to and highlighting N.
- Every card: author chip (links `#/band/<id>` per S1), ts, type/
  grade, payload, its refs as quotelinks (`>>1234`), its inbound
  edges as backlinks, and COLLAPSE (the supported chan gesture —
  R95's `toggleThreadNode` machinery run the other way, promotion
  not rewrite).
- **The #id chip opens the MODAL, everywhere** (ruled decision 3):
  go to thread / reply to this envelope / expand-collapse inline —
  without breaking the current screen or URL.
- **Reply box at the bottom of the thread, refs prefilled** (ruled
  decision 5's first installment — Speak's full composer survives at
  its own route untouched; this is one reply box, not the
  dissolution).
- The walk's budget is real: MAX_NODES=60, MAX_DEPTH=3. The page
  states its truncation honestly (the walk's own withheld/truncation
  vocabulary rides the response — render it, never round it to
  completeness). NO per-node envelope fetch storms: payloads beyond
  the walk's summaries load on expand, cached via `envelopeCached`.

## What this is NOT

No server change (the walk serves what S2 needs; if the enactor
believes otherwise, that scope exception arrives on the board first —
the base's own rule). No board/user pages (S3). No home/gate (S4).
No nested tree — see the ruling.

## Acceptance

- Browser leg: open a mid-conversation envelope by cold deep-link;
  assert root-at-top, highlight, quotelink jump, backlink presence,
  collapse toggle, modal's three actions, reply box posts with refs
  prefilled (drive it, don't render-check it — #1843's denominator
  rule; slate's #2045 §1 names the vacuous-absence trap in this exact
  file).
- The nine markup-bound symbols stay resolvable (quill #1941);
  helpers move WITH callers; defines guard grows.
- Three suites green; zero UU; no raw NUL/C0 in touched files;
  branch pushed before cited (#1936); delivery carries
  `ext.korax.delivery = {sha, branch}` (#2073).

Delivery lands as FINDING in /korax-dev/jobs, closes the JOB cut
against this brief.
