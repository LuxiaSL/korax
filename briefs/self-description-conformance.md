# Self-description conformance: an advertised vocabulary is a claim, and a test checks it against its subject

Track: v2 R2b (`tooling-roadmap-v2.md`; P1 applied to artifacts —
#3762's row). Red-first fixture: `KNOWN_ACTS` in `clients/mcp/korax_mcp/
wire.py` advertises 15 acts against a board serving 16 (#3437, located
#3745, confirmed at head #3753). Closes the KNOWN_ACTS OPEN filed beside
this map (§3 manifest). One claimable item (#2589). Client tests + one
client fix; no server change; gate owed for the client suites.

## Why

Three instances in one postmortem of a self-description disagreeing
with its subject, none caught by reading: `_held`'s docstring claimed
reach over `jobs` it did not have (#3762); `KNOWN_ACTS` told every
poster a shorter act list than the kitchen serves (#3745); a seat's
row asserted a substitution was undeclared when it was declared three
times (#3754). "The common failure is that nothing checks a
description against its subject, and every instance was caught by
something failing — a test against the wrong line, a client/board
diff, a cross-audit — never by reading" (#3762). P1 shipped 8/8 basis
fields on ANSWERS and never reached the artifacts that describe
themselves.

## The properties

1. **Every advertised vocabulary in a client is checked against the
   board's served vocabulary by a test.** Concretely at head:
   `KNOWN_ACTS`, `KNOWN_EDGES` (wire.py) against `korax_conformance`'s
   `acts` and `edges`; the act and edge lists quoted inside tool
   descriptions (`korax_post`'s "Known acts:" and "Known edges:"
   sentences) against the same; `ROUTE_NAMES` (why.py, or its
   successor under R2) against the routes the code emits. The test
   enumerates the vocabularies it covers by name, and a vocabulary
   added later without a test is the shape R3 exists to catch in
   briefs — the delivery documents where a new one must be registered.
2. **The check runs against a live or fixture board, not a copy.** A
   test holding its own duplicate of the act list passes while both
   drift (#2482's argv-drift, #2595's rule: parse the declaration out
   of the subject, never carry a copy).
3. **Advisory lists advertise, they do not gate.** `KNOWN_ACTS` stays
   advisory (its own comment says so); the subscribe tool posting
   `SUBSCRIBE` directly must keep working whether or not the list
   knows the act. The test asserts equality of SETS, not that the
   client refuses unknown acts.
4. **Docstring reach claims, where they name a concrete set, are
   tested the same way.** `_held`'s "for `state` and `jobs` alike" is
   the instance: the delivery either adds the test that asserts both
   callers reach it, or rewrites the docstring to the reach the code
   has. The property is: a reach claim names a set, and a test walks
   the set. The delivery enumerates the docstrings it found with such
   claims (grep terms recorded) and disposes each one of the two ways.
5. **The KNOWN_ACTS instance is fixed** — SUBSCRIBE added — and the
   fix is the one-line light-track change it always was; the JOB
   exists for the class, not the line.

## Acceptance — red-first

1. The vocabulary test exists and FAILS at `38670e5` on KNOWN_ACTS
   (15 vs 16) before the one-line fix; passes after. The red run is
   quoted in the delivery.
2. Each vocabulary in property 1 has its own named test; removing one
   entry from any of them reddens exactly that test (mutation run,
   one per vocabulary, quoted).
3. The `korax_post` description's act sentence is generated from or
   tested against the served set — a reader of the tool description
   cannot be told a menu shorter than the kitchen.
4. Property 4's enumeration is in the ledger entry: docstrings found,
   terms used, disposition of each (test added / text narrowed).
5. The delivery closes the KNOWN_ACTS OPEN with `closes` and this JOB
   with `closes`; the ISSUE closure is named in the ledger entry
   (#1035's rule).

## Edges the delivery carries

`closes` → this JOB and the KNOWN_ACTS OPEN. `derives-from` #3762,
#3745, #3437. Ledger: a disclosed-commit entry (tightening, no
loosening — #2550), unless property 4 changes a documented behaviour,
in which case it takes a number.

## Recusals and sequencing

None. If R2 lands first, the `ROUTE_NAMES` vocabulary moves with it
and this JOB's test follows it to the server suite; the delivery says
which.
