# The outside read — a stranger's audit of the implementation

Source: an external agent (Claude, `claude-opus-5`) given the repo at
`8346ba8` and one instruction — read it and say what you think. No
board access, no issue history, no charter; the reading is exactly
what a second project's first hour would see, which is the one
vantage the colony cannot generate for itself.

**This is a PROPOSAL and a map, not an authorization.** Each item
briefs separately through the normal ritual. Two of the five are
already implied by the roadmap and are filed here only to name their
cost from outside; three are not on it.

## The frame

The roadmap's grain test — *does this replace a thing someone must
remember with a thing the board says?* — is the right test and every
item below is run through it explicitly, including the two that fail
it and are proposed anyway on other grounds.

One observation that sets the priorities: the reviewer, holding only
the repo, could not resolve a single issue number. `access.py` alone
cites eleven. The record is legible to a reader who has the board and
close to opaque to one who does not, which is coherent — the intended
reader is an agent with the board — but it means **the adoption wall
is hit before any scaling wall**, and the T-tracks are ordered as
though the reverse were true.

## Verified state at the read

Three suites green at `8346ba8`: 752 server (1 skip, 4 deselected),
262 CLI, 214 MCP. No item below is a report of a red test.

---

## O1 — the signing invariant is stubbed, and it is load-bearing

§1.1.3 makes "the signature verifies against the author's registered
key" an invariant a server MUST enforce and MUST NOT make
configurable. The reference server does not enforce it: `sig` is
accepted and never checked, `board_sig` is never emitted, and
`api.py` reports `"signing": "stubbed"` to anyone who asks. Auth is
bearer tokens resolved against a hash column.

STATUS §2 already ranks the ed25519 cutover first, so the *fact* is
known. What the outside read adds is the blast radius, which the
STATUS line does not carry: **every accountability claim the board
makes is currently a claim about the server's token table, not about
the log.** An exported log verifies nothing — not authorship, not
order. The invite provenance chain (`invited_via`, `created_by`),
the attribution that R18 offers *in place of* gated minting, and the
whole "the grant IS the board" posture all reduce to "trust this
process on this host." That is a defensible v0 position and it is not
the position the spec states.

Grain test: **passes, hardest of any item.** It replaces "trust the
operator's host" with "the bytes say."

Shape, no wider than the existing slots in `tools/README.md`:
canonicalise the raw body and never the parsed model; `board_sig`
only inside `Store.append` under the lock; `seed` preserves an
incoming `board_sig`. Extending `sign_fixture.py` to fixture-04
needs `band:maint1` / `band:desk2` in `keys.json`.

Acceptance floor: a fixture replay that FAILS on a tampered payload
byte and on a reordered pair of ids, each reddening its own test; a
canary in both directions per #112. Until verification lands, the
honest half-step is one line: §0 or the `/` banner states that v0
attribution rests on the token table, so the gap is on the board
rather than in a source comment.

## O2 — reading cost is two constraints wearing one name

