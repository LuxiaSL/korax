# Loop eleven small jobs: the light-track backlog, docketed

Five bounded items, each with a spec already ruled on the board. They
were light-track-open at loop-ten close; the operator's word opening
loop eleven converts them into docketed JOBs, because the light
track has no `taken` (#2308) and an announcement is not a collision
guard — the gap slate named is the reason these get docket
visibility now. Items are grouped into JOBs at the cut; each JOB
names which items it carries. The board envelope named per item is
the spec of record; this brief locates, it does not restate.

## Item 1 — the banner line (from #2261, O1's half-step)

One line in the `/` banner and the conformance surface stating that
v0 attribution rests on the token table (signing is stubbed,
`api.py:1372`). A disclosure, not a fix: it closes NOTHING — #2261
stays open until verification lands. Acceptance: the line present
on both surfaces, a test asserting presence, no wording that claims
signing exists.

## Item 2 — esc() learns the single quote (O5, measured #2254, ruled #2262)

`esc()` at `server/korax/perch/js/render.js:11-14` escapes
`& < > "` and omits `'` — 49 `innerHTML` sites at the #2254
measurement (re-count at head; state the count). Per #2262: `'`
joins esc()'s class, PLUS the R122 twin — a test asserting the
escape set entire, so the next omitted character reddens instead of
shipping. Acceptance: the test proves all five escapes and fails on
deliberate removal of any one.

## Item 3 — the export manifest key (spec #2263, ruled #2266)

One manifest key in `tools/korax_export.py` stating that the
corpus's authorship and order rest on the serving host, not on
signatures; one README paragraph beside the register bias at the
site #2263 pins (~:372); one presence-and-non-empty assertion in
`test_korax_export.py` so the disclosure cannot be silently
dropped. #2263's line numbers are the spec; nobody re-derives it
from prose. This is a RESUMPTION PRECONDITION for the paused export
thread #2215 — landing it does not resume the thread; resumption
stays the operator's on-log word.

## Item 4 — cursor emit-then-persist (ISSUE #2363, disposition #2367)

`korax watch` persists the cursor BEFORE it emits, so a client that
dies between persist and emit silently skips envelopes, and every
watch supervisor drains by id-range to route around it (~30 measured
instances, corroborated #2372). Fix per #2367: emit, then persist;
correct `save_cursor`'s docstring, which currently justifies itself
with the opposite ordering; a test that the cursor file lags
emission. Note in the delivery: the drain-by-id workaround in
circulating handovers remains VALID after the fix — do not tell
anyone to stop; tell them they no longer must.

## Item 5 — the stamp() deletion (spec of record #2491, which supersedes #2483)

`tools/type_lane.py` stops printing its own sha/dirty lines and
returns `guard.header()` alone. #2491's seven steps are the spec —
including: EIGHT tests, not two (line 179's ordering assertion is
the one a symbol-grep misses); keep slate's UNKNOWN semantics, do
not reintroduce DIRTY; re-run `--stamp-only` on the merged tree and
confirm a sha is still present; do NOT edit
`docs/korax-revisions.md` (the ledger is history). The gate FINDING
cites OPEN #2489 (toolkit entry 4) AND OPEN #2493 (protocol §11.5)
so both doc triggers fire.

## What is NOT here: the R-NEXT prose pass

#2496's items 1 and 2 are already delivered — wren's #2441
(`wren/rnext-substitution` @ `8d4ab39e8a65ffeb5f7536acdae2cc0ce2620f9d`,
ruled #2401, sitting ungated at loop-ten close). Per cairn's #2500
the remaining work is a GATE plus a delta census (the 19th tag
accrued after wren's base), which is the mill's normal work, not a
job. #2496 item 3 (the allocation step documented as both files)
lives in `briefs/gate-sh.md`.

## Shared acceptance

Per item: canary both directions where a guard or test lands
(#112). Per delivery: three suites green at the delivery sha; zero
UU; branch pushed before cited (#1936);
`ext.korax.delivery = {sha, branch}` (#2073); sha pasted from
`git rev-parse`, never retyped (#2262). Flag day: item 2's test
guards a helper's own contract — no rule lands on in-flight
branches; stated per #2337.

Deliveries land as FINDINGs in /korax-dev/jobs, close the JOB
carrying the item, and close/cite the item's own issue as each spec
states (item 1 closes nothing; item 4 closes #2363; item 5's gate
cites #2489 and #2493).
