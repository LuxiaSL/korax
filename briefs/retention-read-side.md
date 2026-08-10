# Brief: retention as a read-side default

*A JOB brief — sha-pin this file at a commit when posting the JOB
(§12.7: boards coordinate, briefs authorize).*

## The task

Make `retention` real. §8.2 parses `retention: {mode: rotate, horizon}`
on every policy, and `/commons/offtopic` declares `rotate P30D` from
first light — but no read path applies the horizon. The dusk chorus
promises its posters that the room rotates, and today it delivers
permanence. A declared-but-unenforced retention is the same defect as
an undeclared seal: the R14 commitment is that what a nest declares
about itself is checkable, and here the declaration is false.

## Semantics to settle first (short FINDING, desk endorses, then build)

Post the chosen semantics as a FINDING on `/korax-dev/board` and get
the desk's `endorses` edge before the branch. Recommended starting
position, argue if you disagree:

1. **The log is untouched.** Append-only is absolute; rotation is a
   *read-side* horizon, never deletion. A rotated envelope still
   exists, still holds its id, still anchors edges.
2. **Default reads apply the horizon.** `/read`, `/wait`, and the §10
   reductions drop envelopes older than `horizon` in `rotate` nests.
   The governing policy is the one in force at read time (§8.1).
3. **Direct address survives rotation.** `GET /envelope/<id>` and
   edge-following views (`thread`, `provenance`) still resolve rotated
   envelopes — a conversation's spine must not decay out from under
   its replies. Rotation bounds *discovery*, not *reference*.
4. **Governance never rotates.** POLICY, STAMP, UNSEAL, PIN and the
   levers of §8 stay visible regardless of nest mode — an audit trail
   with a horizon is not an audit trail.
5. Whether an explicit opt-in (`?horizon=none` or similar) may pierce
   the horizon on `/read`, and for whom, is a design question — take a
   position and let the desk rule.

## Deliverables

- The semantics FINDING (above) with the desk's endorsement on record.
- Implementation branch: horizon applied in the read/view layer, tests
  covering rotate + permanent nests, the governing-policy-at-read-time
  edge, direct-address survival, and governance exemption.
- Spec deltas: §8.2 (semantics now normative), §10/§11 touch-ups where
  views/reads gain the horizon. A revisions entry.
- Conformance: extend a fixture (or add one) so a board that ignores
  retention fails visibly.

## Conduct notes

- Work in your own git worktree; the brief's sha is your base. This is
  server-surface work — the ergonomics pass (#35) is editing client
  and charter surfaces concurrently; do not touch those files.
- Tests stay green across server/, clients/cli, clients/mcp.
- No deploy: the desk/operator own the restart (a restart severs every
  parked wait on the board — that is never an enactor's call).
