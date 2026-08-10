"""The civic layer — pins, required reading, and acks (§4.4, §10.9, §10.10).

Everything here reduces to three questions the log can answer:

  1. What is canon *here, now*?  Canon-class PINs in force in a nest —
     a PIN is in force until something supersedes it (a replacement PIN
     at budget, or a retiring SUPERSEDE with `ext.retired`).
  2. What does acting on *this* require?  The transitive `requires`
     closure, expanded to the originating nest's `max_required_depth`,
     with truncation reported rather than silently capped.
  3. What has this identity attested to reading?  Acks are durable per
     (identity, target-version): every requirement is resolved to the
     *current* version of its document first, so an ack on a superseded
     version stops covering — supersession is exactly the event that
     should void the attestation (§4.4).

The server never tracks what anyone read; it checks attestations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .log import Log
from .models import Act, EdgeType, Envelope
from .nsglob import ns_matches
from .policy import PolicyTimeline


def current_version(log: Log, env_id: int, offset: int) -> int:
    """Follow `supersedes` forward to the live head of a document lineage
    at `offset`. Where several envelopes supersede the same target, the
    latest wins (it is the one a curator posted knowing the others)."""
    seen: set[int] = set()
    cur = env_id
    while cur not in seen:
        seen.add(cur)
        heirs = log.inbound(cur, EdgeType.SUPERSEDES, offset)
        if not heirs:
            return cur
        cur = max(h.id for h in heirs)
    return cur  # cycle guard — malformed lineage, stop where we are


def canon_pins(log: Log, ns: str, offset: int) -> list[Envelope]:
    """Canon-class PINs in force in exactly this nest at `offset`."""
    out = []
    for env in log.acts_in(Act.PIN, offset):
        if env.ns != ns:
            continue
        if not (isinstance(env.payload, dict) and env.payload.get("class") == "canon"):
            continue
        if log.inbound(env.id, EdgeType.SUPERSEDES, offset):
            continue  # replaced or retired — either way, out of force
        out.append(env)
    return sorted(out, key=lambda e: e.id)


def ack_set(log: Log, identity: str, offset: int) -> set[int]:
    """Every target the identity has acked, at any version. `acks` edges
    may ride on any act (§4.4), so this scans refs, not just ACK acts."""
    acked: set[int] = set()
    for env in log.upto(offset):
        if env.author != identity:
            continue
        acked.update(env.refs_of(EdgeType.ACKS))
    return acked


@dataclass
class Closure:
    """One requirement set: ids in `id` order, how each got there, and
    where expansion was cut at depth (§10.10 — never silent).

    `complete` is every document the closure required, acked or not;
    `unread` is the subset with no current-version ack. Both come from
    one pass over one ack set (§10.9) — the 409's `missing`, `required`
    and `onboard` are the same computation over different *scopes*, and
    the scopes are deliberate (JOB #385 D3). Callers project; only
    `onboard` serves `complete`, because it is the only surface whose
    scope is "everything you hold grants in" and therefore the only one
    where the full set answers a question a reader asked."""

    unread: list[int] = field(default_factory=list)
    via: dict[str, list[str]] = field(default_factory=dict)
    truncated: list[int] = field(default_factory=list)
    complete: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "unread": sorted(self.unread),
            "via": {k: sorted(v) for k, v in sorted(self.via.items())},
            "truncated": sorted(self.truncated),
        }

    def as_onboard_dict(self) -> dict:
        """§10.9 — the canon set in force, each entry marked read or
        unread, plus the unread projection every existing caller reads.

        `unread` keeps its exact prior meaning on purpose: both clients
        fetch documents by looping over it (cli.py, mcp server.py), so
        widening it would silently make every returning session
        re-download canon it has already acked. Marking is orientation;
        fetching is reading (JOB #385 D1)."""
        return {
            "canon": self.complete,
            "unread_count": len(self.unread),
            **self.as_dict(),
        }


class _Expander:
    """Accumulates requirement closures across seeds, resolving every
    node to its current version before expanding its `requires` edges."""

    def __init__(self, log: Log, offset: int):
        self.log = log
        self.offset = offset
        self.required: dict[int, set[str]] = {}  # id -> sources
        self.truncated: set[int] = set()
        self._depth_seen: dict[int, int] = {}  # id -> best (smallest) depth expanded at

    def add(self, doc_id: int, source: str, depth: int, max_depth: int) -> None:
        cur = current_version(self.log, doc_id, self.offset)
        self.required.setdefault(cur, set()).add(source)
        prior = self._depth_seen.get(cur)
        if prior is not None and prior <= depth:
            return  # already expanded at least this generously
        self._depth_seen[cur] = depth
        env = self.log.get(cur)
        if env is None:
            return
        prerequisites = env.refs_of(EdgeType.REQUIRES)
        if not prerequisites:
            return
        if depth >= max_depth:
            self.truncated.add(cur)  # has unexpanded requires — report, never cap silently
            return
        self.truncated.discard(cur)  # a shallower path expanded what a deeper one could not
        for pre in prerequisites:
            self.add(pre, f"requires:{cur}", depth + 1, max_depth)


def _closure_for_pins(
    expander: _Expander, log: Log, timeline: PolicyTimeline, ns: str, offset: int
) -> None:
    """Feed a nest's in-force canon pins into the expander, each pinned
    document expanded to that nest's depth budget."""
    _, pol = timeline.policy_at(ns, offset)
    for pin in canon_pins(log, ns, offset):
        for target in pin.refs_of(EdgeType.PINS):
            expander.add(target, f"pin:{pin.id}", 0, pol.max_required_depth)


def _finish(expander: _Expander, log: Log, identity: str, offset: int) -> Closure:
    acked = ack_set(log, identity, offset)
    closure = Closure()
    for doc_id, sources in sorted(expander.required.items()):
        env = log.get(doc_id)
        read = doc_id in acked
        closure.complete.append(
            {
                "id": doc_id,
                # a document the reader cannot resolve is still required —
                # report the gap rather than dropping the entry (§10.10)
                "ns": env.ns if env is not None else None,
                "read": read,
                "via": sorted(sources),
            }
        )
        if read:
            continue
        closure.unread.append(doc_id)
        closure.via[str(doc_id)] = sorted(sources)
    closure.truncated = sorted(expander.truncated)
    return closure


def onboard(log: Log, timeline: PolicyTimeline, offset: int, identity: str) -> dict:
    """§10.9 — the canon set in force across every namespace the identity
    holds grants in, each document marked read or unread at its current
    version.

    `unread` is still only what wants reading, so the amortization is
    unchanged — but a returning identity whose canon has not changed now
    learns *that*, instead of receiving nothing and having to guess
    whether nothing meant "current" or "broken" (JOB #385, FR4 of #280).
    Absent and empty were the same answer here; they are not the same
    question."""
    patterns = [
        pattern
        for grantee, pattern, _band in timeline.grants_at(offset)
        if grantee in (identity, "band:*")
    ]
    nests: set[str] = set()
    for env in log.acts_in(Act.PIN, offset):
        if env.ns.startswith("/scratch/"):
            continue  # reductions never source from scratch (§3.5)
        if any(ns_matches(p, env.ns) for p in patterns):
            nests.add(env.ns)
    expander = _Expander(log, offset)
    # board canon first, then the rest — §10.9's load-in order is id order,
    # and /korax/canon is seeded before any project nest by construction
    for ns in sorted(nests):
        _closure_for_pins(expander, log, timeline, ns, offset)
    result = _finish(expander, log, identity, offset)
    return {"identity": identity, **result.as_onboard_dict()}


def required(
    log: Log, timeline: PolicyTimeline, offset: int, env_id: int, identity: str
) -> dict:
    """§10.10 — the unmet closure for acting on one envelope: its own
    transitive `requires` plus its nest's canon pins, minus current acks."""
    env = log.get(env_id)
    if env is None or env.id > offset:
        raise LookupError(f"no envelope {env_id} at offset {offset}")
    _, pol = timeline.policy_at(env.ns, offset)
    expander = _Expander(log, offset)
    # the target itself is what you are acting on, not part of the list;
    # expand from it at depth 0 so its requires land at depth 1
    for pre in env.refs_of(EdgeType.REQUIRES):
        expander.add(pre, f"requires:{env_id}", 1, pol.max_required_depth)
    _closure_for_pins(expander, log, timeline, env.ns, offset)
    result = _finish(expander, log, identity, offset)
    return {"target": env_id, "identity": identity, **result.as_dict()}


def unmet_for_claim(
    log: Log,
    timeline: PolicyTimeline,
    offset: int,
    claim_ns: str,
    target_ids: tuple[int, ...],
    identity: str,
) -> tuple[list[int], list[int]]:
    """§4.4 enforcement — the reading list a CLAIM must have covered in a
    `require_acks` nest: the nest's canon pins plus each claimed target's
    transitive requires. Returns (missing ids, truncated ids)."""
    _, pol = timeline.policy_at(claim_ns, offset)
    expander = _Expander(log, offset)
    _closure_for_pins(expander, log, timeline, claim_ns, offset)
    for target_id in target_ids:
        env = log.get(target_id)
        if env is None:
            continue
        for pre in env.refs_of(EdgeType.REQUIRES):
            expander.add(pre, f"requires:{target_id}", 1, pol.max_required_depth)
    closure = _finish(expander, log, identity, offset)
    return sorted(closure.unread), closure.truncated
