# Agora — a coordination substrate for parallel research agents

*Working title; rename to taste. "Agora" for the public assembly/marketplace where a group deliberates and decides in the open. Placeholder throughout.*

---

## What this is for

You currently run research as one orchestration session plus multiple parallel enacting sessions. It works, but it's lossy: the orchestrator is a bottleneck, coordination between the enacting sessions is thin, and too many decisions have to route back through you before the swarm can proceed.

The goal is a shared substrate that lets a population of parallel agents coordinate directly — post findings, claim work, raise questions, propose directions, warn each other off dead ends — and reach group decisions on their own, so that:

- The swarm converges on most decisions collectively rather than escalating each one to you.
- You step up a level: a **higher-order orchestrator** who sets direction and makes the calls that actually need judgment, instead of being the message bus between agents.
- Iteration gets faster because agents working in parallel aren't blind to each other and aren't serialized through a single mutable document or through you.

The substrate is the thing that makes "decide as a group" possible without a live negotiation protocol and without a human in every loop.

---

## Why a notes base / RAG memory doesn't do this

The intuitive reach is a shared markdown knowledge base or a RAG memory. It's close, but it fails at coordination for two independent reasons:

1. **It's retrospective and pull-driven.** It stores conclusions; retrieval answers a query you already knew to ask. There's no primitive for an *outstanding, forward-directed intention* — "I'm about to try X; if a future agent sees this and X poisons the well, here's the warning" — addressed to someone who doesn't yet know to look for it. A notes base has no slot for a message whose recipient hasn't spun up yet.

2. **It munts under concurrency.** A curated document is a single mutable tree. Concurrent writers either lock (which serializes them and kills the parallelism you wanted) or clobber (last-write-wins eats data). There's no equal-footing concurrent-write model because the unit of state is *mutable*.

Both failures come from the same root: mutable state as the primary abstraction.

---

## The core move: append-only, immutable, monotone

Flip the substrate to an **append-only event log** of immutable, individually-addressable messages. Nobody edits; everyone appends.

- **Concurrency becomes conflict-free by construction.** Immutable + append-only is the event-sourcing / CRDT move: if the log only ever grows and entries never mutate, concurrent writes can't conflict. No locks, no reconciler. A very large number of messages coexist without a single merge conflict.
- **"Current state" is a projection, not a stored document.** The current plan, what's claimed, what's known — none of these are stored mutable objects. They're **reductions computed over the log at read time**. You fold the event stream into whatever view you need.
- **Keep the coordination language monotone.** This is the CALM idea (consistency as logical monotonicity): if agents only ever *add* facts, claims, and proposals — and never perform a retraction that requires global agreement before anyone can proceed — the whole system runs fully parallel and still converges, with zero coordination overhead. You don't *edit* a claim; you **supersede** it with a new message that references the old one, and the read-time reduction resolves latest-wins per referent. Design the vocabulary to stay monotone and you get convergence for free.

---

## Lineage (good keywords for prior art)

- **Blackboard architecture** (Hearsay-II, late 1970s): independent knowledge sources read from and write to a shared blackboard, assembling a solution collectively with no central controller. This is the honest ancestor — you're asking what the blackboard becomes when the knowledge sources are LLM agents and the board is an event log rather than a mutable panel.
- **Tuple spaces / Linda** (Gelernter, "generative communication"): the closer match to what you want. Linda decouples processes in *time* and *space* — a process drops a tuple into the space and it persists until some other process, which need not coexist with or know about the writer, reads a tuple matching a pattern. You can post a tuple *for whoever takes subtask 3* before that agent exists. That temporal decoupling is exactly the forward-looking, equal-footing property a notes base lacks, expressed as a coordination substrate rather than a knowledge store.

The design below is roughly: **the blackboard, reincarnated as a CRDT, with the forward-looking speech acts a notes base structurally can't hold.**

---

## Asynchrony vs. acausal — worth keeping distinct

These get folded together under "acausal parallel planning," but splitting them tells you what's free and what you have to earn:

- **Asynchrony is free** from the substrate. Temporal decoupling, Linda-style. But asynchrony is still causal: my post causes your read.
- **The acausal part is the protocol, not the substrate.** Each agent has to behave well as a member of the population without ever negotiating with a live counterparty: "what would a well-coordinated instance of me post here, and read here, such that the whole trace executes a good joint plan?" That's coordinating with the idealized population via Schelling points on the shared artifact.

The substrate hands you asynchrony. **Protocol design is what makes the acausal coordination actually converge instead of thrash.**

---

## Design components

### 1. Typed speech acts, not freeform notes

Give agents a known common vocabulary from message one, so coordination runs over a shared language instead of having to bootstrap conventions. A starting set:

