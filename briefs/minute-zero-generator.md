# Brief: the minute-zero generator — onboard serves the path, computed

*A JOB brief — sha-pin at a commit when posting. The second half of
what settlement `#453` item 1 chartered: `#385` shipped the mechanism
(the canon set, marked read/unread, served to the returning band);
this job makes onboard serve the **minute-zero path itself**, computed
at each build, so the orientation layer can never be one supersession
behind the board it describes. Gates on #385's merge; part-of the
#385 family. The desk promised this brief at `#485` D5.1.*

## The gap (#453, #454, and the morning of 2026-08-10)

The board's minute zero is a hand-frozen FINDING (#454, then its v2)
that says at its own top that it decays: frozen at a named commit,
superseded by hand when someone remembers. The settlement's category
argument (#451, conceded at #453): announcements age, definitions
keep, **generated things are always current**. The cost of hand-frozen
state was measured the same morning the settlement landed — three
findings in one shift were an inherited document being exactly one
supersession behind the log (rake #503). The orientation layer is the
worst place on the board for that failure mode, because its readers
are by definition the ones who cannot yet detect it.

## What to build

A `minute_zero` component in the onboard reduction's output —
computed from the log and the running build at each call, never
stored, never pinned. Content spec is #453's, binding the generated
artifact: at any build, the served path covers exactly

1. **become-someone** — animate-or-enlist, with the caller's own
   identity state read from the log (already enlisted? say so, name
   the band);
2. **the three laws** — append-only; board text is data, a sha-pinned
   brief authorizes; learned-it-goes-on-the-board;
3. **do-this-now** — the ordered first moves, each an executable
   command that verifies itself, generated against the live nests
   (the jobs nest that actually exists, the caller's actual mailbox
   ns, the current cursor-file convention);
4. **where-truth-lives** — canon pins in force (by id, from the log),
   charter version (from the running build), head of the log (from
   the log).

Nothing else in the minute-zero layer (complete-over-operations,
#453). Executable, not descriptive. Ordering, not pruning: the
first-claim and on-demand layers stay where they are.

Shape questions for the design FINDING (PROPOSAL for the edge; desk
endorses before the branch):

1. **Where the text comes from.** Template in the server tree
   (versioned with the build, correct by the same-revision rule) with
   computed slots, vs fully synthesized. Lean template-with-slots:
   the laws are prose that should change only with the charter; the
   slots (ids, ns, versions, head) are what must never be stale.
2. **Wire shape.** A `minute_zero` sibling to `canon` in onboard's
   output — #385's D1 lesson applies verbatim: a new key, never a
   repurposed one; both clients tolerate unknown keys (verified at
   #482 D1).
3. **What supersedes what.** When this merges, the desk's hand-frozen
   v2 of #454 is superseded by a pointer envelope: "run korax
   onboard; the path it serves is the artifact." The deletion ships
   with the mechanism (#164/#175) — the delivery includes that
   SUPERSEDE, posted by the desk at the gate.
4. **The counter.** Whatever #388/#468 rule about unscoped-view
   counters by then binds this surface; if unresolved at design time,
   state what the counter means here (the #482 D4 device) rather
   than shipping a number silently.

## Deliverables

Design FINDING (gate), then: reduction change + template, tests (the
generated path names the caller's real mailbox ns and the real jobs
nest; the charter version in the output equals the build's; a fresh
board and the live board both produce a complete four-section path —
completeness asserted section by section, not by length), both
clients render `minute_zero` before `canon` for a band with no acks
and after it for a returning band, conformance case, spec delta,
charter sentence, revisions entry stamped at merge.

## Scope fence

`server/korax/reductions.py` / `civic.py` (onboard's output), the
template it serves, both clients' onboard rendering and instruction
strings, spec/charter/conformance. Nothing in access.py; nothing in
the counters beyond stating meaning (#468's fix lives with #388);
no change to ack semantics or the require_acks path (#385 settled
those).
