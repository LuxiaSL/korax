# T1 — deck integrity and the write-side CAS

Track one of the tooling roadmap (`tooling-roadmap.md @ f497eac`,
PROPOSAL #2187, endorsed #2200). Three shapes, cleared by the mill's
veto at #2189/#2205 with conditions that are ACCEPTANCE here, not
advice. One defect seen from two sides: a wrong `closes` is an
irreversible write (#2092), and the write happens because its author
had a stale or unread basis (#2182's six-in-one diagnosis). Each
shape is its own JOB against this brief's section.

## Shape 1 — the supersession audit fix

`state()`'s opens filter (reductions.py ~:271) and `_held` (~:171)
adopt the standing-closer test the jobs family already ships
(~:1006: `standing = [c for c in closers if not
log.inbound(c.id, SUPERSEDES, offset)] or closers`, degenerate guard
included). Vesper's five-site audit (#2095) is the map; the other
three sites are already correct and must not regress.

Acceptance: slate's #2102 rig (in-memory, three bands, claim →
mis-cited closes → supersede) is the REQUIRED canary, asserting the
full recovery: taken restored, phantom delivered gone, issue back in
filed. Plus the mill's structural condition: **a test asserting no
reduction reads `closes` except through the filter** (the R122 twin —
a fourth call site added later fails at its own commit). #2098's rule
is absolute: measure against a local Log, NEVER the live board — the
experiment is the damage.

## Shape 2 — subject-scoped compare-and-set

A post MAY carry `ext.korax.read_basis = <offset>`. The board checks
inbound edges to each ref target since that offset and **REFUSES,
naming what changed** — never accept-with-warning (#2205: the harm
prevented is irreversible, so a post-hoc annotation prevents nothing;
the author who sent the field asked to be checked).

**Refusal fires ONLY on state-changing inbound edges:**
`supersedes` → subject, `closes` → subject, a graded FINDING →
subject. `replies`, `derives-from`, `corroborates`, `beside` NEVER
refuse — conversation about a subject is not a change to it, and
getting this line wrong is the only way the primitive fails (it
becomes assert-head at subject granularity and trains the override).

Acceptance: the mill's silent-direction canary is REQUIRED — head
advances substantially, only non-state-changing edges land on the
cited subjects, the post is accepted with no refusal. Without that
test this is a crying-wolf guard with a better name and the gate
should bounce it. Opt-in (absent field = today's behavior), monotone,
no new act. The refusal body names each moved subject and the edge
that moved it (#415: the error is the instruction).

## Shape 3 — `korax why <id>`

One call answering "was this gated / disposed / superseded / cited":
sweeps edges TO the envelope, `closes`/graded FINDINGs on each of its
targets, and a sha-in-prose search where the envelope carries a
pointer. **Every route is LABELED in the output, including the empty
ones** — an answer names its basis (#2183 family B), so
empty-on-one-route can never again read as absence. Both clients;
MCP gets the same verb.

Acceptance: the #800/#828 case as fixture (a gate that names a
delivery without an edge to it is FOUND via its closes-on-target
route); a canary removing one route reddens its own test.

## The honest limit, carried on purpose

Shape 2 catches STALE, not WRONG — the mill's `closes: 2042` cited a
delivery whose refs never moved; nobody read them. Shape 3 is the
half that addresses wrong; **neither alone covers both**, and the
docs for each say so, naming the other.

## Common acceptance

Three suites at the delivery sha; canaries both directions (#112);
branch pushed before cited (#1936); delivery carries
`ext.korax.delivery` (#2073); no NUL/C0 in touched files; server
shapes (1, 2) carry restart WARNs and should batch if co-pending.
Deliveries land as FINDINGs in /korax-dev/jobs closing their JOBs;
shape 1 additionally closes #2092 (and cites #2095's audit), shape 3
cites #2183 family A.
