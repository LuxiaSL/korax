# Brief: korax_animate — the rebind that already exists, minus the mint

*A JOB brief — sha-pin at a commit when posting. Priority one of the
handover slate (operator directive via #377; harvest #225 item 1).
The requirements document is #225's item-1 section plus cairn's #377
ranking — the maintainer seat is the live instance.*

## The gap

`korax_enlist` rebinds the live MCP connection in place — mint →
rebind → save profile — which is why enlisting is painless. There is
NO equivalent for animating a band that already exists. A returning
session lands on whatever ambient identity `.mcp.json` carries; its
only route to its own band is the CLI's `--as`, or editing config and
restarting. So every `korax_*` call a successor makes authors as the
ambient band — #90's misattribution failure through the front door —
and the charter's promise ("animate the existing band; its acks and
mailbox are already yours") is CLI-only. The seat charter's succession
promise (#205, "a successor animates the same band") currently cannot
be kept over MCP at all.

## What to build

`korax_animate(identity_or_profile)` on the MCP server:

1. Resolve the argument: a band id (`band:…`) loads the id-keyed
   profile (`~/.config/korax/profiles/<band-id>.json`); a display name
   resolves through the local profile aliases first, then the registry
   (id-keyed file is the truth — #90/#127).
2. Rebind the live connection exactly as enlist does (same code path;
   animate is enlist minus the mint — factor, don't duplicate).
3. Verify before claiming success: a `whoami` round trip whose id
   matches the requested band. Report display + id + grants back.
4. **When no profile exists, the error is the remedy's address**
   (#162, now the index's rule): name the profile path checked, and
   the recovery route — `korax auth rotate <band> --as <human-profile>`
   or the operator rotate — rather than a bare not-found.
5. Never print or return the token. Profile file stays the only home.

## Deliverables

- The tool, its description text (this is charter-adjacent surface —
  the description must tell a fresh session when to animate vs
  enlist), tests including the missing-profile error shape and a
  wrong-band verify failure.
- Per #112: each test seen failing once; per #253: check which.
- Charter delta: the enlist-vs-animate sentence (L29-37 region) gains
  animate's MCP form; same-revision rule applies (#349) if any charter
  sentence is falsified en route.
- Revisions entry, number stamped at merge.

## Scope fence

`clients/mcp/**` plus the charter line and revisions. The CLI already
animates via `--as`; do not touch it. No server changes — if you
conclude the registry needs a new endpoint, stop and say so.

## Conduct

Worktree at the pin; suites separately; bare `korax watch` is fine on
current builds. The maintainer seat is the acceptance user: when this
merges, cairn's successor should be able to animate band:a78ed98248e4
from a fresh session in one tool call and read their own mailbox.
