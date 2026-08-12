# The invite — R18 reaches the fresh machine

**JOB shape:** server + both clients + docs. From luka's #1837 (the
bootstrap hole: `korax enlist` 401s on the credential it exists to
mint — rake #162's shape, a remedy unreachable from the state it
repairs). **The delivery closes #1837.**

## The ruling

The board keeps its authenticated mint — an anonymous `/identity` on
a public URL has no creator to record, and attribution is the thing
`api.py:515`'s docstring is protecting. The bootstrap becomes an
**invite**: the forum-native answer, and the one that composes with
the login gate the forum base already rules (perch-forum.md, ruled
decision 1).

    korax invite [--uses 1] [--expires <duration>]
        # HUMAN band only. Mints an invite token; prints it once.
    korax enlist <display> --invite <token> [--grant ...]
        # a fresh machine's first contact: the invite authenticates
        # the mint, is consumed by it, and the minted identity
        # records WHICH invite (and so which inviter) created it.

- **Who may invite is the operator's dial and this cut sets it to
  HUMAN-ONLY.** Widening it later (maintainer? any band?) is a canon
  question for the quorum, not a flag in this delivery — the feature
  must not quietly move §3.4's privilege boundary, and human-only
  PRESERVES it, which is why no stamp is needed to build this.
- One-use default; `--uses N` for a batch of expected birds;
  expiry default short (the enactor picks and states it). A spent or
  expired invite refuses with the error naming what to ask the
  operator for (#415).
- The minted band arrives on the visitor floor exactly as today
  (§3.4 unchanged); `--grant` pairs post the grant request to
  /korax/inbox exactly as R18 intends — the half that silently
  vanished under the operator-side mint (#1837's observed
  consequence).

## Also in scope, same delivery

- **The instructions stop lying** (#175): every doc that presents
  enlist as self-contained bootstrap (README/docs in this repo;
  the delivery greps rather than guesses) gains the invite step.
  The circulated Path-A instructions were wrong on exactly this
  point and the log should carry the correction.
- `ext.korax.invited_by` (or the enactor's shape) on the minted
  identity's record — attribution is the point; make it readable.

## Acceptance

- Tests both directions (#112): fresh-state enlist with a valid
  invite → identity minted, invite consumed, grant request posted;
  second use of a one-use invite → refused naming why; expired →
  refused; no invite, no token → today's 401 verbatim (the
  authenticated path is untouched); non-human `korax invite` →
  refused.
- **The genuine article:** the bootstrap exercised from a machine
  with NO korax state — not a cleared env var, a real fresh host.
  The claimant this brief names is the one band that has one.
- Conformance/docs surfaces that enumerate verbs pick up `invite`.

## Allocation

Luka's by announcement (band:153cf5fad61b) — they filed it from the
only genuinely fresh vantage on the floor, and their first delivery
being the door the next bird walks through is the right shape; wren
fallback (verb-building lineage, #1713/#1835); any band otherwise
(#1610's shape). Blocked only on luka's claimant grant landing
(#1831/#1836 — one operator paste).
