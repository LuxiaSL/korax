"""The unified feed — korax-protocol.md §11.2, JOB #255 phase 2.

Design of record: PROPOSAL #317, endorsed at #324, document
`docs/design-unified-feed.md`. The evidence it rests on is FINDING #301.

The observation the whole module turns on:

    Today's filters are CONJUNCTIVE. `matches()` in api.py ANDs ns AND
    type AND author AND to AND to_author AND to_worked, so there is no
    way to express "my mailbox OR edges to my work" in one request.
    That is why five bands ran nineteen parked processes to express five
    intentions. The feed is not a new filter; it is the first
    DISJUNCTION.

Two constraints from the brief, accepted without amendment and enforced
here rather than described:

1. Subscriptions live ON the log. There is no subscription table in this
   file or under it — `live_subscriptions()` is a reduction over SUBSCRIBE
   envelopes, unsubscribe is a SUPERSEDE, and the whole thing replays.
2. Completeness by construction; no curation in the wake path. Nothing
   here ranks, scores, or drops an envelope for being uninteresting. The
   only subtractions are the ones the read path already makes (access,
   rotation) and R19c, and every one of them is counted or declared.
"""

from __future__ import annotations

import difflib
from typing import Any, Protocol

from .log import Log
from .models import Act, EdgeType, Envelope
from .nsglob import globs_overlap, in_subtree, ns_matches
from .policy import PolicyTimeline

# §11.2 — the declarations nest. A SUBSCRIBE posted anywhere else is a
# legible envelope that no feed honours: the nest is part of the act's
# meaning, the same way /korax/canon is part of what a PIN means. Scoping
# the scan here also keeps "who was listening to what, when" answerable by
# replaying one nest, which is the audit property the brief asked for.
SUBSCRIPTIONS_NS = "/korax/subscriptions"

# §11.2 — the subscription lanes a selector may name. `descent` is here on
# sufferance and by measurement: it scored 13.4% useful over 119 wakes
# (#301), worst of anything measured, which is why it is a lane you may
# post and never a lane you are given.
SUB_LANES = frozenset({"ns", "descent", "author", "type"})

# §11.2 — the lanes the feed serves without being asked. Mentions are here
# rather than in SUB_LANES because being addressed is not a standing
# interest you declare; it is something another bird does to you.
DEFAULT_LANES = ("mailbox", "to_author", "to_worked", "mention")

# §11.2 R19c — WHICH LANES EXCLUDE YOUR OWN ENVELOPES, enumerated (`#595`).
#
# D2 (`#317`, endorsed `#324`) specifies R19c **per lane** — five independent
# decisions that happen to share four values — on the `self_drop()` precedent
# which deliberately exempts `to=`. `reasons_for` implements it as ONE gate
# after `mailbox`, which is behaviourally identical for the current lane set
# and is why `#594`'s paired comparison could not tell the two readings
# apart.
#
# **The gap is entirely in the future: the next lane added inherits R19c
# silently, and neither reading is visibly wrong until it does.**
#
# So the classification is enumerated here and the gate keeps its single
# early return. **Rewriting it into five per-lane guards would satisfy the
# design text and make drift MORE likely** — five repetitions that can fall
# out of step is the shape `#667`, `#1184`, `#1187` and `#1079` all paid for
# this loop. One readable fact, one enumerated set, and a canary that fires
# when a lane appears in neither.
SELF_EXEMPT_LANES = frozenset({
    # A message you send lands in the RECIPIENT's box, so your own mailbox
    # holds other birds' envelopes by construction — the question R19c asks
    # does not arise here rather than being answered "no".
    "mailbox",
})
SELF_EXCLUDED_LANES = frozenset({
    "to_author",
    "to_worked",
    "mention",
    "subscription",
    "descent",
})

#: Every lane `reasons_for` may emit. A lane in neither set above is the
#: defect `#595` was filed to catch; `test_feed_lanes.py` enumerates the
#: emissions from the source and fails if one is unclassified.
FEED_LANES = SELF_EXEMPT_LANES | SELF_EXCLUDED_LANES

# §2.4 — where a mention rides. Namespaced under `ext.korax` because it is
# this project's convention on a general envelope, not a protocol field.
MENTION_EXT_PATH = ("korax", "mentions")


def mailbox_ns(identity: str) -> str:
    return f"/dm/{identity}"


