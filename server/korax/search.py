"""Search and the neighbourhood walk (§11.x, JOB #386) — the board
becomes queryable.

Two read surfaces over the requester's already-filtered log. Neither
computes access: both are handed the output of `access.filter_log` and
consult it. That is not tidiness, it is the mechanism behind two
guarantees the brief asks for and neither surface could re-derive
correctly on its own:

  * **Blind rounds cannot leak here.** `access._blinded` resolves to the
    verdict "denied", and `filter_log` drops denied envelopes entirely
    rather than returning them for counting (#268 D2). A blinded
    envelope therefore never reaches a counter on any surface that
    routes this way — including this one, which did not exist when that
    decision was made.
  * **The seam and participation stay exactly as §8.7/§9.3 define them**,
    including for surfaces added later.

THE CONTENT/METADATA LINE (design #636 D2, ruled at #637)
---------------------------------------------------------
`q` is NEVER evaluated against an envelope the requester may not read.

To count a withheld envelope as *a match* you must run the query over
content you are enforcing they cannot see, and the count then publishes
a function of hidden bytes. That function is a decoder: ask
`q=secret`, `q=secret_a`, `q=secret_ab`… and read the payload out of a
mailbox you have no grant for, one character per request, without the
board ever showing you an envelope.

So exclusions here are counted by STRUCTURAL slice only — namespace,
type, author, grade, id-range — which is exactly the predicate `/read`
already applies to withheld envelopes, and the response says in words
that the query was not run against them. The general rule, adopted at
#637 for every future read surface carrying a content filter:
**metadata may be evaluated against what you cannot read; content may
not.**

THE BUDGET, NOT THE DEPTH, IS THE LOAD-BEARING LIMIT (#636 D4)
--------------------------------------------------------------
Measured on the live board at head 627 (561 readable envelopes, 925
edges): a depth-3 walk from the worst node returns 178 envelopes, 32%
of everything, on a feature whose purpose is reducing what you must
read. Depth 2 returns a median of 12. But depth is a proxy for cost and
the graph densifies as `part-of`/`corroborates` adoption grows — a cap
correct at depth 3 today is wrong at depth 3 later and nothing
announces it. `MAX_NODES` is stable under densification; the depth cap
is a floor under pathological fan-out. Truncation is reported, never
silent (§10.10's discipline).
"""

from __future__ import annotations

from typing import Any
from collections.abc import Callable

from .counters import Scope, withheld_counts
from .log import Log
from .models import Envelope

# §11.x — the walk's bounds. DEFAULT_DEPTH is what a caller gets unasked;
# MAX_DEPTH is the ceiling a caller may request; MAX_NODES is the one that
# actually holds, and the one to raise or lower when the graph changes.
DEFAULT_DEPTH = 2
MAX_DEPTH = 3
MAX_NODES = 60

EXCERPT_RADIUS = 90


def _summary(env: Envelope, dump: Callable[[Envelope], dict[str, Any]]) -> dict[str, Any]:
    """An envelope's card: enough to decide whether to fetch it, never a
    projection presented as the whole (§13)."""
    d = dump(env)
    return {
        k: d[k]
        for k in ("id", "ts", "author", "band", "ns", "type", "grade", "refs")
        if k in d
    }


def _excerpt(payload: Any, needle: str) -> str | None:
    """A window around the hit. Drawn only from an envelope the requester
    may read, so it discloses nothing the full fetch would not — which is
    why it is safe to include and why it must never be built for a
    withheld envelope."""
    if not isinstance(payload, str) or not needle:
        return None
    i = payload.lower().find(needle.lower())
    if i < 0:
        return None
    start = max(0, i - EXCERPT_RADIUS)
    end = min(len(payload), i + len(needle) + EXCERPT_RADIUS)
    return ("…" if start else "") + payload[start:end] + ("…" if end < len(payload) else "")


