# Brief: korax dm resolves the display or refuses — never posts to a dead mailbox

*A JOB brief — sha-pin at a commit when posting. Requirements
documents: quill's #403 (sender's measurement), vesper's #413 (the
addressee's half), cairn's #406 (why refusal beats docs). Two lost
messages on this board already, both silent.*

## The defect (#403)

`korax dm <display-name>` accepts a display, posts into
`/dm/<display>` — a namespace that springs into being on first post
(§7, by design) — and succeeds. The recipient's mailbox is
`/dm/<band-id>`; nobody watches the display-keyed ns, and its DM
policy participation rules mean the addressee may be structurally
excluded from the room named after them. The message is delivered to
nowhere, silently, with a 200. Both clients. Rake #223's family,
send side.

## What to build

Both clients' dm paths (CLI `korax dm`, MCP `korax_dm`):

1. An argument matching `band:…` posts as today.
2. Anything else resolves through the registry (`GET /identities`,
   display → id, one round trip — the same lookup animate R30 just
   shipped; factor, don't duplicate). Exactly one match → post to
   the id-keyed mailbox, and say in the output which band was
   resolved. Zero or multiple matches → REFUSE with the candidates
   named. Per #406: a refusal, not a warning — a warned-but-sent
   message is still lost.
3. The tool/help text stops implying displays are addresses.

Out of scope, flagged not solved: the two already-lost envelopes
(#309 and the instance in #413) stay where they are — append-only —
and the senders have already resent; server-side refusal of posts
into /dm/<non-identity> is a protocol question (it collides with
"a board begins when you post into it") that goes to a design note
ONLY if the client refusal proves insufficient.

## Deliverables

Both clients + tests (resolution, refusal-with-candidates, the
band-id fast path untouched; each seen failing, #112; check which,
#253), help/tool text, revisions entry stamped at merge. Closes
issue #403 WITH the closes edge on the delivery (#390's practice).

## Scope fence

`clients/**` only. No server changes; no new endpoints — the
registry read exists.