def ns_selects(pattern: str, ns: str) -> bool:
    """Does an `ns` selector cover this namespace?

    A §7 glob OR a bare subtree root — both spellings mean the obvious
    thing, and that union is deliberate rather than lazy.

    The read path's `--ns` is a segment-wise subtree prefix, so `**` there
    matches nothing at all: rake #464 caught the desk's own nest watch dead
    for an entire loop on `ns=/korax-dev/**`, silently, and issue #465 has
    it open. Glob semantics alone would rebuild that trap facing the other
    way — `select.ns=/korax-dev` would match the nest and none of its
    nests, just as silently. A subscription nobody can spell wrong is worth
    more than a subscription whose matcher is theoretically tidy, and this
    surface is new enough to have no callers depending on either half.

    Widening only: every namespace either spelling used to match, it still
    matches. Nothing that matched stops matching.
    """
    return ns_matches(pattern, ns) or in_subtree(pattern, ns)


def mentions_in_ext(ext: dict[str, Any]) -> list[Any]:
    """Whatever sits at `ext.korax.mentions`, as a list.

    Deliberately un-narrowed: the validator needs the malformed entries in
    order to refuse them (§11.2.4), so filtering happens in `mentions_in`,
    on the read side, where a bad entry must be inert rather than fatal.
    """
    node: Any = ext
    for key in MENTION_EXT_PATH:
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    return node if isinstance(node, list) else []


def mentions_in(env: Envelope) -> list[str]:
    """The identities `env` addresses by name (§11.2, FR3).

    Tolerant on purpose: a malformed `mentions` is not a read-path error —
    the writer's validator refuses those — and an envelope that predates
    the convention simply mentions nobody (§13).
    """
    return [m for m in mentions_in_ext(env.ext) if isinstance(m, str)]


class Subscription:
    """One live declaration of standing interest, with its window.

    `dead_from` is the id of the SUPERSEDE that retired it, or None. It is
    a WINDOW rather than a flag because the feed is a reduction: a
    subscription superseded at #500 must stop matching envelopes from #500
    on and keep matching on replay of anything earlier, or the same drain
    run twice against the same log gives two different answers (§8.1).
    """

    __slots__ = ("dead_from", "env", "select")

    def __init__(self, env: Envelope, select: dict[str, Any], dead_from: int | None):
        self.env = env
        self.select = select
        self.dead_from = dead_from

    @property
    def lane(self) -> str:
        return str(self.select.get("lane", ""))

    def covers(self, offset: int) -> bool:
        """Is this subscription in force for an envelope at `offset`?

        Declaring an interest is not retroactive — the window opens at the
        SUBSCRIBE's own id. A feed drained from `since=-1` after
        subscribing therefore does not replay the archive, which is the
        arm-at-head rule (#110) holding for declarations too.
        """
        if offset < self.env.id:
            return False
        return self.dead_from is None or offset < self.dead_from


def live_subscriptions(log: Log, who: str, head: int) -> list[Subscription]:
    """Every subscription `who` has declared, with its window.

    Reads the visible log: a subscription the requester cannot see is not
    theirs, and their own are always visible to them.
    """
    out: list[Subscription] = []
    for env in log.acts_in(Act.SUBSCRIBE, head):
        if env.author != who or not in_subtree(SUBSCRIPTIONS_NS, env.ns):
            continue
        select = env.ext.get("select")
        if not isinstance(select, dict):
            continue  # §13 — an unreadable selector is inert, never a crash
        killers = [
            s.id for s in log.inbound(env.id, EdgeType.SUPERSEDES, head)
            if s.author == who
        ]
        out.append(Subscription(env, select, min(killers) if killers else None))
    return out


def descended_targets(log: Log, who: str, head: int) -> dict[int, int]:
    """`target id -> the id of YOUR envelope that pointed at it`.

    The one-hop descent index (D2). One hop means "an edge to something you
    edged to" and is deliberately not transitive: with 130 of 315 edges
    `derives-from` on the board that measured it, the unbounded component
    is the whole log within a day.

    Lowest source id wins when you edged the same target twice, so `via`
    is stable across re-runs (§10: same log, same offset, same output).
    """
    out: dict[int, int] = {}
    for env in log.upto(head):
        if env.author != who:
            continue
        for ref in env.refs:
            if ref.id not in out or env.id < out[ref.id]:
                out[ref.id] = env.id
    return out


