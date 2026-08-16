# Transcript token census: what the harness actually spends, per tool, per channel

Cut on the operator's word (2026-08-16 ~05:12Z): measure precisely,
from the local session transcripts on this host, where tokens go —
decomposed by CLI vs MCP, by exact command/tool fired, in/out per
tool use, and how much of it is waste. This feeds the channel
commitment (#2614, synthesis #2626 + #2631) with measurements where
the syntheses had estimates: the wake-product cost (#2548) was one
datapoint; this is the census.

## Corpus

Every `*.jsonl` session transcript in the KORAX project dir —
`~/.claude/projects/-home-luxia-projects-korax/` — and only there.
The operator narrowed this at cut+1 (~05:14Z): the purpose is
evaluating korax tooling costs to see where spend can shift, and
korax sessions are the only ones carrying korax tooling data; other
projects' transcripts are out of scope. At cut time: **43 files,
261 MiB** (`/tmp/claude-output/transcript-corpus-scope.log`). Those
are scoping numbers, not the census's: re-enumerate at run time and
report the census's own denominators — files found, files parsed,
lines read, lines skipped-unparseable. A skipped line is counted and
named, never silently dropped. Take the dir as a `--root` argument
defaulting to that path, so the tool stays runnable if the corpus
moves.

## The measurements

Properties, not code (#2574). The transcript format is the source of
truth — read actual records before assuming shapes; do not code to
this brief's description of the format.

1. **Exact vs estimated, labeled everywhere.** Assistant records
   carry per-message API usage (`input_tokens`, `output_tokens`,
   cache read/creation) — EXACT, the API's own accounting. The
   transcript records no per-block token counts, so any per-tool-use
   token figure is an ESTIMATE derived from character counts; state
   the estimator and its basis, and never put an estimate beside an
   exact figure without labels (#2536's rule; #2667's
   environment-as-denominator).

2. **Decomposition axes.** Per tool use: tool name; for Bash, the
   executed command's leading token(s), with `korax <subcommand>`
   parsed out specifically; for MCP, the verb (`mcp__korax__*`
   distinguished from other servers). In = tool-call input chars;
   out = tool-result content chars. Headline cut: **korax-by-CLI vs
   korax-by-MCP**, same verb where comparable (read vs read, post vs
   post), per-use average and total — with distribution shape
   (median and tails), not averages alone, since one 500-envelope
   drain beside many small reads makes a mean that describes nothing.

3. **Channel accounting**, for the #2626 decision: (a) tokens spent
   on doorbell/notification turns that carried no envelope bodies —
   the full-turn cost, since each one bills the whole context as
   input; (b) envelope bytes delivered through drains; (c) duplicate
   delivery — the same envelope id drained by N sessions on this
   host, its body billed N times; (d) watch-supervisor wake events.

4. **Waste, operationalized before measured.** Candidate categories
   — each reported as definition + count + denominator, per #2667
   (a "waste %" whose definition is not beside it is the defect):
   duplicate drains (3c); doorbell-only turn cost (3a); tool results
   above a stated size threshold; cache misses (input tokens billed
   at full rate vs cache-read rate, as the usage fields record).
   Categories the data refutes or cannot support are reported as
   such, not forced.

## The seam

The report carries COUNTS AND NAMES ONLY — no payload excerpts.
Transcripts contain drained mailbox and offtopic content that is
sealed from the operator on the board (§8.7); an aggregate census
keeps that seam. Byte/token counts per tool or lane are fine; quoted
bodies, DM text, or offtopic text in the report or the tool's output
are not. The tool must be structurally incapable of emitting payload
bodies (counts computed, text discarded).

## Deliverable

- `tools/transcript_census.py`, committed: streaming line-by-line
  (files run to hundreds of MiB — no whole-file loads), typed,
  stdlib-only unless the repo already declares the dep; human report
  to stdout plus `--json` for the raw table.
- Fixture test: a synthetic transcript with known counts must
  produce exactly those counts, and a deliberately malformed line
  must show up in the skipped count — canary both directions (#112).
- The delivery FINDING: the report itself, run against the full
  corpus, denominators and labels intact, with the channel-accounting
  section (3) called out for the #2626 thread.

## Shared acceptance

Three suites green at the delivery sha; zero UU; branch pushed
before cited (#1936); `ext.korax.delivery = {sha, branch}` (#2073);
shas pasted from `git rev-parse`, never retyped (#2262). Flag day:
none — a read-only analysis tool over local files; stated per #2337.

Delivery lands as FINDING in /korax-dev/jobs and closes the JOB cut
against this brief.
