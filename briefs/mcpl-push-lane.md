# Brief: the MCPL push lane — make the doorbell ring on a host that can hear it

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Requirements: **`briefs/connectome-pilot.md`** (the seat moves; line 105
expects MCPL push to "arrive natively" and says measure it rather than
assume it), **#995/#997/#991** (the doorbell as shipped, and the
one-declaration finding), **#2626/#2631** (the wake-channel target),
**#2875** (the watch-vs-push measurement quill and slate owe),
**#171** (the rake: no wake and a quiet board are the same nothing).
Read the connectome-pilot brief first — this job exists because one of
its expectations is false.*

**The doorbell we shipped speaks a language the new host does not
route. This job teaches it the second language, in ~200 lines, against
a seam we already built and already test.**

## Provenance of the analysis below

Read off both trees by an operator-side Claude Code session on
2026-08-16, at these commits:

| tree | sha |
|---|---|
| korax | `fa49613` |
| agent-framework | `ae1d4d5` |
| mcpl (spec) | `5d1adeb` |
| heartbeat-mcpl | `3c96537` |
| connectome-host | `61d724a` |

**Evidence: `source-checked`.** Every claim below was read out of the
named file at the named line. **Nothing here was executed** — no wake
was demonstrated end to end, and the one runtime claim that matters is
flagged as unproven where it appears. Grade it accordingly.

## The defect

`korax_mcp/channel.py` declares **`claude/channel`** — Claude Code's
push lane. The connectome host does not route that method and never
has. Its complete inbound dispatch table is
`agent-framework/src/mcpl/server-connection.ts:937-959`
(`METHOD_TO_EVENT`); the only push method in it is MCPL's
**`push/event`**, gated on the `pushEvents` capability at
`:978-986` (`METHOD_TO_REQUIRED_CAPABILITY`). There is no
`claude/channel` string anywhere in the framework.

So on the pilot host the doorbell starts, declares a capability nobody
reads, polls the board correctly, and rings into a void. **That is
#171 exactly** — and worse than the old failure, because the seat has
a doorbell in its recipe and will reasonably believe it works.

Two consequences for the pilot as briefed:

- **`connectome-pilot.md` line 105 is wrong.** Push does not arrive
  natively for transferred seats. It arrives when we write it.
- **The seat's request for a permissive EventGate "on all board lanes"
  has nothing to gate.** Day one there are zero board-originated
  wakes; heartbeat is the only board wake path that exists.

## The measurement: the port is small, and mostly already built

**The wire surface is trivial.** `push/event` is SPEC §9.1
(`mcpl/SPEC.md:832-900`) — four required fields: `featureSet`,
`eventId`, `timestamp`, `payload.content`. The prerequisites are
advertising `experimental.mcpl { version, pushEvents: true,
featureSets: {…} }` (§5.1, `SPEC.md:192-237`) and answering the host's
`featureSets/update` Request with a degradation receipt (§5.3,
`SPEC.md:263-307`). Everything heavy in MCPL — context hooks,
inference lifecycle, channels, state management, manifest changes — is
optional. Advertise nothing, implement nothing.

**Three things then fall our way, and they are the reason this is a
small job rather than a rewrite:**

1. **The declaration seam exists and is already parameterized.**
   `declare_channel_capability(server, capabilities=None)` —
   `clients/mcp/korax_mcp/channel.py:125`. Declaring `experimental.mcpl`
   is *passing a different dict to a function we already have*. The
   FastMCP `_lowlevel_server` reach-in, the thing #987 agonized over,
   is done, guarded by `check_capability_seam()` (`channel.py:81`), and
   fails RED via `tests/test_channel_seam.py`. **The ugliest part of
   this job was paid for by #995.**

2. **The notifier seam exists.** `connection_notifier()`
   (`channel.py:175`) hands back a raw `connection.notify(method,
   params)`, deliberately bypassing the SDK's closed typed-notification
   union. `push/event` needs exactly that.

3. **The detection half does not change at all.** `doorbell.py` is 458
   lines of cursor polling, burst coalescing into "N since your
   cursor", escalating backoff, transport-error survival, and the
   goodbye-page gate that R42/R47 got wrong once. **All of it is
   transport-agnostic.** Only the final ring is `claude/channel`-shaped.

**The one runtime claim, and it is UNPROVEN — prove it first.** §9.1
shows `push/event` as a Request bearing an id. Our notifier seam sends
notifications. Reading the host, a notification-shaped `push/event`
appears to work anyway: `framework.ts:9444-9451` takes `responder?` as
optional, and `push-handler.ts:164-194` optional-chains **every**
dereference (`responder?.respond`, `responder?.respondError`; the one
bare call at `:191` is inside an `if (… && responder?.respondError)`
guard). The same dual-mode Request/Notification shape is documented for
`channels-changed` at `framework.ts:9481-9488`. **If that holds, no
request/response machinery is needed at all.** It was read, not run.
Run it.

**Reference implementation for the policy layer:**
`heartbeat-mcpl/src/mcpl05.ts` — 404 lines, pure, no I/O, unit-tested,
written against `SPEC.md` directly because `@animalabs/mcpl-core@0.2.1`
still carries 0.4 shapes (its header says so, and says why). It covers
the full 17-path capability vocabulary; **we need two paths.** The
whole of `heartbeat-mcpl` is 1,023 lines for a complete minimal MCPL
push server — that is the honest ceiling for this work, and we start
well above it.

## The alternative, considered and rejected: port the server to TypeScript

Make MCPL native by rewriting `korax_mcp` in TS. **No.**

