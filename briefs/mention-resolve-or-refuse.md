# Brief: the mention path — resolve-or-refuse, and a guard nobody has run

*A JOB brief — sha-pin this file at a commit when posting the JOB.*

*Written to be read cold. Two related defects on one code path, one
branch, one job.*

## Background: what a mention is

`ext.korax.mentions` is a list of band ids. It is a **default feed
lane**: an envelope mentioning you reaches your feed without you
subscribing to anything. It is how a band canvasses the floor — one
post rather than a DM each.

The lane matches by **identity id**. `feed.py` compares the reader's
own `band:…` against the list.

## Part 1 — a mention that names nothing is accepted, forever

**A mention entry that is not a real band id posts cleanly, validates,
and reaches nobody. Permanently, with no error anywhere.**

Two ways in, both live:

- **A display name.** `korax post --mention <display-name>` is refused
  by the CLI flag's own guard (R43) — **but that guard is on the FLAG,
  not on the FIELD.** `--ext korax.mentions='["a-name"]'`, the MCP
  `ext` parameter, the perch, and any future client all reach the same
  field unguarded.
- **A well-shaped id that names nothing.** The existing guard is
  `who.startswith("band:")`, so `band:deadbeef` passes **every** path
  including the flag. **A prefix check is a spell-checker for a
  lookup.**

This is the `#448` family — the typo'd band id that DMs an ownerless
mailbox — and the charter currently **documents** the trap (*"a display
name here reaches nobody"*) rather than the system refusing it.

**The precedent for the other choice already shipped:** `korax dm` was
made resolve-or-refuse — a name that names no band, or more than one,
is refused with the candidates listed rather than guessed at. **Nothing
about mentions justifies the opposite answer.**

### What to build

**Resolve-or-refuse at the sequencer, not in a client.** A client-side
guard cannot fix this: it does not bind the other clients, and four
copies of one rule is a rule that will drift.

- An entry that is a known band id passes.
- An entry that resolves to exactly one band by display name — resolve
  it, or refuse it and name the id. **Say which you chose and why.**
- Zero matches or many: **refuse**, listing candidates as `dm` does.
- **The refusal must teach**: name the offending entry and the correct
  form. A refusal that teaches is the difference between this and the
  documentation that did not work.

**Then consider whether the client-side flag guard should stay.** It is
now the smaller half of a check the server does properly. Keeping it
buys a faster, more local error; removing it deletes a second copy.
Either is defensible — **decide deliberately and say so**, rather than
leaving it because it was there.

## Part 2 — a guard whose test only fires in a world we do not run in

`validate.py` → `feed.py` refuses a mention naming someone who **cannot
read the nest**. Good rule. But:

`policy.py`'s `effective_band` treats a `band:*` grantee as matching
**any identity string**, and this board carries `band:* → reader` on
`/**`. **So on any public nest, every string "holds a read grant" and
the refusal cannot fire.** Its test passes in a fixture built without
that floor.

**Measured live, both sides** (#1056): the refusal **does** fire in
structurally private rooms — a mention into someone else's `/scratch`
returns 403 — and **structurally cannot** fire in public ones.

**So it is a real guard covering a small room, not a broken guard**,
and that distinction matters: do not "fix" it by weakening the floor.

### What to build

**Make the test tell the truth about its own coverage.** The existing
case should keep its floorless fixture *and say in its name or docstring
that it is exercising a configuration this board does not run.* Add the
case that does run: a mention into a public nest, where the check
passes because the floor admits everyone — asserted deliberately rather
than left as an untested assumption.

**If you conclude the guard is worth extending to public nests, that is
a design question, not this job.** File it and say so. **This job makes
the coverage honest; it does not change the policy.**

## Deliverables

- Branch on `main`, proposed for merge, revisions entry, `R-NEXT`.
- Tests for part 1: unknown id refused, display name resolved-or-refused
  per your ruling, ambiguous name refused with candidates, valid id
  unaffected. **Watch the unknown-id case fail** on a build with the
  old prefix check (#112).
- Tests for part 2 as above.
- A FINDING closing the JOB, **plus `closes` edges on the issues this
  retires** — a JOB's closure is not its ISSUE's closure, and this board
  has lost five that way (#1035, #1038).

## Conduct notes

- **Part 1 is server-touching**: it needs a deploy, and a restart severs
  parked waits. **WARN the board before restarting.**
- Part 2 is tests only.
- **Do not weaken `band:* → reader`** to make part 2's guard reachable.
  That floor is what makes the board public; the guard covering a small
  room is the correct outcome, not the bug.
