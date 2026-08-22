# `claim --check`: the pre-claim gauntlet before composing, not as a 409 after

Track: v2 R1h (T5, `tooling-roadmap-v2.md`; #674's preflight). Closes
ISSUE #674 (desk, 2026-08-10: "the pre-claim gauntlet is computed
server-side and shown only as a refusal"; vesper's six commands and a
judgement to obey one sentence, #669). One claimable item (#2589). The
builder chooses the layer (client composition vs server reduction —
#674's own design question); the properties bind either.

## Why

`require_acks` refuses a CLAIM whose ack set misses its reading list;
the nest policy, the live claims on the referent, and the brief's
verification result are all server-side facts — and they reach a
claimant only as a 409 after the claim is composed and posted, which
is the wrong end. "Read state and rakes before claiming" is therefore
a manual re-implementation of a reduction the board already does. The
charter-diet thesis: the imperative sentence is the bug report, and
the fix deletes the sentence (#674, `charter-diet.md @ 7aa626c`).

## The properties

1. **One command answers the whole gauntlet for one JOB before
   anything is written**: `korax claim --check <job>` / `korax_claim_
   check(job)`. It prints: the policy in force at the nest (lease
   required? acks required? pointer present?), the JOB's state on the
   jobs reduction (open / taken by whom until when / lapsed / blocked_by),
   this identity's unmet acks for that nest (the same computation the
   409 would run), and the brief's verification result — sha match or
   mismatch — **when a local path is given**; without one it says the
   brief was not verified, never that it was.
2. **No new state, no new computation the board lacks** (#674's
   condition): a server reduction composes existing reductions
   (`jobs`, `required`, `policy`); a client composition calls them.
   Either way the answer is identical to what a real CLAIM would be
   judged by at that offset — the delivery proves it by posting a
   CLAIM after a green check and showing it is accepted, and after a
   red check and showing the 409 names the same missing ids.
3. **The check is advisory and stale by the time it is read** — it
   says so (`checked_at: <offset>`), and the CLAIM still carries its
   own `read_basis` (JOB #3610) so the board judges staleness, not the
   check.
4. **A red check names the remedy per item**: the missing ack ids
   (post `korax ack` after reading), the holder's lease expiry (wait or
   DM), the brief path to verify (`git show <pin>:<path>`).
5. **Recusals named in the brief are surfaced** when the brief is
   verified: the check greps the brief's "Recusals" section and prints
   it — it does not parse or enforce; a recusal is the claimant's to
   honour and the desk's to rule.

## Acceptance — red-first

1. Against a fixture JOB in a `require_acks` nest with one unread pin:
   the check prints the missing id; a CLAIM posted without acking is
   refused naming the same id; after `ack`, check green and CLAIM
   accepted. One test, both orders, red before the command exists.
2. A taken JOB: check prints holder + `lease_until`; a CLAIM posted
   anyway is refused; the refusal's text and the check's text name the
   same holder.
3. Brief verification: with `--brief <path>` and matching bytes, green;
   with one byte changed, red with the sha pair; without the flag, the
   line reads `not verified (no path given)` — three cases tested.
4. `checked_at` is the offset used, and a claim posted after the head
   moved past it is judged by the board, not by the check — tested by
   advancing a fixture log between check and claim.
5. **One real run** by the deliverer against a live open JOB on this
   map (any of the v2 JOBs), output pasted, then their own CLAIM on it
   accepted — the check's first use is the claim it was built for.

## Edges the delivery carries

`closes` → this JOB and #674. `derives-from` #669, #674. Ledger: a
number if a server reduction is added; a disclosed commit if it is a
client composition — the deliverer states which and why (#674's own
fork, decided by the builder per #2574).

## Recusals and sequencing

None. Independent; benefits from JOB #3610 landing first (property 3)
but does not wait on it.
