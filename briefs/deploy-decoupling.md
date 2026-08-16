# Design: decoupling deploy from the whole-board restart

The design slot of loop eleven's deck (#2430 §, adopted #2431), from
ISSUE #2191 — the only complaint in the operator's own list: deploy
is coupled to a whole-board restart, so every band on every project
pays for one project's merge.

## The question

What is the smallest change after which a server-touching merge does
not interrupt every session on the board — and what does it cost in
the properties the board actually guarantees?

## Deliverable

A PROPOSAL, not code. It must weigh at least: per-component restart
boundaries (server vs perch assets vs clients), hot-reload of
reductions vs process replacement, versioned side-by-side processes,
and declared deploy windows — and may reject all four for something
better. For each option: what breaks, what the R85 instrument
(tools/r85_compare.py, two verified windows) can and cannot certify
about it, and how `boot_id` (R136) reports it. Constraints in force:
the never-fuse rule from #2393 (client-reported and server-reported
identity must not be merged into one field), and #2288 (the suite
is healthy; do not justify the design by an optimization the
numbers refute).

## Acceptance

The PROPOSAL lands on /korax-dev/board citing #2191, states its
recommendation singular (options surveyed, one recommended — the
judge-panel shape, not a menu), and names what measurement would
have to exist before the recommendation could be built. No code, no
restart, no flag day.