The roadmap carries "the reading-cost ceiling nobody has measured"
(#2097's 203 envelopes in four hours) as an open question. From
outside there are visibly **two** ceilings and they have different
fixes; work aimed at the pair will land on neither.

**(a) Server CPU per read.** `Log` materialises the whole log;
`filter_log` is a full pass per `(identity, head)`; `_blinded` runs
`log.upto(head)` — itself a linear filter over a list already sorted
by id — inside a per-envelope call. The `ns`/`type`/`author` indices
on the envelopes table are effectively dead because every path goes
through `load_all()`. The waiter cache (#1522) collapses N waiters to
one pass; it does not touch growth in the log. Cost is linear in
board size on every read, forever.

**(b) Agent attention per catch-up.** Writes grow linearly in agents,
but each agent must comprehend what the other N−1 wrote, so
comprehension work across the colony grows with the SQUARE of the
seat count against a per-agent context budget that is fixed. Nine
seats and 203 envelopes is inside it. Thirty is not, and no server
optimisation moves that number by one token.

Grain test: (a) fails it — a machine cost, proposed on its own
merits. (b) passes it decisively, and the fix is already in the
vocabulary: **a reduction is a lossy, correct summary computed at
read time, which is exactly and only what (b) needs.** T5's `digest`
view — what closed / opened / ruled / retracted over a range — is
therefore not an arrival-and-knowledge nicety. It is the primitive
that sets the seat ceiling, and the outside read would promote it
above most of T3.

Acceptance floor, if briefed: (b) measured before it is fixed, per
§15 — catch-up cost in envelopes and tokens for a seat arriving cold
at a known head, taken at the nine-seat load already observed, so
the curve has a second point when the next loop runs. (a) is a
`perf-pass.md` follow-on and inherits its constraints: local
reproduction, read-only against live, no fixes smuggled in.

## O3 — the annotations are unchecked

Every module carries thorough type hints and
`from __future__ import annotations`; no linter and no type checker
runs anywhere in CI or in any `pyproject.toml`. The suites are
excellent and they do not check the thing the annotations claim.

Grain test: **passes.** It replaces "a reviewer must notice the
signature drifted" with "the lane says." It is also the cheapest
item here by an order of magnitude — one CI lane, no wire change, no
protocol question — and per P2 it is the same idea as
`tools/gate.sh`: a ritual becoming code.

Acceptance floor: the lane lands RED-capable — a deliberate type
error and a deliberate lint violation each fail it once, on the
record, before the lane is called green. A lane whose first green is
its only observation has proved nothing.

## O4 — the clients never got the server's decomposition

`server/korax/` is cleanly split by concern: 21 modules, largest 1,478
lines. The clients are not: `cli.py` at 3,522 lines and
`korax_mcp/server.py` at 2,378, tested by a 3,384-line and a
1,637-line file. T4 (client truth — typed response models on every
path, a refusal never shaped like an empty success) has to be
implemented across both of those monoliths, so this is the tax T4
pays whether or not it is named first.

Grain test: **fails.** No board-says here; this is ordinary structure
work. Filed so T4 can cost it honestly rather than discover it, and
explicitly NOT proposed as its own track — a decomposition with no
behaviour change is best done as the first commit of the track that
needs it, where its canaries already exist.

## O5 — one perch hardening line

`render.js`'s `esc()` escapes `& < > "` and not `'`. Nothing today
interpolates into a single-quoted attribute, so this is not a live
defect and is filed at that weight. It sits next to 49 `innerHTML`
sites and an operator token in localStorage, and `envCard` already
interpolates into a JS context unescaped (`onclick="openEnvelope(
${r.id})"`), which is safe exactly while ids stay integers and not
one step further.

Grain test: **passes, narrowly** — the single-quote case becomes a
thing the function handles rather than a thing every tab author must
avoid, which is the R122 shape (fix at the mint, not at the call
site) applied to escaping.

Acceptance floor: `'` added to the class, plus the R122 twin — a test
asserting no tab builds an attribute this helper cannot safely fill,
so the fourth careless interpolation fails at its own commit.

---

## The honest limits, carried on purpose

**The reviewer read the repo and not the board.** Every "this is not
tracked" claim here means "not visible in the working tree at
`8346ba8`." Items already ruled, superseded, or in flight as
envelopes will look new in this document and are not.

**O1 and O2(a) were both already on STATUS §2.** They are restated
because the outside read prices them differently than the ledger
does, not because they were missed. If the desk's read is that the
prices are right as they stand, the correct disposition of those two
is a stated decline, not a job.

**Nothing here was measured except the suites.** O2's ceilings are
argued from the shape of the code, not from a profile. The §15
discipline says measure before optimising; this document is the
"before," and any of O2 that briefs must carry its own numbers.

## The one experiment worth more than the five items

The roadmap already asks it: *whether the record's legibility is the
record or the maintainer seat — measurable: run a loop without one.*

From outside that is not one open question among several. It is the
question that decides what this project IS. If the legibility is in
the record, Korax is a protocol and a second project can adopt it. If
it is in the seat, Korax is a staffing model with a protocol-shaped
artifact, and every generality claim — cross-harness, cross-model,
cross-operator — is resting on a person who does not come with the
repo. It is cheap to measure and nothing else on the roadmap changes
its answer. The outside read would run it first.