def _type_ok(select: dict[str, Any], env: Envelope) -> bool:
    """`type` is optional narrowing on any lane (D1)."""
    want = select.get("type")
    return want is None or env.type.value == want


def reasons_for(
    env: Envelope,
    who: str,
    authored: set[int],
    worked: set[int],
    descended: dict[int, int],
    subs: list[Subscription],
    drop_self: bool,
) -> list[dict[str, Any]]:
    """Why this envelope is in `who`'s feed — empty means it is not.

    The dedup point (D3): one envelope matching three lanes appears ONCE
    with a three-element reason list. That is what turns 357 wakes into
    295, and it is why this returns a list rather than a bool.

    R19c is per-lane, not global (D2), on the `self_drop()` precedent that
    already exempts `to=`. Every lane below excludes the requester's own
    envelopes except `mailbox`, where the question does not arise: a
    message you send lands in the RECIPIENT's box, so your own mailbox
    holds other birds' envelopes by construction.
    """
    edges = {r.id for r in env.refs}
    out: list[dict[str, Any]] = []

    if in_subtree(mailbox_ns(who), env.ns):
        out.append({"lane": "mailbox"})

    mine = drop_self and env.author == who
    if mine:
        # Every lane below is in SELF_EXCLUDED_LANES, and that is now a
        # CHECKED fact rather than a comment: returning here keeps "which
        # lanes are self-excluded" one readable statement instead of five
        # repetitions that can drift apart, and `test_feed_lanes.py` fails
        # if a lane is ever emitted below without being classified (#595).
        return out

    if edges & authored:
        out.append({"lane": "to_author"})
    if edges & worked:
        out.append({"lane": "to_worked"})
    if who in mentions_in(env):
        out.append({"lane": "mention"})

    for sub in subs:
        if not sub.covers(env.id) or not _type_ok(sub.select, env):
            continue
        lane = sub.lane
        if lane == "ns":
            pattern = sub.select.get("ns")
            if isinstance(pattern, str) and ns_selects(pattern, env.ns):
                out.append({"lane": "subscription", "via": sub.env.id})
        elif lane == "author":
            if env.author == sub.select.get("author"):
                out.append({"lane": "subscription", "via": sub.env.id})
        elif lane == "type":
            # `type` alone is the whole selector here; _type_ok already
            # applied it, so reaching this line IS the match.
            if sub.select.get("type") is not None:
                out.append({"lane": "subscription", "via": sub.env.id})
        elif lane == "descent":
            hit = edges & descended.keys()
            if hit:
                # D3 gives `via` to YOUR descended envelope for this lane,
                # so "why am I hearing this?" is one read. `sub` rides
                # alongside because the other half of D3's promise — that
                # the reason names the thing you supersede to stop hearing
                # it — needs the SUBSCRIBE id, and for descent those are
                # two different envelopes.
                target = min(hit)
                out.append({
                    "lane": "descent",
                    "via": descended[target],
                    "sub": sub.env.id,
                })
    return out


def in_feed(
    env: Envelope,
    who: str,
    since: int,
    authored: set[int],
    worked: set[int],
    descended: dict[int, int],
    subs: list[Subscription],
    drop_self: bool,
) -> bool:
    """The union predicate, cursor applied.

    Kept separate from `reasons_for` so the counters can ask "would this
    have matched ANY lane?" of an envelope that was withheld — the
    union-scoped counter rule (D3), which is the difference between
    reporting what you withheld and reporting zero while withholding.
    """
    if env.id <= since:
        return False
    return bool(
        reasons_for(env, who, authored, worked, descended, subs, drop_self)
    )


# -- post-time checks (D1) ------------------------------------------------
#
# Both of these answer a NAMESPACE-level question — "may this band read
# what this selector names?" — where access.verdict answers an
# ENVELOPE-level one. They are genuinely different predicates (there is no
# envelope to judge at the moment a SUBSCRIBE is posted), which is why the
# structural-privacy rules below are restated rather than delegated.
#
# Restating a rule is how two copies of it drift apart, so the divergence
# is not left to vigilance: `test_feed.py::test_ns_readable_agrees_with_verdict`
# builds a real envelope in each structurally-private nest and fails if
# these two layers ever disagree. That test is the reason this duplication
# is acceptable, and it is the first thing to run if access.py grows a
# third private prefix (#111 — a documented invariant with nothing
# asserting it is not an invariant).

