# Brief: the thread opens in place — inline expansion in the conversation view

JOB for the operator's ask (off-board, with screenshot, 2026-08-11
~23:15Z): in the envelope page's conversation/neighbourhood walk,
clicking a related node should open that envelope's full card
DIRECTLY BENEATH the one currently open — a proper thread/board
visualization — instead of round-tripping its id through the fetch
box and losing the walk.

## Deliverables

1. Each node card in the conversation walk (one hop / 2 hops / …)
   gains an expand affordance: click → fetch → the full envelope card
   renders inline beneath the node row, collapse on second click.
   The walk's structure (hop grouping, edge labels, the withheld/
   sealed counters) stays visible around expanded cards — expansion
   adds depth, never replaces context.
2. Expanded cards carry the same affordances a fetched envelope has
   (its own conversation link at minimum; full recursion is the
   builder's call — if depth is capped, the cap is visible, not
   silent, per the counters' own convention).
3. Repeated expands reuse fetched envelopes (the registry-cache
   pattern already in plumbing) — no re-fetch per click of the same
   id.

## Constraints

Perch-only: merge is the deploy, no restart, no WARN. §9.3 untouched
— expansion renders what the requester could already fetch by id;
sealed refs keep rendering as withheld, exactly as the walk does
today. The smoke suite (#1615, in build) will click this too once it
exists; until then the delivery names what it hand-verified.

## Notes for the gate

Client-side rendering only, no server leg. Closes no ISSUE; derives
from the operator's ask as recorded in this brief.
