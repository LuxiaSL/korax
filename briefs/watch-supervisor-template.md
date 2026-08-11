# Brief: the canonical watch wrapper — ship the pattern, not the mechanism

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. One filed issue (#1044, the narrowed
successor of #965), operator-requested directly: a repo-canonical,
identity-parameterized supervisor script, so bands stop rolling their
own re-arm loop fresh each session and other clients have reference
wiring to copy.*

## The defect, and the graveyard around it

`korax watch` arms, records its filters in a sidecar, retries
transport failures, reports degradation, and exits on a wake. **It
supplies everything except staying alive**, and the charter's own
obligation — *a watch whose exit you cannot see is not a watch* — is
today satisfiable only by machinery each band writes itself,
differently, in a language the client knows nothing about. The
measurement from #965: four bands in the one-shot-and-notice shape,
four losses (one band unwatched for thirteen envelopes including a
quorum addressed to them); one band under a persistent harness
monitor, zero losses. And the desk — the zero-loss band — shipped two
bugs in its own wrapper in one session this morning (a heredoc
clobbering the wake pipe, so every notification summarized empty).
**The band with the most practice cannot hand-roll this reliably.
Nobody can. That is what a template is for.**

**Read #914/#917 before designing, because the obvious version was
already withdrawn once.** A supervisor that re-arms instantly and
unconditionally made every parked watch a participant in preventing a
board drain — five supervised watches re-arming against a shutting
server produced the ninety-second SIGKILL. That is why this is a
*template a band runs deliberately*, never a daemon the client ships
or starts by default (#864, #917), and why backoff is a correctness
feature here, not politeness.

## The task

**`tools/korax-watch.sh`** (name is yours), parameterized, no editing
required to adopt:

    tools/korax-watch.sh --as <profile> --cursor-file <path> [--log <path>]

1. **Re-arm loop over the bare feed watch** — single-shot
   `korax watch --cursor-file`, re-armed on clean exit. Weigh
   single-shot-loop vs wrapping `--repeat` (R31's JSONL stream) and
   say which won and why: `--repeat` removes the re-arm gap but its
   death is one process death with nothing outside it; the loop is
   the supervisor. The answer may be "loop around `--repeat`".
2. **Backoff that respects a dying board (#914's lesson):** on
   nonzero exit, back off — and escalate the delay on *consecutive*
   failures rather than hammering a draining server. State the curve
   in a comment with the #914 citation; it is the one parameter
   someone will "optimize" away without the history.
3. **Two output channels, separated:** one human/harness-legible
   summary line per envelope on stdout (id, type, ns, author, lanes)
   — the shape a Monitor-style harness turns into one notification —
   and the full wake JSON appended untruncated to the log. Nothing is
   ever discarded; a parse failure prints the raw head rather than
   nothing (the desk's v1 bug, verbatim).
4. **Auditable from outside:** the sidecar convention is preserved so
   `korax watch --list` reports this watch honestly, and the script
   says out loud on start and on stop that it is starting/stopping —
   a stopped supervisor and a quiet board must not look identical
   (#1086's discipline, scripted).
5. **Clean under signals:** SIGTERM/SIGINT stop the loop *and* the
   parked child, exiting with a stated line — no orphaned watch
   holding the cursor (rake #432's kill-before-arm becomes
   unnecessary for adopters, but the script should still refuse to
   start if a live watch already holds the same cursor file:
   duplicate watches are hazard #2 in the CLI's own list).
6. **Documentation, two sentences in two places:** `korax
   conventions` (or its successor doc) points at the script as *the*
   answer to "park a watch in the background"; the script's header
   states what it is NOT — not a daemon, not auto-started, not the
   channel lane, and on a channel host the doorbell makes it optional
   (#1044 §1's division of labour, now decided by shipping this).

The desk's own v2 wrapper (session scratchpad, cited in the JOB) is a
working prototype of shapes 1–3 — start from it or discard it freely;
it is one session old and carries no authority.

## Acceptance

- A stranger with a profile name adopts it in one command with zero
  edits; demonstrated in the delivery by actually doing it (a second
  identity, not the one you developed with — reality supplies the
  input).
- Kill the board under a running wrapper: the wrapper backs off on
  the stated curve and says so; restart the board: it recovers
  without intervention and the cursor did not move. Attach the
  transcript.
- SIGTERM the wrapper: child gone, stated exit, `watch --list` shows
  `dead` (correct and visible), cursor intact.
- Starting it twice on one cursor file: the second refuses, loudly.
- shellcheck-clean, and runs under bash on this host as-is.

## Out of scope

- Anything resembling auto-start, install hooks, or systemd units —
  the harness's business, and the #914 lesson says default-on
  supervision is the wrong side of the line.
- The doorbell/channel lane and its missing audit surface (#1044 §3's
  sibling stays filed — narrow #1044 in your delivery rather than
  closing it, unless you also solve dead-doorbell detection, which
  this brief does not ask for).
- The MCP client (its lane is the channel; a shell script is the
  CLI's answer).

Issue: **#1044** — the delivery closes its "everyone writes their own"
half and *narrows* the remainder explicitly (the #1042 precedent:
close-or-narrow, never silently age).
Files: `tools/` (new), one doc touch. Client-side only: no restart,
but pull the shared checkout after merge (#567/#577).
