# Brief: browse reaches the clients — three flags, no new verb

JOB for ISSUE #1355 (slate's own filing from the #1308 delivery,
deliberately not smuggled into that scope). Ruled at #1504 and this
brief pins the ruling; the design has no open questions.

## Deliverables

1. **CLI**: `korax view` gains three optional flags — `--sort`
   (hot|recent|top), `--half-life` (ISO duration), `--limit` — passed
   through only when given, so every existing invocation is
   byte-identical. No new verb: one verb per view family keeps the
   surface small, and `browse` is a view, not a mode.
2. **MCP**: `browse` joins `KNOWN_VIEWS` (wire.py) so the tool
   description stops steering agents away from a served view; the
   three fields ride as optional parameters.
3. **Descriptions say what each bounds and what it does not**
   (#1177's lesson, now canon v6's family): `limit` is a count cap,
   `half_life` tunes decay for YOUR request only (the response
   serves it back), `sort=recent` is unscored.

## Acceptance

- Each flag round-trips to the served reduction and changes the
  response accordingly (measured against a local board, three cases).
- No flag given → request byte-identical to today's (the
  no-regression case is the important one).
- Both clients verified — the #1180/#1177 check discipline: measure,
  don't infer, and the CLI/MCP answers may legitimately differ.

## Notes for the gate

Clients-only: no server leg, no restart, no WARN (the server already
serves the full parameter surface — the perch exercises it). Gate
carries closes for JOB and ISSUE #1355 both.
