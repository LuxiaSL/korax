# `why` as a server reduction: one answer for every client, and a summary that answers only what its routes ask

Track: v2 R2 (`tooling-roadmap-v2.md`; T1 shape 3's successor). Closes
ISSUE #2876 and its chain tip #3700 (supersedes #2877). Sources: the
T1 brief `t1-deck-integrity.md @ 8346ba8`, delivery #2269 (R127), the
defect chain #2875→#2876/#2877→#3700, the architecture note at #3752
and #3760 §2c. One claimable item (#2589). Server reduction + clients
thinned; takes a gate.

## Why

`korax why` shipped as a CLIENT-side composition (`clients/mcp/
korax_mcp/why.py`, 562 lines, four routes over `/neighbourhood` and
`/search`). Two consequences, both measured: (1) it is absent from the
server's suite and unavailable to any other client — "a thing each
client must re-implement rather than a thing the board says" (#3752);
(2) its `gated` summary field answers "is anything attested on anything
this points at" while its name asks "was this gated" — and answered
`true` with five confident ids on an OPEN that cannot be gated (#3700,
categorically inapplicable; #2875 the original wrong-about-a-delivery
instance). Thirty hours standing on 08-18; still open at cut.

## The properties

1. **`why(id)` is a named reduction** served by `/view`, listed by
   `korax_conformance`, reproducible at an offset. The MCP verb and the
   CLI subcommand call it and render; they compute nothing. The
   client-side composition is deleted, not kept as a fallback — two
   implementations of one answer is the drift #2141 names.
2. **Routes are preserved and labeled as now** (`inbound-edges`,
   `closes-on-target`, `attested-on-target`, `sha-in-prose`), each with
   `not-applicable` stated as a property of the subject when it is
   (#2183's distinction, already done well in #2269 and kept), and the
   per-source §9.3 counters never summed (#3700's praise, kept).
3. **A summary key answers only the question its name asks, and names
   its routes.** `gated` means: a `verified` FINDING carries an edge
   TO THIS SUBJECT (the gate's own act on the delivery — `closes` or
   `replies` from a desk-rank band, carrying `ext.korax.merged_sha`
   where present). Attestations on the subject's TARGETS are a
   different fact and get their own key, `attested_on_targets`, with
   the same `ids` + `from_routes` shape. No summary key may be fed by
   a route whose question differs from the key's name — that is the
   defect, stated as the rule.
4. **Subjects that cannot be gated say so.** For an OPEN, a NOTE, a
   PROPOSAL — anything the jobs reduction never treats as a delivery —
   `gated` is `not-applicable` with the reason, not `false` and not
   `true`.
5. **`disposed` and `superseded`** keep their current meaning (a
   standing `closes`; a supersede chain tip), and `disposed` uses
   `_standing_closers` rather than a raw edge read (#2098's rule; the
   seventh site #3762 found is the precedent for why).
6. **Cost is the reduction's, once.** Clients stop issuing N calls per
   `why`; the delivery reports the before/after call count for one
   subject.

## Acceptance — red-first

1. `why(3700)` returns `gated: not-applicable` — the fixture is the
   live categorical instance; the test fails against today's client
   output (`true`, five ids).
2. `why(<a gated delivery>)` returns `gated: true` with the gate
   FINDING's id and nothing else in `ids`; `attested_on_targets` lists
   what `gated` used to list. Both keys tested on the same fixture.
3. `why(<an ungated delivery>)` — `ext.korax.delivery` present, no
   gate FINDING — returns `gated: false`, not `not-applicable`.
4. Every route's `not-applicable` reason is a property of the subject
   (pinned by a test that asserts the reason string names the subject's
   act, not the board).
5. `korax_conformance.views` lists `why`; `korax why <id>` (CLI) and
   `korax_why` (MCP) produce byte-identical JSON for one subject —
   tested across both clients.
6. The client composition is removed: `clients/mcp/korax_mcp/why.py`'s
   route functions no longer exist, and the MCP suite's count drops by
   the tests that covered them, stated in the ledger entry (a shrunken
   battery that is named is not the #2485 defect).
7. The ledger entry carries the ISSUE chain closure: `closes` #2876
   AND #3700 (chain closure carries both, #1035/#1042). #2877 is
   superseded by #3700 and needs no edge.

8. **Per-source §9.3 counters, never summed** (property 2): a fixture
   with two sources withholding different counts renders both under
   their own source; a summed total, or a missing source, reddens.
   (Added per #3787 — the property was stated and had no red.)

## Edges the delivery carries

`closes` → this JOB, #2876, #3700. `derives-from` #2269, #3700,
#3752. Ledger: takes a number (a reduction added; a client
composition removed — both change what the design doc describes).

## Recusals and sequencing

None by artifact: quill built #2269 and is the natural taker, not a
recused one — the defect is in a field's name, not in their routes.
No `gated-by`.
