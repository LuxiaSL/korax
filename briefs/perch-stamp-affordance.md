# Brief: the perch can stamp anything a human may stamp

*A JOB brief — sha-pin this file at a commit when posting the JOB.
Drafted by quill (band:2887f5287fd2) at the operator's request, from
issue **#606** and the operator's ruling **#610**. The requirements
document is #606; this adds what reading the source settled and what a
design gate should still rule.*

## The gap (#606, confirmed from the source)

`server/korax/perch.html` writes exactly one STAMP, from exactly one
place:

- `:650-668` `loadRatifications()` — scans **POLICY** envelopes below
  human band with no human STAMP inbound (§8.5) and renders a button
  per pending policy. That is the perch's entire stamp surface.
- `:672-678` `stampPolicy(id, ns)` — the only writer of a STAMP act in
  the file.

So the one governance path that **mandates** a human stamp has no
interface path at all. A PROPOSAL awaiting canon ratification (§8.6
`stamp_required`), an OPEN requesting a stamp, a FINDING — none can
grow a button, because the sweep that builds buttons only looks at
POLICY. **The interface enforces a rule it cannot help satisfy.**

The operator's ruling: *"we want to get me the ability to stamp from
the UI"* (#610). Wanted before the next working loop opens, because
the canon path is blocked behind it.

## What the source already gives you

**`stampPolicy(id, ns)` is already generic.** It posts
`{type: "STAMP", refs: [{edge: "stamps", id}], ns}` and nothing in it
is POLICY-specific. The writer needs no change; only the surfaces that
*offer* it. Rename it (`stamp(id, ns)`) rather than adding a second
writer — two writers of the same act is the drift this board keeps
filing rakes about.

**`stamps` has no target constraint.** The board's own `edge_rules`
serves `stamps: {sources: ["STAMP"]}` — a source rule and no target
rule. Any envelope can be stamped; §4.3 restricts the *act* to human
band, server-side, and that restriction is the real gate.

## What to build

**1. A generic stamp affordance on the envelope view.** `tab-envelope`
already renders any envelope through `envCard(e, extra)` and the
`extra` slot exists. Put the button there. This is the primitive: it
works for every stampable target, present and future, without an
enumeration to maintain.

**2. An ergonomic path from the inbox**, where the operator actually
is. `loadInbox()` renders each OPEN with `contextBlock()`; an OPEN that
requests a stamp carries a ref to its target. Offer *"stamp the
referent"* there so the common case — read the request, grant it — does
not require copying an id into another tab.

Both call the one writer.

**3. Do not offer a stamp that already exists.** `loadRatifications()`
already does this check (`/read?to=<id>&type=STAMP`, look for a human
band). Reuse it. Showing the existing stamp instead of a second button
is the correct rendering, and double-stamping should not be one click
away.

**4. Keep the §8.5 pending-policies sweep exactly as it is.** It is
correct for its case. This adds a surface; it replaces nothing.

## Shape questions for the design gate

1. **How is "human band" decided client-side?** `/whoami` returns
   grants, not a band, and band is per-namespace. The button can be
   hidden unless a `human` grant covers the target's ns — but **the
   client's derivation must never be the gate**. The server refuses a
   non-human STAMP (§4.3) and that refusal is the security boundary;
   hiding is ergonomics. Rule explicitly which is which, so the next
   reader does not mistake a hidden button for an enforced rule.
2. **Self-stamping.** The `:657` skip (`if (e.band === "human")
   continue`) is correct for the pending-policies sweep and stays. On
   the generic envelope view the operator will inevitably open
   something they posted: does the button render disabled with the
   §8.5 reason, or not render at all? Recommend **disabled with the
   reason** — an absent button and a forbidden one look identical, and
   this board has spent a loop filing that failure.
3. **Enumerate stampable types, or offer generically and let the
   server rule?** Recommend **generically**. An allow-list in the perch
   is a second source of truth for §8.6, and it will drift from the
   validator exactly the way `edge_rules` drifted from its own
   constraints (#511/#519).

## Testing, and be honest about what is reachable

**`perch.html` has one test: `test_perch_is_served_at_root` asserts the
response contains the string "perch".** There is no JS test
infrastructure in this repo and **this job should not build it.**

What is cheaply guardable, and what each guard is worth:

- **The contract the button depends on, server-side and real:** a STAMP
  authored by a human band, carrying `stamps: <id>`, into the target's
  ns, is accepted for a **PROPOSAL** target — and refused from a
  non-human band. If that already holds in `server/tests`, cite it; if
  it holds only for POLICY targets, extend it. **This is the assertion
  that matters**, because it is the one the affordance rests on.
- **A smoke check that the affordance exists in the served HTML.** Say
  out loud in the test's docstring that this is #111's shape — prose
  describing a mechanism — and that it catches deletion, not
  correctness. A weak guard named honestly beats a weak guard mistaken
  for a strong one.

Per rake #112, whatever guard ships gets broken once on purpose before
delivery, and per #701, **commit before you mutate**.

## Deliverables

Design FINDING (PROPOSAL for the edge, so the desk can endorse it),
then: the envelope-view affordance, the inbox path, the already-stamped
check, the server-side contract test, the smoke check, a revisions
entry, and — if the design gate agrees — the `stampPolicy` → `stamp`
rename in the same commit.

## Scope fence

`server/korax/perch.html` and `server/tests/**`. **No protocol change,
no new endpoint, no change to who may stamp** — §4.3 already decides
that and this job must not restate it client-side as though it were
deciding it.

**A note on the split:** `perch.html` lives in `server/`, which is
slate's half of the standing split, while the perch itself is the
operator's client. Quill flagged this rather than assuming it, having
mis-stated it once already (#615 called it "squarely this band's
surface"; it is not, by tree). **The desk assigns.**
