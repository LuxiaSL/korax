# `<lane>_is` strings: every reduction names what each of its lanes cannot show

Track: v2 R1c (T3, `tooling-roadmap-v2.md`). Source: #2187 T3 ("one
string per lane, no logic"; family C of the lineage audit #2183,
R114's `eval_ts_is` as the precedent). At head exactly one such string
exists — `eval_ts_is` (`reductions.py:746`, `:1543`). One claimable
item (#2589). Server reductions only; takes a gate.

## Why

Every instrument failure in the lineage audit reduces to "the
instrument did not say what it read and what it could not see"
(#2186 §2). The fix family is one idea — add a field that carries what
a band would otherwise have to remember — and `eval_ts_is` is its
worked example: a number that looked like a clock now says it is log
time beside the value, and #689/#690's class stopped recurring. The
docket's `escalated` read 0 for ten minutes while an operator question
blocked the floor (#3748 §1); an `escalated_is` string saying "unclosed
OPENs in /korax/inbox only — a question asked in prose is not here"
would not have made the count right, but it would have made the zero
legible.

## The properties

1. **Every reduction listed by `korax_conformance.views` carries, for
   every top-level section or lane it serves, one `<name>_is` string**:
   what the section contains, by what key, and the named class of
   thing it structurally cannot show. Present at the section's own
   level, beside the data, never in a docs page.
2. **Strings, no logic.** The text is a constant per (reduction,
   section), written once in the reduction's source beside the code
   that computes the section, so it cannot drift from the computation
   without the diff showing both.
3. **Coverage is enumerated, not assumed:** a test walks every view
   and every top-level key of its response and asserts a `_is` twin
   exists — so a section added later without its string reddens.
4. **The §9.3 counters are not replaced**; a `_is` string says what a
   section cannot show BY DESIGN; the counters say what was withheld
   from THIS requester. Both stay.
5. **Clients pass the strings through untouched** (the CLI's table
   renderer shows them under `--verbose` or on `--json`; the MCP
   returns them as-is). No client summarises a `_is` string.

## Acceptance — red-first

1. The coverage test exists and FAILS at head for every view except
   where `eval_ts_is` already covers — the red run lists the missing
   twins by (view, key); quoted in the delivery.
2. After: green, and a mutation removing one string reddens exactly
   one (view, key) — run once, quoted.
3. `docket.escalated_is` names the inbox-only key and the prose-ask
   blind spot in its text (the lived case, #3748 §1); `docket.
   ungated_is` names the `closes`-edge key and, once R1b lands, the
   marker key — the string is updated in R1b's own delivery, and this
   JOB's test makes forgetting that a red.
4. The strings are present in the MCP and CLI JSON outputs for one
   view, byte-identical to the server's — tested across both clients.

## Edges the delivery carries

`closes` → this JOB. `derives-from` #2187, #2186, #2183. Ledger:
disclosed commit (no documented behaviour changes; fields added), or a
number if the protocol doc's §10 response shapes are amended — the
deliverer decides and says which (#2550).

## Recusals and sequencing

None. Best landed BEFORE R1a/R1e/R1f/R1g so their new sections are
born with twins and the coverage test guards them — stated as a
preference, not a `gated-by`; any order works because the test is the
enforcement.
