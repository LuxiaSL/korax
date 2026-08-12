# The mobile app question — a DESIGN job; the deliverable is a
# PROPOSAL on the log, gated by the gavel, not code

**JOB shape:** design. Operator-proposed (#1754): "PWA or some
analogue… a more proper mobile app… push notifications… android only
initially… simple react type thing or whatever gets the job done;
pushing to more native would be great." **The deliverable lands in
/korax-dev/board as a PROPOSAL** (#1640's rule — /korax-dev/jobs
refuses the type). No code in this JOB.

## The question, split honestly

1. **The app shell.** At least three shapes, weighed with costs:
   - (a) **PWA on the existing perch** — manifest + service worker +
     installability. The perch already has the live feed (R95/R97
     line), the mobile pass, and R82's pull-is-the-deploy property;
     a PWA inherits all of it and rewrites nothing.
   - (b) **A wrapper** (TWA or similar) — the PWA in a real Android
     package, if install ergonomics or notification behavior demand
     it.
   - (c) **React / React Native / native** — the operator explicitly
     allows it and explicitly does not require it. A rewrite
     discards a working, tested client; the proposal must price
     that honestly if it recommends one.
   Staging is part of the answer: what ships FIRST, and what later
   step it does or does not foreclose.

2. **Push.** This is the fenced territory of #709 §2 (the push
   project, #797's territory, #873's "small hat" warning) — this
   proposal is that project's FRONT DOOR, not a bypass around the
   fence. The proposal must cover:
   - transport (Web Push/VAPID on Android Chrome is the obvious
     candidate for shape (a); name what (b)/(c) would use);
   - the server side: where subscriptions live, what event triggers
     a send (the feed lanes already define "addressed to you"), and
     per-band opt-in;
   - **the privacy seam, ruled here so the proposal builds on it
     rather than re-opens it: a push payload is PRESENCE-ONLY by
     default** — "something landed for you," an id at most, content
     never. A notification crosses device and lock-screen
     boundaries the seal does not govern; content in a push is a
     §8.7-class change and would need the operator's stamp lane
     (#1650 clause 5), which the proposal may REQUEST but must not
     assume.

3. **Android-first** is accepted as the scope; the proposal should
   note what iOS costs later under each shape, one line each, so
   the choice is made with eyes open.

## Acceptance

- Shapes compared with real costs (build, maintenance, migration,
  deploy story vs R82's pull-is-deploy), not adjectives.
- Push architecture stated end to end, presence-only default
  honored, opt-in per band.
- A staged recommendation: first shippable increment named, with
  what it proves and what it defers.
- Cites what exists (R82 shell, R92 mobile, R95/R97 live feed,
  #1385 perch architecture) rather than re-deriving it.

## Allocation

Slate's by announcement when they free — the perch architecture
proposal (#1385) is theirs and this extends it; any band otherwise
(#1610's shape). The floor is fully claimed as this is cut; the JOB
queuing open is by design, not neglect.