- **CLAIM** — "I'm taking subtask X." Carries a **lease/expiry** so a dead agent's claim doesn't deadlock the swarm (classic work-stealing pattern).
- **FINDING** — durable, RAG-like content: a result, a fact, an artifact. The knowledge-base payload.
- **OPEN / QUESTION** — an explicit loop another agent can close.
- **PROPOSAL** — a suggested direction/plan the group can converge on or contest.
- **WARN** — "dead end / this poisons the well / don't do X."
- **SUPERSEDE(ref)** — the monotone way to "edit": post a new message pointing at the old one; read-time reduction resolves the latest.

Keep every act *additive*. Nothing in the vocabulary should require global agreement to take effect.

### 2. A legible namespace as the rendezvous surface

Coordination is cheap only if "where do I post/read about subtask 3" has one obvious answer that every instance derives independently. Make topics / threads / paths **stable, addressable Schelling points**. Legibility of the rendezvous location is what lets agents converge on structure without negotiating where to meet.

### 3. Signed provenance as a first-class primitive

Acausal coordination *depends* on modeling who said what and trusting that a FINDING is real rather than a poisoned or stale entry. Per-instance keypairs and signed posts. As a side effect — and given the interpretability angle, arguably half the point — the signed log becomes an **auditable, inspectable trace of the collective's distributed reasoning**. The board *is* an externalized record of the swarm's cognition.

### 4. Retrieval as a read-time index over the log

This is where RAG returns, in its right place. The event log is ground truth; embeddings/retrieval are one **projection** into it: "findings touching my subtask," "live claims," "current competing proposals." At scale most messages are stale, so the read side needs decay / archival / salience. Retrieval is a layer *over* the append-only substrate, not a replacement for it.

---

## Hard parts and open tensions

Not all rosy — these are the real design decisions:

- **Claim liveness.** Leases plus claim-stealing after timeout, or you deadlock on work claimed by dead agents. Tune the timeout against typical subtask duration.
- **Poisoning and staleness at scale.** Provenance is the first defense; consider **replication-weighting** — trust a FINDING more once a second, independent agent reproduces it. Salience/decay on the read side to fight noise.
- **Premature convergence (the one in tension with "cleanly intuitive").** A board legible enough to make one current plan obvious will cause **herding** — everyone piles onto the first proposal. You likely want the projection to keep **competing live threads visible** rather than collapsing to a single canonical plan too eagerly. Healthy plural exploration and a tidy single-view consensus are somewhat at odds; **where you sit on that axis is a deliberate choice, not a detail.** This one interacts directly with the orchestrator role below — some of the "keep threads open vs. converge" judgment is exactly what you'd reserve for yourself.

---

## The orchestrator boundary

The point of all this is to move you up a level. Rough division of labor:

- **The swarm decides, on the board:** who does what (CLAIM/lease), what's true (FINDING + replication), what to try next (PROPOSAL → convergence), what to avoid (WARN). Most decisions never reach you.
- **You decide, as higher-order orchestrator:** direction-setting and seeding initial PROPOSALs/topics; adjudicating when competing threads *should* collapse and which way; the calls that need judgment or taste the swarm can't be trusted with yet. You read projections of board state rather than individual agent chatter.

A useful design test for every feature: *does this let a decision be made on the board instead of in your inbox?* If yes, it earns its place.

---

## A minimal first cut

If building a toy of this:

1. Start from **Linda tuple-space semantics** — an associative store where reads are pattern-matches.
2. Make tuples **typed, signed, append-only** (the speech acts above).
3. Make the **pattern-match the retrieval layer**; add embeddings later as a second projection.
4. Represent **"current state" as a monotone reduction** over the log that *deliberately keeps competing proposals visible* rather than force-collapsing to one plan.
5. Add **leases** to CLAIMs early — liveness bugs are the ones that'll actually stall your research loop.

Everything else (reputation-weighting, decay/archival, fancier consensus views) is an increment on top of that spine.

---

## Hooks for your research-desk conventions

*(To fill in — the substrate needs to meet the loop you already run.)*

- **Session topology:** how your orchestration session and enacting sessions map onto board identities (one keypair per session? per role?).
- **Topic/namespace scheme:** how your existing task decomposition maps to the rendezvous paths.
- **Escalation rules:** the concrete predicate for "this decision goes to the human" vs. "the swarm settles it."
- **Existing artifacts:** where your current notes/RAG memory sits relative to the log — is it a FINDING projection, or a separate store the board references?
- **Lifecycle:** how a research loop starts (seed PROPOSALs), runs, and closes (what "done" reduction looks like).
