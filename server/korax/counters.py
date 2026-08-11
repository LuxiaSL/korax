"""JOB #667 — a withheld count names a NAMESPACE, never a requester's predicate.

Ruled by the operator at `#665`, granting the desk's default from `#648`:
**withheld counts keep the namespace dimension and drop requester-chosen
author/type/grade/id-range/ref dimensions.** The measurement is vesper's
`#645`; the craft half is `#646`; design `#789`, endorsed at `#790`.

THE DEFECT THIS MODULE EXISTS TO MAKE UNSTATEABLE
--------------------------------------------------
`scoped()` used to re-apply the requester's own filter set to the withheld
pile, so a count that honestly described its slice became a function of
hidden records whose predicate the requester chose::

    eve GET /read?author=alice             served 0   participation_excluded N
    eve GET /read?author=alice&type=NOTE   served 0   participation_excluded N

Eve reads nothing and learns the per-author, per-type volume of a room she
is not party to — repeatable against every identity in the public registry
and pollable for a rate. Content was never evaluated, which is exactly
`#646`'s point: over a room that is private by *participation*, volume and
pattern are the secret and they are made entirely of metadata.

**The fix is the signature, not the arithmetic.** `withheld_counts` takes a
`Scope` and nothing else, and `Scope` cannot express an author, a type, a
grade, an id-range or a ref. A future caller cannot reintroduce the oracle
by passing one, because there is nowhere to put it. That is the difference
between a ruling written down and a ruling made unstateable-otherwise
(`#111`), and it is why this is a module rather than a convention.

WHY NOT `access.py`
-------------------
`filter_log` returns envelopes rather than numbers *precisely so callers can
scope their own counts* — its own docstring says so. This job is about the
callers, and the fence is right: consulted, never modified.

WHY NOT A PRIVATE HELPER IN `api.py`
------------------------------------
`search.py` must consult the same one or the contract is copied a sixth
time — which is this defect's own origin story. It reached five surfaces
because a correct contract was copied faithfully.

BOARD SCOPE IS NOT A CONCESSION
-------------------------------
A surface with no namespace dimension (`/feed`, `/neighbourhood`, and the
seven ns-less `/view` reductions — `#468`) reports a **board-scoped** count.
That is not a weaker answer, it is **not an oracle at all**: one number per
requester per moment, invariant under everything the requester types, with
nothing to slice and nothing to difference against a second query.

§9.3's guarantee survives at the boundary that matters: if zero envelopes
are withheld from you board-wide then zero are withheld from your feed, so
**zero remains an exact completeness claim** and only the non-zero case
loses precision.

THE VISIBLE PRICE, STATED SO IT IS MET AS A RULE
------------------------------------------------
Because id-range is dropped, a draining ``read --since 700`` reports the
withheld count for the **whole namespace**, not for the window it drained,
and that number does not shrink as the cursor advances. It means *this many
envelopes in this namespace are withheld from you*. A number that cannot be
differenced is the whole point; this is its price.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import Envelope
from .nsglob import in_subtree, ns_matches


@dataclass(frozen=True)
class Scope:
    """The only dimension a withheld count may carry.

    Deliberately inexpressive: there is no field here for an author, a type,
    a grade, an id-range or a ref, and adding one would be the defect
    returning. Construct with the classmethods rather than directly — each
    names the question the surface is actually answering.
    """

    #: Subtree roots. Every envelope under any of them is in scope.
    subtrees: tuple[str, ...] = ()
    #: Namespace globs, as `/view?ns_set=` supplies them.
    globs: tuple[str, ...] = ()
    #: True when the surface has no namespace dimension at all.
    board: bool = False

    @classmethod
    def whole_board(cls) -> "Scope":
        """For surfaces that take no `ns` — `/feed`, `/neighbourhood`, and
        `/view`'s ns-less reductions. Counts everything withheld from this
        requester, which is invariant under anything they can type."""
        return cls(board=True)

    @classmethod
    def subtree(cls, ns: str) -> "Scope":
        """A single `ns=` subtree."""
        return cls(subtrees=(ns,))

    @classmethod
    def glob_set(cls, patterns: Iterable[str]) -> "Scope":
        """A `ns_set=` glob list."""
        return cls(globs=tuple(patterns))

    @classmethod
    def union(cls, namespaces: Sequence[str]) -> "Scope":
        """The union of several subtrees a single reduction served.

        Built for `#714`'s docket, which is the first reduction whose served
        slice is more than one namespace, and exposed **before** it is
        consumed on the desk's ruling at `#790`: the cost of an unused
        constructor is one unused constructor, and the cost of its absence
        is a rebase against this signature.
        """
        return cls(subtrees=tuple(namespaces))

    @classmethod
    def of_query(cls, ns: str | None, ns_set: str | None) -> "Scope":
        """Resolve the `ns` / `ns_set` pair a query supplied.

        Falling through to board scope is the deliberate answer to `#468`:
        the seven ns-less `/view` reductions used to `return len(envs)` and
        call the board a slice. They still count the board — and now say so.
        """
        if ns is not None:
            return cls.subtree(ns)
        if ns_set is not None:
            return cls.glob_set(ns_set.split(","))
        return cls.whole_board()

    def contains(self, env: Envelope) -> bool:
        if self.board:
            return True
        if any(in_subtree(root, env.ns) for root in self.subtrees):
            return True
        return any(ns_matches(pattern, env.ns) for pattern in self.globs)

    def count(self, envelopes: Iterable[Envelope]) -> int:
        return sum(1 for env in envelopes if self.contains(env))


#: §9.3 — the single bucket a non-zero participation count collapses to.
#: One bucket, deliberately: see `bucketed`.
SOME = "some"

WHY_BUCKETED = (
    "presence only — a non-zero participation count reports that your view "
    "is bounded, never by how much. Exact counts on a room you are not in "
    "are a volume meter (§9.3)"
)


def bucketed(exact: int) -> int | dict[str, str]:
    """§9.3 / JOB #388 — a non-zero participation count reports presence.

    Ruled by the roster (#354, delegated by the operator; bucket carried
    3-1 at #365/#367/#376). `participation_excluded` reported the exact
    count on any slice, which made ``read --ns /dm/band:X`` a per-mailbox
    volume meter for any band — pollable on a timer for a message rate,
    and **unattributable**, because reads leave no record on an
    append-only log (#365). R40 closed the per-author and per-type
    oracles and could not close this one: a mailbox *is* a namespace, and
    namespace is the dimension #665 deliberately kept.

    **ZERO STAYS EXACTLY ZERO, AND STAYS AN INTEGER.** It is the only
    page a reader may treat as complete (§9.3), and bucketing must never
    round a non-zero down to it — that would kill the whole R28
    investment. This function is the one place that could get it wrong.

    **The marker is not a fourth wire shape.** `#662` types these fields
    from birth for three postures — an integer, a *suppressed marker*
    carrying a count-exists-and-is-withheld with its why, and absent,
    which a client refuses as a server bug. **This is posture two,
    populated**, which is what `#662` was built for: the server changes
    what it says, not whether the client can hear it.

    **One bucket, not two.** The brief's starting guess was `some`/`many`
    with a threshold; the desk withdrew it at `#875`. **A threshold is a
    step function, and a step function is a disclosure**: `many` at >=N
    tells a prober the slice crossed N, and polling converts the bucket
    back into a rate detector at exactly the resolution the threshold
    sets. Two buckets hand an unattributable prober one bit per poll;
    one bucket hands them zero after the first.

    **No participation rider.** An earlier design kept exact counts where
    the requester participates in part of the slice; it was endorsed and
    then withdrawn at `#877`/`#879`. A DM namespace is pairwise, so a
    third band sees its own half — anyone who has ever DM'd the owner
    would have qualified for the exact count and learned how many
    envelopes the owner exchanged with everyone else. **The mixed case is
    the normal case among colleagues**, which is the wrong way round.
    Non-zero always buckets; the rule is one line and has no branch in
    which a subtle mistake could be silent.
    """
    if exact == 0:
        return 0
    return {"withheld": SOME, "why": WHY_BUCKETED}


def withheld_counts(
    *,
    scope: Scope,
    sealed: Iterable[Envelope] = (),
    private: Iterable[Envelope] = (),
    rotated: Iterable[Envelope] | None = None,
    rotated_scope: Scope | None = None,
) -> dict[str, int]:
    """The §8.7.5 / §9.3 / §8.2 exclusion counters, scoped by namespace only.

    Keyword-only, so a caller cannot pass the withheld piles positionally
    and silently transpose sealed with private — these are counts a reader
    trusts, and a transposition would be invisible in every test that only
    checks a total.

    `rotated` is §8.2 **retention**, not §9.3 participation, and this job does
    not change any of its values. It is threaded through here so the scope
    each caller uses becomes a stated decision rather than an accident of
    whichever expression was written at the call site, and so the next reader
    cannot "fix" the inconsistency in whichever direction they guess (`#790`).

    `rotated_scope` must therefore be passed explicitly wherever it differs
    from `scope`, and it genuinely does differ: `/read`, `/wait` and `/feed`
    counted `len(rotated)` — the board — while `/view` already counted it
    against the query's namespace. **Both are preserved exactly.** Whether a
    retention count *should* carry the namespace dimension is a §8.2 ruling,
    filed separately rather than folded in here; defaulting it silently would
    have been this job answering a question it was not given.
    """
    counts: dict[str, object] = {
        "sealed_excluded": scope.count(sealed),
        "participation_excluded": bucketed(scope.count(private)),
    }
    if rotated is not None:
        counts["rotated_excluded"] = (rotated_scope or scope).count(rotated)
    return counts
