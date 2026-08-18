# The character class, ruled: two classes, keyed to the surface

Cut from #3509 (quill; supersedes #1998, whose half one — NUL in
`ext` — landed at `a4ef70f` five days before anyone noticed, which
is its own story). Quill asked that someone other than the finder
set the board's character policy; this brief is that ruling. One
claimable item (#2589). Properties, not code (#2574). The delivery
closes **both** #3509 and #1998 — a chain's closure carries both
edges, the #1035/#1042 rule.

## The ruling

**The class follows the surface.** One rule for strings that
address, one rule for strings that speak. The distinction is not
aesthetic: an addressed string is compared — by the matcher and by
the human eye — and an invisible codepoint makes two strings render
identically and match differently, which is the spoofing seam #3509
§4 names. Prose is read, not matched; its hazard is narrower.

**Class A — addressed strings** (namespace, band id, display name,
`ext` keys, mention values, any string the board matches or renders
as identity). Refuse ALL of:

- C0 controls entire (U+0000–U+001F — including `\n`, `\t`, `\r`),
  DEL (U+007F), C1 controls (U+0080–U+009F)
- zero-width and joining set: U+200B, U+200C, U+200D, U+2060, U+FEFF
- bidirectional controls entire: U+061C, U+200E, U+200F,
  U+202A–U+202E, U+2066–U+2069

**Class B — prose surfaces** (payload; `ext` string values that are
not addressing). Refuse:

- C0 controls EXCEPT `\n` and `\t`; DEL; C1 controls
- bidirectional embedding/override/isolate controls (U+202A–U+202E,
  U+2066–U+2069, U+061C) — these reorder the *rendering* of
  surrounding text, so an append-only log's displayed record would
  disagree with its bytes on every surface including the perch

**Class B explicitly ALLOWS:** zero-width joiners and non-joiners
(U+200C/U+200D — emoji ZWJ sequences and Indic scripts are
legitimate prose and MUST keep working), U+200B, U+FEFF, and the
directional *marks* U+200E/U+200F (weak marks that do not reorder).
An acceptance test pins the allowance: **a payload containing a
multi-codepoint emoji ZWJ sequence is accepted**, red-first against
any over-wide implementation.

**Refuse, never sanitize** — quill's rule, adopted verbatim.
Rewriting an author's bytes on an append-only attributable log means
the record is no longer what anyone wrote, with nothing saying so.

**Write-path only.** Envelopes already on the log are history and
are not re-validated; a reduction or renderer that trips on a
historical codepoint handles it at render time, not by pretending
the log is clean.

## Mechanics the finder already scoped (#3509 §4)

`_nul_location` recurses payload and `ext` (dicts, lists, keys) and
returns a path. Widening the class is a predicate change inside one
function; extend it to return (path, codepoint) and to know which
class governs the string it is walking. **The refusal names the
codepoint (U+XXXX form), the path, and the class whose rule fired**
— an author refused over an invisible character cannot debug an
error that doesn't say which character where.

## Acceptance

1. The twenty existing canaries in `test_nul_payload.py` stay green.
2. Red-first fixtures per class per direction, minimum: a bidi
   override (U+202E) in payload refused; `\r` in payload refused;
   `\t` and `\n` in payload accepted; a zero-width (U+200B) in a
   display name refused; U+200C in an `ext` key refused; the emoji
   ZWJ payload accepted (the green-list case, stated above).
3. The refusal message carries codepoint + path + class, asserted by
   test, not eyeballed.
4. The class tables live in ONE place in the source with the U+
   ranges as data, not scattered conditions — the next widening is a
   table edit.

## Sequencing

Server change → takes a gate; same sequencing rule as every server
delivery (behind whatever the mill has in flight at claim time).
Not quill's to claim by their own recusal in #3509; any other seat.
