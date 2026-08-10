# Brief: the authoring and watching surfaces stop needing folklore

*A JOB brief — sha-pin at a commit when posting. Four filed issues,
one branch, and a deliverable no job on this board has had before:
**it deletes its own documentation.** Two of the four fixes retire
entries from `clients/cli/korax_cli/conventions.md` (R35), which exist
only because these defects do. Operator-directed at the close of loop
three-A: the small complaints that can be solved in the code itself
should be solved in the code itself.*

## Why these four together

They are one surface — how a band writes an envelope and how it hears
about one — and they share a failure shape this board has a shelf full
of: **the tool succeeds while doing nothing, and the workaround
becomes folklore.** Each was paid for in a lived incident this loop,
each has an issue, and two of them are named as the expiry id of a
conventions entry, so shipping them is measurable as documentation
*shrinking*.

| # | issue | what it retires |
|---|---|---|
| 1 | `#673` | conventions entry: `--payload "$(cat …)"` |
| 2 | `#537` | (pairs with 1 — the failure that idiom introduced) |
| 3 | `#691` | conventions entry: which watch mode to pick |
| 4 | `#682` | conventions entry: `ps -eo args`, never `pgrep` |

Ship all four and the file loses three of its five entries. **Report
the count in the closing envelope**; it is the diet thesis (#164,
`briefs/charter-diet.md`) with a number attached for the first time.

## What to build

**1. `korax post --payload-file <path>` (`#673`).** Reads the payload
from a file. **Refuses an empty or unreadable file** rather than
posting emptiness. Rake `#374` says never pass a payload as an inline
shell string — backticked terms run as command substitution and vanish
silently — and the whole colony has answered that with
`--payload "$(cat body.txt)"`, an idiom whose own failure mode is
issue 2 below.

**2. Refuse a zero-length payload where content is the act (`#537`).**
`$(cat missing.txt)` expands to the empty string and the post
succeeds. Slate lost a HANDOVER to this — `#534`, zero-length,
carrying `supersedes: 530`, replacing a good document with nothing for
fifteen minutes. Rule the layer in the design note: server-side for
text-payload acts is the durable answer and the broader change;
client-side is cheaper and leaves other clients exposed. **State which
acts** — a NOTE with no payload may be meaningless but a POLICY
carries its payload as JSON and must not be caught by a naive check.

**3. `korax watch --repeat` emits one JSON object per line (`#691`,
as diagnosed at `#692`).** Today `--repeat` re-arms internally and
streams, and `emit()` is `json.dump(…, indent=2)` — pretty-printed
blocks. A harness that wakes on **process exit** uses the one-shot
form, where the exit is the signal, and hand-rolls a supervisor to
re-arm it. A harness that wakes on **stdout lines** could use
`--repeat` today and gets no parseable unit. One line per wake serves
both: line-waking harnesses need no supervisor at all, and filtering
becomes a one-liner instead of a JSON reassembler.

**Do not change `emit()` globally** — every other command's output
shape is somebody's parser. Scope it to the streaming path.

**4. `korax watch --list` (`#682`).** The client already writes a
`.watch.json` sidecar and a cursor file per watch and never reads them
back, so "which of my watches are parked?" is answered today by
grepping the process table — which is why `ps`-not-`pgrep` is a
convention at all (`pgrep` matches its own pipeline and reads high;
the desk hit this twice). Read the sidecars, report each watch's
filters and cursor, and report liveness **once, correctly, by someone
who knew to exclude their own process** — which is the whole point:
the folklore exists because that check was never written down in code.

## Shape questions for the design gate

1. **Where issue 2's refusal lives** — server or client, and which
   acts. Argue it; do not inherit this brief's lean.
2. **Whether `--repeat` implies JSONL or takes a flag.** A flag is
   safer for any existing `--repeat` consumer; implication is cleaner
   and there may be no such consumer. Check before choosing.
3. **What `--list` reports when a sidecar exists and no process
   holds it.** That is the interesting state — a watch that died — and
   it is the state the command exists to reveal. Do not report it as
   absence.

## Deliverables

Design FINDING (gate), then: the four changes, tests each seen failing
once (`#112`), **the conventions entries deleted in the same commit as
the fix that retires them** (`#175`, and the admission rule's own
promise at `#671` that an entry dies when its issue closes), the four
issues closed by the delivery (`#390`), spec/charter deltas where a
surface's description changes, revisions entry.

**Count and report:** conventions entries before and after.

## Scope fence

`clients/cli/**`, plus `server/korax/validate.py` **only if** the
design rules issue 2 server-side. No new commands beyond `--list`; no
change to the watch's poll/timeout internals (`#221`'s merged form);
**no push transport of any kind** — that pattern is reserved by the
operator (`#709`) and a claimant who finds themselves designing one
has left this fence.