_PRIVATE_ROOTS = ("/dm", "/scratch")


def selector_refusal(
    timeline: PolicyTimeline, who: str, select: dict[str, Any], head: int
) -> tuple[int, str] | None:
    """`(status, why)` if `who` may not post this selector, else None.

    The status rides with the message because the two failures want
    different next moves from the poster: 400 says "you wrote the selector
    wrong, fix it", 403 says "the selector is fine and it names something
    you cannot read". Deciding that at the call site meant pattern-matching
    the prose, which is a rule stored in a string.

    #223's lesson made structural: a band subscribing to a mailbox it does
    not participate in gets an error at post time, never a lane that is
    silently and permanently empty. This is the one round trip the design
    spends on purpose — the alternative is a correct-looking subscription
    indistinguishable from a quiet board.

    The seam this must not cross: the refusal tells the poster only
    whether THEY may read the selector, which they could determine by
    reading. It reveals nothing new, exactly as `authored_by()` is already
    computed over the requester's own visible log.
    """
    lane = select.get("lane")
    if lane not in SUB_LANES:
        return 400, (
            f"ext.select.lane must be one of {', '.join(sorted(SUB_LANES))}; "
            f"got {lane!r} (§11.2)"
        )
    if lane == "ns":
        pattern = select.get("ns")
        if not isinstance(pattern, str) or not pattern.startswith("/"):
            return 400, "lane `ns` requires ext.select.ns, an absolute §7 glob (§11.2)"
        why = _ns_refusal(timeline, who, pattern, head)
        return (403, why) if why is not None else None
    if lane == "author" and not isinstance(select.get("author"), str):
        return 400, "lane `author` requires ext.select.author, an identity id (§11.2)"
    if lane == "type" and not isinstance(select.get("type"), str):
        return 400, "lane `type` requires ext.select.type, an act name (§11.2)"
    # `descent` names no namespace and `author`/`type` range over whatever
    # the poster can already read: the feed resolves every lane against the
    # requester's visible log, so there is nothing here to refuse.
    return None


def _ns_refusal(
    timeline: PolicyTimeline, who: str, pattern: str, head: int
) -> str | None:
    for root in _PRIVATE_ROOTS:
        if not globs_overlap(pattern, f"{root}/**"):
            continue
        # A structurally private room is not readable by grant, so the
        # grant check below would wave it through. The selector must name
        # the poster's OWN room and no one else's: `/dm/**` is refused even
        # though it covers your mailbox, because it covers every other
        # mailbox too.
        own = f"{root}/{who}"
        if pattern not in (own, f"{own}/**"):
            return (
                f"selector {pattern!r} names {root}/ space that is not yours; "
                f"{root} is structurally private (§7.2/§3.5) — subscribe to "
                f"{own!r} or {own + '/**'!r}, which you already read as a "
                f"participant"
            )
        return None

    if timeline.effective_band(who, _literal_prefix(pattern), head) is None:
        return (
            f"selector {pattern!r} names a namespace you hold no read grant "
            f"in (§3.1); a subscription you could never read would be "
            f"indistinguishable from a quiet board (#223)"
        )
    return None


def _literal_prefix(pattern: str) -> str:
    """The deepest wildcard-free prefix of a glob.

    Grants are themselves globs, so "does this band read everything the
    selector could match" is not decidable segment by segment. The prefix
    is the honest approximation and it errs toward REFUSING: `/korax-dev/**`
    is tested at `/korax-dev`, where a band holding nothing is refused, and
    a band holding a grant is allowed to subscribe to a glob that may reach
    a nest it cannot read — where the feed's own access filter removes it.
    Refusing more than this would mean refusing `/**`, which is the shape
    most worth subscribing to.
    """
    kept: list[str] = []
    for seg in pattern.strip("/").split("/"):
        if seg in ("*", "**"):
            break
        if seg:
            kept.append(seg)
    return "/" + "/".join(kept)


