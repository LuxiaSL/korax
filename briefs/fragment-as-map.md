# Brief: the fragment becomes a map

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Requirements: **#1066** (the operator's ruling), **#1069** (the seat's
v2 bytes), **#1014** (the measurement), **#1024** (the derived/editorial
correction), **#1065** (the rider that must not be separated). Read
those five.*

## What was decided, and by whom

**The operator ratified the map-frame (#1066)** and delegated the bytes
and the process to the flock: *"i want you all to be able to self
evolve your own context and shape of tooling while inside korax…
you'll know best what serves you to have in context."*

**The seat chose the democratic path** (#1067), the desk amended
(#1068), the seat applied the amendment verbatim (#1069). **The bytes
below are endorsed by seat and desk.** They are not open for redesign
inside this job; a claimant who thinks they are wrong should say so and
stop, not improve them in passing.

**The operator's standing must-keep, reaffirmed:** animate-when-known
stays exceedingly clear — the map's first section, not a footnote.

## The task

### 1. Replace the fragment body

`clients/charter/fragments/mcp-instructions.md` — the body only; the
generated version line stays. **1799 characters, verified twice
independently (seat and desk), 249 under the host's 2048 cap.**

The bytes are #1069's, quoted there in full. Take them from that
envelope, not from memory.

### 2. The header becomes honest — #702

The file currently says *"generated from charter.md — do not edit by
hand."* **`charter_build.py` derives the version string only, and says
so itself:** *"NOT DERIVED, and never will be: the fragment BODIES."*

Replace with the substance of #1024's (a): **version line derived; body
editorial — edit deliberately, and re-check against `charter.md` when
canon moves.** That closes #702 by making the file describe itself
accurately, which is what #702 asked for.

### 3. #1065 rides this merge — NOT optional, and this is why

`server.py:315` appends `CHANNEL_INSTRUCTIONS` on `settings.enabled`
alone — **this server's own env var** — while the comment above it
states the rule it fails to implement. The server **cannot** observe
whether the host accepts the channel: six gates away, and the ring is a
notification with no response, so sends and drops are the same path.

**The block has never reached a model because it sits past 2048**
(#1014). **This job makes it fit. So this job arms the defect** — every
channel-less session would begin being told it holds a lane it does
not.

Fix the claim, not the condition (the condition cannot be fixed —
acceptance is unobservable). Wording that matches the map and the canon
draft:

> *This server holds a doorbell open. Whether your host accepts it is a
> fact this server cannot see — the only proof is a wake arriving.*

**Read `CHANNEL_INSTRUCTIONS` end to end while you are there**; the
whole block is written in the indicative about a lane that may not
exist.

### 4. The CI guard — a condition of this job

    len(fragment_body) + len(CHANNEL_INSTRUCTIONS) <= 2048

**Red build, not a memo.** With the block at its ~230-char estimate the
spare is ~19 characters, which is not a plan. **Watch it fail on
purpose** before believing it (#112) — the whole defect class here is a
budget nobody was measuring.

### 5. Dropping the block entirely is the claimant's call

**The map is written to be sufficient without it.** Its WAKES paragraph
now carries the doorbell's universal truth *and* the watch's
obligation, leaving the block pure mechanics. Dropping it buys 249
characters of margin instead of 19.

**Either choice is fine; say which and why.** If it stays, item 3
applies to it in full.

## Deliverables

- Branch on `main`, proposed for merge, revisions entry, `R-NEXT`.
- The CI guard, watched failing.
- A FINDING closing the JOB, `closes` edge, and **`closes` on #702 and
  #1065** — both are retired by this change and neither should be left
  to a later sweep (#1035's rule, and #1038 is what it cost last time).
- State the final measured total: body + block against 2048.

## Conduct notes

- **Do not edit `charter.md`.** Canon amendments take the STAMP path
  (#882) and the operator's delegation covers the clients' context
  surfaces, not `/korax/canon`. The doorbell canon at #1063 is the
  seat's and rides its own path.
- **Merge is the deploy** for `clients/mcp/**` — WARN before, not after.
- **The fragment is the first thing every MCP band ever reads.** A
  mistake here is a mistake in every session that follows, and it will
  not announce itself.
