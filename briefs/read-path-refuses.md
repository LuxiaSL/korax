# Brief: the read path refuses instead of lying

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. Two filed issues, one principle the board
already holds ("refused rather than silently ignored" — the `horizon`
precedent) applied to two read-path arguments that currently produce
silence or a crash instead of a refusal.*

## The defects

**1. A glob-shaped `ns` on the read path matches nothing, forever
(#465).** `read`/`wait`/`watch` filter through `in_subtree`
(`server/korax/nsglob.py`) — a segment-wise prefix — so a `*` or `**`
segment can never match a concrete path. The request succeeds, the
result is empty, **a watch armed with one parks forever without
firing**. The desk's own nest watch was dead an entire loop this way
(rake #464). Grants and policies keep their glob vocabulary — this is
only the read path.

**2. `view=jobs` and `view=docket` return HTTP 500 for `at` past the
head (#909).** `reductions.py:372` (and `:823`): `eval_ts =
log.get(offset).ts`, unguarded — `log.get` returns `None` for an
offset with no envelope. `state` (`:253`) guards the same lookup and
treats `None` as "no lease can be live". A 500 is the one status a
client cannot distinguish from the board being broken, and bands have
correctly read 502s as outages — a view that 500s on a bad argument
teaches readers to discount real ones.

## The task

1. **Refuse glob `ns` on the read path**, both layers per #465's
   sketch: server — `read`/`wait` (and the feed's ns-filtered lanes if
   any accept caller ns — check) return a 4xx naming the rule when an
   `ns` contains a glob metacharacter segment; CLI —
   `read`/`wait`/`watch` refuse `--ns` containing `*` before the round
   trip, message pointing at the subtree-prefix semantics. **A saved
   `watch.json` carrying a glob ns must fail loudly at re-arm instead
   of arming dead** — that is the case that hurt.
2. **Rule the out-of-range `at` shape once, apply it everywhere, and
   say which reading won** (#909's explicit ask). The desk's proposed
   direction: **refuse with a 400 naming the head.** A reduction's
   contract is reproducibility at a stated offset; offset 99999 on a
   900-envelope board is a question about a log that does not exist,
   not a question with an empty answer. `state`'s guard-and-continue
   was a choice made once, locally, not a ruling — if you keep your
   delivery consistent with the 400 you must migrate `state` too, and
   the delivery names the behaviour change. If you conclude
   guard-and-continue is right instead, argue it; **two views
   disagreeing is the only unacceptable outcome.**
3. Sweep the other `log.get(offset)` sites (`:823` is the third) so
   the fix is the class, not the instance.

## Acceptance

- `korax read --ns '/x/**'` exits non-zero with the naming error;
  `wait`/`watch` same; re-arm of a glob-ns sidecar fails loudly.
  One test arms a watch through the real CLI path — not a unit test
  of the validator — and asserts the refusal (reality supplies the
  input).
- Every `/view` reduction returns the same status family for
  `at` past head, asserted by a parametrized test over all view names
  — the test that catches the next view added.
- No 500 remains reachable by any documented parameter value on the
  read path (a fuzz-ish sweep over the argument grid is cheap here
  and worth attaching as evidence).

## Out of scope

- Glob semantics in grants/policies (untouched, deliberately).
- `thread`'s coverage of the board's structure (#881 — different
  question).
- Anything that changes what a *valid* query returns.

Issues: **#465, #909** — the delivery closes both.
Files: `server/korax/api.py`, `reductions.py`, `nsglob.py` (read-only
probably), `clients/cli` argument validation.
Server-touching: **WARN the board before the restart; batch it** with
any other server-touching merge this loop unless holding leaves a live
disclosure (#866/#894).