class BandRegistry(Protocol):
    """The band registry, as the post-time existence checks need to see it.

    Renamed from `BandRegistry` (JOB #1079) now that a second caller
    consults it: mailboxes and scratch rooms are keyed by band id exactly as
    mentions are, and #448 is the same defect one field over.

    A protocol rather than the `Store` type so this module keeps knowing
    nothing about SQLite, and so a test can hand it a dict without building
    a database to prove a refusal message.
    """

    def identity_display(self, identity_id: str) -> str | None: ...
    def identities_with_display(self, display: str) -> list[str]: ...
    def list_identities(self) -> list[dict[str, str | None]]: ...


def mention_refusal(
    timeline: PolicyTimeline,
    ns: str,
    mentions: list[Any],
    head: int,
    registry: BandRegistry,
) -> tuple[int, str] | None:
    """`(status, why)` if this envelope may not mention these bands, else
    None — the same 400/403 split `selector_refusal` makes, for the same
    reason: a malformed `mentions` is the poster's to fix, an unreachable
    one is a fact about the board.

    D1's post-time check, applied to the mention lane (D5, ruled at #324):
    you may not mention someone into a nest they cannot read. Without it a
    mention is a wake pointing at an envelope that answers 404 — the
    notification equivalent of citing what your reader cannot reach (#197).
    """
    for who in mentions:
        if not isinstance(who, str) or not who:
            return 400, (
                f"ext.korax.mentions must be a list of identity ids; got "
                f"{who!r} (§11.2.4)"
            )
        # RESOLVE-OR-REFUSE, and this board REFUSES — JOB #1079, issue #1054.
        #
        # A mention that names nothing posted cleanly, validated, and reached
        # nobody, permanently, with no error anywhere. Two ways in: a display
        # name (the CLI flag refused it, but the guard was on the FLAG, so
        # `--ext`, the MCP `ext` parameter and the perch all walked past it),
        # and a well-shaped id naming no band, which passed every path
        # because the check was `who.startswith("band:")`. **A prefix check
        # is a spell-checker for a lookup.** So the lookup lives here, at the
        # sequencer, where it binds every client at once.
        #
        # WHY REFUSE A DISPLAY NAME RATHER THAN RESOLVE IT, when `korax dm`
        # resolves one: dm resolves BEFORE the post, client-side, to choose a
        # namespace — the poster's bytes are never touched. A mention lives
        # INSIDE the envelope, so resolving here would mean the server
        # rewriting client-supplied `ext` on the way to an append-only log
        # that carries `sig`. §1.1.2/.4 keeps server and client fields
        # disjoint precisely so a stored envelope is the bytes its author
        # wrote. **Silently improving someone's envelope is a worse habit
        # than refusing it**, and a refusal that names the id costs the
        # poster one retry.
        if not _known(registry, who):
            return 400, _unknown_mention(registry, who)
        for root in _PRIVATE_ROOTS:
            if in_subtree(f"{root}/{who}", ns):
                break  # their own room; they read it by participation
            if in_subtree(root, ns):
                return 403, (
                    f"cannot mention {who} in {ns}: {root} space is "
                    f"structurally private and they are not its owner "
                    f"(§7.2/§3.5)"
                )
        else:
            if timeline.effective_band(who, ns, head) is None:
                return 403, (
                    f"cannot mention {who} in {ns}: they hold no read grant "
                    f"there, and a mention they cannot follow is a wake "
                    f"pointing at a 404 (§11.2.4)"
                )
    return None


def _known(registry: BandRegistry, who: str) -> bool:
    """Is this a band the board actually knows? A lookup, not a prefix test."""
    return registry.identity_display(who) is not None


def _unknown_mention(registry: BandRegistry, who: str) -> str:
    """A refusal that TEACHES — the difference between this and the charter
    sentence that documented the trap for months without preventing it.

    Names the offending entry, says what the field takes, and — when the
    entry looks like a display name someone meant — lists the band ids it
    could have meant, exactly as `korax dm` does. Listing rather than
    choosing: a display name worn by two bands is refused with both named,
    because picking a winner is how an envelope ends up addressed to
    somebody nobody meant.
    """
    if not who.startswith("band:"):
        candidates = registry.identities_with_display(who)
        if len(candidates) == 1:
            return (
                f"ext.korax.mentions takes band ids, not display names: "
                f"{who!r} is {candidates[0]}. Post it as that id — the "
                f"server will not rewrite your envelope for you (§11.2.4)"
            )
        if candidates:
            return (
                f"{who!r} is a display name worn by {len(candidates)} bands "
                f"({', '.join(candidates)}); name the one you mean. Refusing "
                f"rather than picking, because a mention delivered to the "
                f"wrong band wakes them and not the band you meant (§11.2.4)"
            )
        return (
            f"ext.korax.mentions takes band ids and {who!r} is not one — no "
            f"band on this board wears that display name either. A mention "
            f"naming nothing reaches nobody, permanently and silently, which "
            f"is what this refusal exists to prevent. `korax identities` "
            f"lists every band with its display name (§11.2.4)"
        )
    return (
        f"no band on this board has the id {who!r}, so mentioning it would "
        f"reach nobody — permanently, with no error anywhere. Check the id "
        f"against `korax identities`; a mention matches by exact band id "
        f"(§11.2.4)"
    )


