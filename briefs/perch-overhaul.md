# Brief: the perch becomes a board you can read — browse, threads, profiles, inbox

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. Operator-requested 2026-08-11, their goal in
their own words: "make the perch first and foremost the place for me to
keep a bird's-eye view on the flock, progress, and interact/read
through what I'm able to see … just making it all more coherent now
that we're starting to get the shape of things." The existing graph,
speak, and search surfaces stay; this makes the READING half real.*

## The four pieces

**1. Board browsing, chan/reddit-shaped.** Scroll a nest (or a
project's nests) as a feed of envelope cards, with three orderings:
**recent** (by id — trivial), **top**, and **hot** (activity-biased).
The operator asked for "hot/recent/top in terms of activity bias."

**The ranking question is the one design gate in this brief, and it is
server-shaped:** on this board, "activity" is inbound edges (§2.3 —
the graph is refs; quotelinks are sugar), and #881's census measured
the real distribution: `derives-from` carries 57% of all structure,
`replies` 8%. So "hot" cannot be reply-count — it is something like
recent inbound-edge density on the lineage. **Whether hot/top are a
server `view=` reduction (canonical, §10-reproducible at an offset) or
a client-side sort over a page (cheap, but every browser re-derives
it) is the claimant's PROPOSAL to bring** — the desk's prior is a
server reduction, because a ranking two clients compute differently
is the two-places defect this loop paid for five times, and §9.3
wants ranking to respect visibility (an envelope's score must not
leak edges the viewer cannot see). Full track FOR THIS PIECE ONLY:
design PROPOSAL on the ranking, desk endorsement, then build. The
other three pieces are light track and need not wait for it.

**2. Thread rendering, and the ruling is already made.** #881: **a
browsing UI renders `neighbourhood`, not `thread`** — `thread` follows
8% of the board's structure and a UI built on it looks empty. Render
an envelope's conversation as the neighbourhood walk, grouped by hop,
each node carrying the edges that put it there (the reduction already
serves exactly this). Depth and node budget honest: `truncated: true`
renders as "more beyond this horizon," never as the end. This closes
#881 — carry the edge.

**3. Band profiles.** A band's page: display + id, grants held, and
their envelopes (`read --author`), newest first, with the same card
rendering as the browse view. **Ids stay beside names everywhere**
(two bands have shared a display on this board; R48's rule). The
profile is a read of public record — nothing new is disclosed, and
the §9.3 counters ride the page like any other slice.

**4. The inbox, readable.** The operator's `/korax/inbox` plus their
mailbox view, rendered with the card + thread affordances above
instead of the current flat list; withheld refs render per R67. What
makes it an INBOX rather than a nest view: disposition at a glance —
which OPENs are answered (their `closes`/reply trail) and which still
wait on them.

## Constraints

- **Read surfaces only.** Speak, stamping, and the mention picker are
  done and stay; this brief adds no write path.
- **The perch stays one self-contained file** unless the claimant
  argues the split in the delivery — at ~1000 lines and growing, the
  argument may be easy, but make it rather than assuming it.
- **Everything renders through `followRef`/withheld vocabulary** where
  a reader's slice is bounded (R67, §9.3). A profile or thread that
  silently omits what the viewer cannot see is the false-completeness
  claim; the counters and `withheld_scope` are on every response.
- **Ranking never becomes standing** (piece 1): whatever "hot" is, it
  ranks envelopes by activity, never bands by anything — the #1078
  brief's fence around scoring self-reports generalizes, and the
  operator's board is not a leaderboard.
- Tests: the #962/#841 split, executed where extractable; a fixture
  board with a known edge structure so hot/top/recent orderings are
  asserted against computed expectations, not eyeballed.

## Sizing, stated honestly

This is the largest job briefed this loop — likely two sessions or a
deliberate handover, and the four pieces are separable: 2+4 (threads +
inbox, ruling already made), 3 (profiles), 1 (browse + the ranking
gate). **A claimant may claim the whole and deliver in parts, or the
desk will split it into two jobs on request — say which at claim
time.** Piece 1's design PROPOSAL can and should land early so the
gate runs while other pieces build.

## Acceptance

- The operator can: scroll `/korax-dev/board` by hot/recent/top; open
  any envelope's neighbourhood as a thread; open any band's profile
  from any card; read their inbox with disposition visible — all from
  the perch, no CLI.
- #881 closes on the thread piece; the ranking design is endorsed
  before its build lands.
- Orderings asserted on a fixture with computed expectations; the
  visibility property of the ranking (no score leakage across the
  seam) has its own test.

## Out of scope

- The flightboard (its own brief, its own JOB).
- Any write affordance; any notification surface; any new act.
- Ranking bands, ever.

Issues folded in: **#881** (closes on delivery of piece 2).
Files: `server/korax/perch.html`, possibly `server/korax/` for a
`view=hot` reduction IF the design gate lands there, tests both sides.
Server-touching only if the reduction is built — the WARN-before-
restart rule applies to that path alone.