def _haystack(env: Envelope) -> str:
    """POLICY and friends carry structured payloads; searching their JSON
    text is more useful than skipping them and is not a disclosure —
    the requester can already read the envelope whole."""
    if isinstance(env.payload, str):
        return env.payload
    try:
        import json

        return json.dumps(env.payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def search(
    visible: Log,
    q: str,
    structural: Callable[[Envelope], bool],
    withheld: list[list[Envelope]],
    dump: Callable[[Envelope], dict[str, Any]],
    limit: int,
    *,
    scope: Scope,
) -> dict[str, Any]:
    """Substring over payloads, newest first, no relevance scoring.

    `structural` is the caller's metadata predicate (ns/type/author/
    grade/id-range). It is applied to BOTH the visible envelopes and the
    withheld ones; `q` is applied to the visible ones ONLY. That asymmetry
    is the whole of D2 and the reason the counts below cannot be used as
    an oracle: they do not vary with `q`.

    Ordering is `id`-descending — honest and cheap. No scoring in v1:
    curation lives in render (#255), and a relevance function is the thin
    end of the embeddings this job puts out of scope.
    """
    needle = q.lower()
    hits = [
        e for e in visible.envelopes
        if structural(e) and needle in _haystack(e).lower()
    ]
    hits.sort(key=lambda e: e.id, reverse=True)
    truncated = len(hits) > limit
    out = []
    for env in hits[:limit]:
        item = _summary(env, dump)
        item["excerpt"] = _excerpt(env.payload, q)
        out.append(item)
    return {
        "q": q,
        "results": out,
        "returned": len(out),
        "truncated_at_limit": truncated,
        # §9.3, as amended at #637: the slice is structural, the query is
        # not run against what you cannot read, and the response says so
        # rather than leaving the reader to assume either way.
        "withheld_note": (
            "counts below are envelopes withheld from you within this "
            "structural slice; whether any of them match your query is "
            "not computed"
        ),
        # §9.3 — counted by NAMESPACE scope only (#667, ruled #665).
        # `structural` still scopes what is SERVED; it no longer scopes what
        # is counted. It carried ns/type/author/grade/id-range, and every
        # dimension but the namespace was a predicate the requester chose
        # for records they cannot read (#645).
        **withheld_counts(scope=scope, sealed=withheld[0], private=withheld[1]),
    }


def neighbourhood(
    visible: Log,
    root_id: int,
    depth: int,
    withheld: list[list[Envelope]],
    dump: Callable[[Envelope], dict[str, Any]],
) -> dict[str, Any]:
    """The edge-connected component around an envelope, both directions,
    grouped by hop, each entry carrying the edges that put it there.

    Carrying the edges is what makes this a corroboration tool rather
    than a pile: the caller sees WHY a node is present and can follow the
    reason rather than re-deriving it.

    Withheld neighbours are reported as ONE aggregate for the whole walk,
    never per hop (#636 D5). A per-hop count localises hidden material to
    a named envelope's immediate edges — "one withheld at depth 1 from
    #385" says a private envelope cites #385 specifically — and no
    existing surface is that precise; `/read`'s counts are per-namespace
    and coarse by construction. Where the brief's instruction and §8.3's
    granularity rule disagreed, the narrower disclosure won.
    """
    if visible.get(root_id) is None:
        raise LookupError(f"no envelope {root_id}")
    depth = max(1, min(depth, MAX_DEPTH))

    by_id = {e.id: e for e in visible.envelopes}
    adjacency: dict[int, dict[int, list[str]]] = {}
    for env in visible.envelopes:
        for ref in env.refs:
            if ref.id not in by_id:
                continue  # unresolvable within this requester's view
            adjacency.setdefault(env.id, {}).setdefault(ref.id, []).append(
                f"{ref.edge.value}->"
            )
            adjacency.setdefault(ref.id, {}).setdefault(env.id, []).append(
                f"<-{ref.edge.value}"
            )

    seen = {root_id}
    frontier = {root_id}
    hops: list[dict[str, Any]] = []
    budget_hit = False
    for hop in range(1, depth + 1):
        nxt: dict[int, list[str]] = {}
        for node in sorted(frontier):
            for neighbour, edges in adjacency.get(node, {}).items():
                if neighbour in seen:
                    continue
                nxt.setdefault(neighbour, []).extend(edges)
        if not nxt:
            break
        entries = []
        for nid in sorted(nxt, reverse=True):
            if len(seen) >= MAX_NODES:
                budget_hit = True
                break
            seen.add(nid)
            item = _summary(by_id[nid], dump)
            item["edges"] = sorted(set(nxt[nid]))
            entries.append(item)
        if entries:
            hops.append({"depth": hop, "nodes": entries})
        if budget_hit:
            break
        frontier = set(nxt)

    # the aggregate: withheld envelopes carrying an edge to anything in the
    # component, counted once for the walk. No `q` exists here to leak, but
    # the same rule applies — this is structure, not content.
    return {
        "root": root_id,
        "depth": depth,
        "nodes": sum(len(h["nodes"]) for h in hops),
        "hops": hops,
        # never a silent cap (§10.10) — a caller that cannot tell it was
        # truncated will read a bounded walk as a complete one
        "truncated": budget_hit,
        "node_budget": MAX_NODES,
        # §9.3 — BOARD scope (#667, ruled #665; confirmed at #790).
        #
        # This counter used to ask "how many withheld envelopes touch the
        # walked component", where both the root and the depth are chosen by
        # the requester. That is a ref predicate, which the ruling drops —
        # and it was the FINER oracle, not a narrower one. `seen` starts as
        # `{root_id}` and grows only through edges the requester can see, so
        # a root with no visible neighbours leaves `seen == {root_id}` and
        # the count became exactly "how many hidden envelopes cite #N", for
        # any N. Envelope ids are dense and public, so the whole id space is
        # enumerable by a counter loop, and no knowledge of who exists is
        # needed.
        **withheld_counts(scope=Scope.whole_board(), sealed=withheld[0],
                          private=withheld[1]),
        "withheld_note": (
            "board-scoped, not walk-scoped — the walk's root and depth are "
            "chosen by the caller, so counting the component would say how "
            "many hidden envelopes cite a named envelope, and at depth 1 on "
            "an isolated root it would say it exactly"
        ),
    }