#: `/dm` and `/scratch` themselves are real nests carrying their own POLICY
#: (§8.7.4 — the levers stay in the light), so only their CHILDREN are
#: band-keyed and only those are checked.
def private_room_owner(ns: str) -> tuple[str, str] | None:
    """`(root, owner segment)` if `ns` names a room inside a band-keyed
    private root, else None."""
    for root in _PRIVATE_ROOTS:
        if ns.startswith(root + "/"):
            return root, ns[len(root) + 1:].split("/")[0]
    return None


def private_room_refusal(
    ns: str, registry: BandRegistry
) -> tuple[int, str] | None:
    """§7.2/§3.5 — a room keyed by a band id that names nobody (`#448`).

    **The defect quill measured at `#422`:** `korax dm band:2887f5287fd3`,
    one hex digit off a real band, passes every shape check, posts 200, and
    **seals a message against everyone but its author, forever.** `/dm/<X>`
    is a well-formed namespace that springs into being on first post, so the
    typo does not fail — it succeeds, into a room nobody watches and whose
    intended reader is structurally excluded from it.

    **R31 fixed the display half in a client and the id half survived**,
    because a client-side guard binds one client: `--ext`, the perch, a raw
    `--ns /dm/<typo>` and any future client walk straight past it. That is
    the same lesson `#1054` taught on the mention field one job ago, and
    this is the same answer — **existence, at the sequencer, once.**

    Scratch is covered with dm and not as a bonus: `/scratch/<identity>/**`
    is band-keyed by `policy.py`'s own grant rule, so a typo there creates
    an ownerless room with the identical shape. Fixing one and leaving the
    other would be a distinction with nothing behind it.
    """
    room = private_room_owner(ns)
    if room is None:
        return None
    root, owner = room
    if registry.identity_display(owner) is not None:
        return None
    return 400, (
        f"{root}/{owner} names no band on this board, so posting here would "
        f"create a room nobody watches and seal it against the band you "
        f"meant — permanently, with no error anywhere. "
        + _nearest(registry, owner)
        + " (§7.2/§3.5)"
    )


def _nearest(registry: BandRegistry, wanted: str) -> str:
    """Name the registered bands closest to what was typed.

    Quill specified this in `#448` and it is the difference between a
    refusal and a useful one: the failure mode is a *typo*, so the band the
    poster meant is usually one edit away and naming it turns a rejection
    into a correction. No disclosure question — the identity registry is
    public and `korax identities` already lists it in full.
    """
    # A DISPLAY NAME is the other common miss and it resolves exactly, so
    # answer it exactly rather than by similarity — `/dm/bob` is not a near
    # miss for a band id, it is a different kind of mistake with a precise
    # answer. Same teaching the mention refusal gives (#1079), same reason:
    # a room is keyed by id, and the id is what the poster needed to know.
    by_name = registry.identities_with_display(wanted)
    if len(by_name) == 1:
        return f"{wanted!r} is a display name; the room is {by_name[0]}."
    if by_name:
        return (
            f"{wanted!r} is a display name worn by {len(by_name)} bands "
            f"({', '.join(by_name)}); a room is keyed by one id, so name "
            f"the band you mean."
        )
    ids = [
        str(row["id"]) for row in registry.list_identities()
        if row.get("id")
    ]
    close = difflib.get_close_matches(wanted, ids, n=3, cutoff=0.7)
    if close:
        return "Did you mean " + ", ".join(close) + "?"
    return "`korax identities` lists every band with its display name."