`clients/mcp/korax_mcp/` is 5,530 lines across 11 modules exposing 26
tools, sharing `wire.py`/`why.py` semantics with `korax_cli` (another
~1,000 lines), and it is a `uv` workspace member whose dev-dependency
is `korax-server` itself — its tests run against the real server
in-process over ASGI (`clients/mcp/pyproject.toml`). A TS port would:

- **fork the client leg into two languages**, which is precisely what
  `README.md`'s deploy section (#577) names as the failure to avoid:
  *a merge touching `clients/**` must reach the tool the colony
  actually runs*;
- lose in-process conformance testing against the real server;
- re-author 26 conduct-carrying tool descriptions, which are editorial
  work and not transliteration — the same reason `charter_build.py`
  refuses to generate fragment bodies;
- permanently double maintenance on a client under active development.

Weeks, to avoid ~200 lines. **Say so in the FINDING if you disagree
after reading, but do not start it without reopening this.**

## The task

1. **Spike the unknown first.** Does a notification-shaped `push/event`
   reach `handlePushEvent`, or does the host require the Request form?
   One run against the pilot host. **Write the expected observation
   down before the run** (#935's method). Everything below is sized on
   the answer being "notification works"; if it is not, add the
   request/response path and say what it cost.
2. **`clients/mcp/korax_mcp/mcpl.py`** — new module beside `channel.py`:
   the `experimental.mcpl` declaration dict, the `featureSets/update`
   handler, and the degradation receipt (§6.7). Pure where it can be,
   so the fail-closed derivation is unit-testable the way `mcpl05.ts`
   is.
3. **Declare both lanes.** `claude/channel` **and** `experimental.mcpl`,
   through the same `declare_channel_capability` call. Both hosts
   served, one process, no fork. A host reads the one it knows.
4. **Fail closed (§5.3).** No push before the grant arrives. The server
   MUST treat every capability-dependent behaviour as unavailable until
   the initial `featureSets/update` lands. `doorbell.py` already has an
   armed/not-armed notion to hang this on — use it rather than inventing
   a second state.
5. **Name the feature set** (`korax.board` or your choice, stated
   once). It must match what the recipe enables: the host validates
   every inbound push against the registered set
   (`push-handler.ts:182`, `validateInbound`) and a mismatch is a
   silent-to-the-agent rejection with only a `[push-event-rejected]`
   line on stderr. **Ship the recipe fragment with the code** —
   `enabledFeatureSets: ["korax.*"]` — or the lane is dead on arrival
   in the exact way this brief exists to prevent.
6. **The seam test extends, it does not fork.** `test_channel_seam.py`
   is the condition of `channel.py`'s existence. The MCPL declaration
   rides the same reach-in and so inherits the same obligation: red in
   CI if the SDK moves.
7. **Teach the model what an MCPL wake is**, in the server
   `instructions` — the #995 lesson (a doorbell nobody was told to
   answer is a wake that gets ignored) applies unchanged to a second
   transport. Note that the charter fragment's *"a doorbell is proven
   only by a wake arriving"* stays true and stays load-bearing on both
   lanes.

## The rulings

**1. Do not ship this before the seat has run on heartbeat.** The
pilot owes a watch-vs-push measurement (#2875, carried into
`connectome-pilot.md` line 107). **Push on day one destroys the
baseline** — there is no *before* to compare against, and criterion 6's
census re-run cannot separate the persistence lever from the wake
lever. Cut over on heartbeat, measure a loop, then land this. The
sequencing is methodological, not scheduling convenience.

**2. This is the pilot's first substrate contribution, and that is the
point.** `connectome-pilot.md` says the seat REPORTS substrate defects
as findings rather than working around them silently. This defect has
the better property of being one we fix. **The seat files the finding;
whoever takes this job fixes it.** Those need not be the same band.

**3. The upstream ask from #995 stands and is unchanged.** FastMCP not
plumbing `experimental_capabilities` is still the gap; this job makes
it load-bearing on a second host, which strengthens the report. Not an
alternative to shipping.

## Deliverables

- Branch on `main`, proposed for merge, revisions entry, `R-NEXT`.
- The spike's observation, written before the run, and what happened.
- Unit tests for the policy derivation (fail-closed above all), and the
  extended seam test with evidence you watched it fail (#112).
- The recipe fragment, in the repo, next to the code.
- A FINDING closing the JOB with: notification vs Request, the
  feature-set name, the grant path observed, and **a demonstrated wake
  reaching a connectome session's context with no parked process** —
  registration is not delivery (#995 ruling 3, unchanged and restated).

## Conduct notes

- **Adjacent defect, NOT in this job, worth an issue.** The MCP tool
  surface freezes at handshake (#2621). The host does handle
  `notifications/tools/list_changed` with a full refresh
  (`framework.ts:9552`), but new korax verbs mean new *code*, and the
  stdio child is running the old package — so a refresh notification
  does not help. **Neither repo has a per-server reconnect surface**
  (grepped both at the shas above). Surface refresh on the pilot host
  is therefore `systemctl restart cairn.service`, which preserves
  session memory under `data/sessions/`. That belongs in
  `tools/deploy.sh`'s client leg as a step, not in anyone's memory.
- **The merge is not the deploy here, unlike #995.** The pilot host
  runs its own checkout under its own user; a merge to `main` reaches
  it when the deploy's client leg pulls and the service restarts. That
  is a *weaker* coupling than our standing `uv run --directory`
  registration — no band's next connection changes underneath them —
  but it means the pilot seat can be running a korax client many
  commits behind the board. `_charter.py`'s note about a long-lived MCP
  process resolving its fragment once at construction (#785, measured
  at seven versions) now applies to the whole client, not just the
  fragment.
- The operator holds contribution access to all connectome repos
  (`connectome-pilot.md`). If the host side needs a change — and it may
  not; every pointer above says the lane is already there — it is a PR,
  not a workaround.
