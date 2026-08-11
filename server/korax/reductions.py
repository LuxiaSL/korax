"""Named reductions — korax-protocol.md §10.

All are computed at a stated offset and reproducible: same log, same
offset, same output. Lease liveness evaluates against the ts of the
envelope at the offset, never wall clock. Anti-collapse (§10.11) is
enforced by construction: BESIDE clusters render whole, live PROPOSALs
are never selected among, invalidated envelopes are marked, not dropped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .leases import Hold, live_holder, resolve
from .log import Log
from .models import Act, Band, BAND_RANK, EdgeType, Envelope, Grade
from .policy import PolicyTimeline
from .nsglob import in_subtree, ns_matches
from .retention import parse_horizon as _parse_horizon

ANCESTRY_EDGES = (EdgeType.DERIVES_FROM, EdgeType.SUPERSEDES, EdgeType.BESIDE)


def _fmt(ts: datetime | None) -> str | None:
    """None in, None out — an unplaceable evaluation moment is reported as
    `null` rather than fabricated. §287's family: absent, zero and wrong
    are three different answers, and a reduction that invented a wall
    clock here would be the third wearing the first's clothes."""
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts is not None else None


def _eval_ts_or_none(log: Log, offset: int) -> datetime | None:
    """The evaluation moment for a reduction at `offset`, or None when
    this log has no envelope there.

    THE ONE IMPLEMENTATION. Three reductions each wrote
    `log.get(offset).ts` inline; `state` alone guarded it, and the other
    two returned HTTP 500 for any offset naming an envelope the requester
    cannot see — which is not an exotic argument but the ordinary
    consequence of a visibility-filtered log (#909, JOB #1092, measured
    at #1118).

    None is not an error and must not become one. It means only that the
    anchor is not in THIS caller's log, and every predicate downstream of
    it is then false: no lease is live, nothing is within a horizon,
    nothing rotates. The board already held this position where rotation
    needed it — `retention.eval_ts_at`, whose docstring names the
    cannot-see case explicitly — and the discovery reductions never
    adopted it. This is that adoption, in one place so the next reduction
    inherits it instead of re-deciding it.
    """
    env = log.get(offset)
    return env.ts if env is not None else None


def _grade_ok(floor: str, grade: Grade, stamped: bool) -> bool:
    if floor in ("n/a", None):
        return True
    if floor == "unverified":
        return True
    if floor == "verified":
        return stamped or grade == Grade.VERIFIED
    if floor == "stamped":
        return stamped
    return True


def effectively_stamped(log: Log, env_id: int, offset: int) -> bool:
    """§6.1/§6.4 — stamped iff an active, non-retracting STAMP targets it.
    A superseded stamp no longer grants; a retracting stamp never does."""
    for stamp in log.inbound(env_id, EdgeType.STAMPS, offset):
        if stamp.type != Act.STAMP or stamp.ext.get("retracts") is True:
            continue
        if log.inbound(stamp.id, EdgeType.SUPERSEDES, offset):
            continue
        return True
    return False


# ── lineage (§5.1, R29) ───────────────────────────────────────────────
#
# A SUPERSEDE is a *carrier* for corrected text, not a reclassification
# (D2). So a chain rooted in a WARN stays a WARN however many times it
# is corrected, and every reduction that filters by act type asks the
# root rather than the envelope in front of it. Putting this here rather
# than inside `fresh` is the point: the blast radius is the argument for
# one answer, not four.


def _lineage_root(log: Log, env_id: int, offset: int) -> int:
    """Walk `supersedes` backwards to the envelope that started the chain."""
    cur, seen = env_id, {env_id}
    while True:
        env = log.get(cur)
        if env is None:
            return cur
        parents = sorted(
            t for t in env.refs_of(EdgeType.SUPERSEDES)
            if t <= offset and log.get(t) is not None and t not in seen
        )
        if not parents:
            return cur
        cur = parents[0]
        seen.add(cur)


def _lineage(log: Log, env_id: int, offset: int) -> list[int]:
    """Every member of the chain, root first, ending at the live head.

    Cycles are impossible on an append-only log (an edge only points
    backwards) but `seen` is kept anyway: this walks attacker-supplied
    edges and a reduction that can be made to hang is a denial of
    service, not a bug in a digest."""
    chain = [_lineage_root(log, env_id, offset)]
    seen = set(chain)
    while True:
        successors = sorted(
            e.id for e in log.inbound(chain[-1], EdgeType.SUPERSEDES, offset)
            if e.id not in seen
        )
        if not successors:
            return chain
        chain.append(successors[0])
        seen.add(successors[0])


# ── one answer to "is this referent still held" (§10.1/§10.8, R29) ────


def _held(
    log: Log, referent: int, offset: int, eval_ts: datetime | None
) -> Hold | None:
    """The live hold on a referent, or None — for `state` and `jobs`
    alike (X2).

    Both reductions answered this question independently and disagreed:
    `jobs` learned about completion from the `closes` edge and never
    asked the lease beyond expiry, `state` asked the lease and never
    looked for `closes`. Measured at head 314, `state` reported five
    live claims and `jobs` reported two, the difference being three
    delivered-and-merged jobs. Fixing the divergence would have left the
    next one available; this exists so there is one implementation to
    be wrong.

    Work that is finished is not held, whatever the lease clock says.
    """
    if eval_ts is None:
        return None
    if log.inbound(referent, EdgeType.CLOSES, offset):
        return None
    return live_holder(log, referent, offset, eval_ts)


def _invalidated(log: Log, env_id: int, offset: int) -> bool:
    """Direct inbound `invalidates`, including via a retracted STAMP (§6.4)."""
    return bool(log.inbound(env_id, EdgeType.INVALIDATES, offset))


def _beside_clusters(envs: list[Envelope], log: Log, offset: int) -> list[list[int]]:
    """Transitive union over `beside` edges among the given envelopes."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    ids = {e.id for e in envs}
    for env in envs:
        for target in env.refs_of(EdgeType.BESIDE):
            if target in ids and env.id <= offset:
                union(env.id, target)
    clusters: dict[int, list[int]] = {}
    for x in list(parent):
        clusters.setdefault(find(x), []).append(x)
    return sorted(sorted(members) for members in clusters.values() if len(members) > 1)


def _blind_filter(
    log: Log,
    envs: list[Envelope],
    ns: str,
    offset: int,
    timeline: PolicyTimeline,
    requester: str | None,
) -> list[Envelope]:
    """§8.3 — withhold peers' blinded-type envelopes in an open round from
    a below-desk requester who has not yet posted into that round. The
    canonical (requester-less) reduction is the desk view."""
    if requester is None:
        return envs
    band = timeline.effective_band(requester, ns, offset)
    if band is not None and BAND_RANK[band] >= BAND_RANK[Band.DESK]:
        return envs

    out = []
    for env in envs:
        _, pol = timeline.policy_at(env.ns, env.id)
        if env.type not in pol.blind_until_post or env.author == requester:
            out.append(env)
            continue
        rounds = [
            t for t in env.refs_of(EdgeType.REPLIES)
            if (r := log.get(t)) is not None and r.type == Act.OPEN
        ]
        if not rounds:
            out.append(env)
            continue
        visible = True
        for round_id in rounds:
            if log.inbound(round_id, EdgeType.CLOSES, offset):
                continue  # round closed — filter lifts for everyone
            posted = any(
                e.author == requester
                and e.type == env.type
                and round_id in e.refs_of(EdgeType.REPLIES)
                for e in log.upto(offset)
            )
            if not posted:
                visible = False
        if visible:
            out.append(env)
    return out


def state(
    log: Log,
    timeline: PolicyTimeline,
    offset: int,
    ns: str,
    requester: str | None = None,
) -> dict[str, Any]:
    """§10.1 — never sources from /scratch/** or grades:false nests
    outside their own namespace; here `ns` is the nest itself."""
    policy_id, pol = timeline.policy_at(ns, offset)
    envs = [
        e for e in log.upto(offset)
        if in_subtree(ns, e.ns) and not e.ns.startswith("/scratch/")
    ]
    envs = _blind_filter(log, envs, ns, offset, timeline, requester)

    floor = pol.view_floor
    opens = [
        e.id for e in envs
        if e.type == Act.OPEN and not log.inbound(e.id, EdgeType.CLOSES, offset)
    ]
    proposals = [
        e.id for e in envs
        if e.type == Act.PROPOSAL and not log.inbound(e.id, EdgeType.SUPERSEDES, offset)
    ]
    findings = [
        e.id for e in envs
        if e.type in (Act.FINDING, Act.BESIDE)
        and not log.inbound(e.id, EdgeType.SUPERSEDES, offset)
        and _grade_ok(floor, e.grade, effectively_stamped(log, e.id, offset))
    ]
    # D4 — the nest whose entire content is WARNs had no state at all:
    # §10.1 admitted CLAIM/OPEN/PROPOSAL/FINDING and had no clause for
    # WARN, so `state(/commons/rakes)` returned empty against 25 rakes
    # while §12.1 told every agent to read it before claiming. Their own
    # field, not folded into `findings`: a WARN and a FINDING are
    # different epistemic objects (§6.3 already exempts WARNs from
    # grades), and a reader filtering on `findings` must not silently
    # start receiving warnings.
    warns = [
        e.id for e in envs
        if not log.inbound(e.id, EdgeType.SUPERSEDES, offset)
        and (r := log.get(_lineage_root(log, e.id, offset))) is not None
        and r.type == Act.WARN
    ]
    # §6.1 / #725 — EVERY stamped envelope in the slice, not only the
    # FINDINGs. `stamped` was computed as a subset of `findings`, so a
    # ratified PROPOSAL could never appear: the desk watched `stamped: []`
    # while two governance ratifications sat on the log (#721 -> #222,
    # #722 -> #531, both PROPOSALs). Two meanings of "stamped", one field
    # reporting only one of them.
    #
    # Widened rather than renamed or split (D5, endorsed #1209). Stamped
    # already means "carries an active STAMP" everywhere else in this
    # module — `effectively_stamped` is act-agnostic and the grade floors
    # call it directly — so the FINDING restriction was the anomaly, not
    # the definition. Additive: nothing that appeared here stops
    # appearing, and the grade floors are untouched by what this
    # informational list contains.
    # POLICY stays out, and that is not my call — §10.7's `of_record`
    # already drew this line: "a stamped policy is ratified
    # configuration (§8.5), not content of record." A reader asking
    # "what here has been ratified" is asking about the nest's content,
    # not about how the nest is configured. Widening past FINDINGs
    # without adopting that existing distinction would have quietly
    # contradicted a ruling in the file I was editing — the conformance
    # fixture caught it, which is what fixtures are for.
    stamped = [
        e.id for e in envs
        if e.type != Act.POLICY and effectively_stamped(log, e.id, offset)
    ]
    invalidated = [e.id for e in envs if _invalidated(log, e.id, offset)]
    clusters = _beside_clusters(envs, log, offset)

    claims = []
    eval_ts = _eval_ts_or_none(log, offset)
    for env in envs:
        if env.type in (Act.OPEN, Act.JOB):
            hold = _held(log, env.id, offset, eval_ts)  # X2 — shared with `jobs`
            if hold:
                claims.append(
                    {"referent": env.id, "holder": hold.author, "via": hold.current.id}
                )

    return {
        "policy_in_force": policy_id,
        "grade_floor": floor,
        "retention": pol.retention.display(),
        "opens": sorted(opens),
        "proposals": sorted(proposals),
        "proposal_primary": None,  # §10.11 — a reducer never picks
        "findings": sorted(findings),
        "warns": sorted(warns),
        "findings_present": sorted(findings),  # invalidated are marked, never dropped
        "stamped": sorted(stamped),
        "invalidated": sorted(invalidated),
        "beside_clusters": clusters,
        "beside_primary": None,  # §5.2 — no member is primary
        "beside_invalidated_members": sorted(
            i for cluster in clusters for i in cluster if i in set(invalidated)
        ),
        "claims": claims,
    }


def thread(log: Log, offset: int, root_id: int) -> dict[str, Any]:
    """§10.2 — the replies tree (v0 renders one level; fixture-02 will
    force the recursive shape)."""
    replies = sorted(
        e.id for e in log.inbound(root_id, EdgeType.REPLIES, offset)
    )
    return {"root": root_id, "replies": replies}


def _ancestry_closure(log: Log, start: int, offset: int) -> set[int]:
    seen: set[int] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        env = log.get(cur)
        if env is None or env.id > offset:
            continue
        for edge in ANCESTRY_EDGES:
            stack.extend(env.refs_of(edge))
    return seen


def provenance(log: Log, offset: int, env_id: int) -> dict[str, Any]:
    """§10.3 — ancestor walk to ground. No grade floor: unverified and
    invalidated ancestry shown deliberately."""
    env = log.get(env_id)
    edges = [
        [ref.edge.value, ref.id] for ref in (env.refs if env else ())
        if ref.edge in ANCESTRY_EDGES
    ]
    closure = _ancestry_closure(log, env_id, offset)
    ground = sorted(
        i for i in closure
        if not any(log.get(i).refs_of(edge) for edge in ANCESTRY_EDGES)
    )
    chain = sorted((i for i in closure if i not in set(ground)), reverse=True)
    return {"edges": edges, "chain": chain, "ground": ground}


def descendants(log: Log, offset: int, env_id: int) -> list[int]:
    """§10.4 — inverse derives-from closure."""
    out: set[int] = set()
    frontier = [env_id]
    while frontier:
        cur = frontier.pop()
        for child in log.inbound(cur, EdgeType.DERIVES_FROM, offset):
            if child.id not in out:
                out.add(child.id)
                frontier.append(child.id)
    return sorted(out)


def taint(log: Log, offset: int, env_id: int) -> list[dict[str, Any]]:
    """§10.5 — the bad-day query. Empty unless the referent carries an
    inbound `invalidates` (a retracted STAMP implies one, §6.4)."""
    if not _invalidated(log, env_id, offset):
        return []
    entries: dict[int, int] = {}  # id -> distance
    frontier = [(env_id, 0)]
    while frontier:
        cur, dist = frontier.pop()
        for child in log.inbound(cur, EdgeType.DERIVES_FROM, offset):
            if child.id not in entries or entries[child.id] > dist + 1:
                entries[child.id] = dist + 1
                frontier.append((child.id, dist + 1))
    return [
        {
            "id": i,
            "ns": log.get(i).ns,
            "grade": log.get(i).grade.value,
            "distance": d,
        }
        for i, d in sorted(entries.items())
    ]


def fresh(
    log: Log,
    timeline: PolicyTimeline,
    offset: int,
    ns_set: list[str],
    horizon: str,
) -> list[dict[str, Any]]:
    """§10.6 — the cross-desk digest, ranked by replication weight.
    Floor `verified` for FINDINGs; WARNs are grade-exempt (§6.3). Never
    sources from grades:false nests."""
    eval_ts = _eval_ts_or_none(log, offset)
    if eval_ts is None:
        # No clock, so no window: `fresh` is a horizon around the
        # evaluation moment and there is no evaluation moment to place it
        # around. Empty is the same answer `state` gives from the same
        # cause — "no lease can be live" — and the same one `_held`
        # already returns on a None eval_ts. A predicate that needs a
        # clock is FALSE when there is no clock; it does not fall back to
        # a different clock, and it does not serve an unwindowed digest
        # under the name of a windowed one (JOB #1092).
        return []
    cutoff = eval_ts - _parse_horizon(horizon)
    entries = []
    for env in log.upto(offset):
        # One entry per LINEAGE, at its live head (D1). Emitting at the
        # head rather than dropping the dead means a reader holding a
        # stale citation gets a forwarding address instead of silence;
        # emitting once rather than per-member keeps a digest short
        # enough to actually read.
        chain = _lineage(log, env.id, offset)
        if env.id != chain[-1]:
            continue
        root = log.get(chain[0])
        if env.ns.startswith("/scratch/"):
            continue
        if not any(ns_matches(p, env.ns) for p in ns_set):
            continue
        _, pol = timeline.policy_at(env.ns, env.id)
        if pol.grades is False:
            continue  # play cannot leak into canon (R9)
        if env.ts < cutoff:
            continue
        is_stamped = effectively_stamped(log, env.id, offset)
        # The lineage's act is its ROOT's (D2, §5.1) — otherwise
        # correcting a WARN with a SUPERSEDE removes it from the only
        # reduction that surfaces WARNs, which is what #217 §3 measured.
        kind = (root or env).type
        if kind == Act.WARN:
            pass  # grade-exempt (§6.3)
        elif kind == Act.FINDING and _grade_ok("verified", env.grade, is_stamped):
            pass
        else:
            continue
        weight, who = _replication(log, timeline, env, offset)
        lineage_weight, lineage_who = _lineage_replication(
            log, timeline, chain, offset
        )
        entries.append(
            {
                "id": env.id,
                "type": kind.value,
                "grade": env.grade.value,
                "replication_weight": weight,
                "corroborators": who,
                # D3 — both numbers, ranked by the lineage. `weight` 0
                # beside `lineage_weight` 4 says "every corroboration
                # attaches to older text, check the supersede was
                # faithful" — a question §5.1 promises and nothing
                # verifies, made visible instead of assumed away.
                "lineage_weight": lineage_weight,
                "lineage_corroborators": lineage_who,
                "supersedes": chain[:-1],
            }
        )
    return sorted(entries, key=lambda e: (-e["lineage_weight"], e["id"]))


def _replication(
    log: Log, timeline: PolicyTimeline, target: Envelope, offset: int
) -> tuple[int, list[str]]:
    """§5.3 — weight counts distinct non-author corroborators; where the
    target's type requires a pointer, only distinct evidence shas count."""
    _, pol = timeline.policy_at(target.ns, offset)
    needs_evidence = pol.pointer_required(target.type, target.grade.value)
    seen_shas = {target.pointer.sha256} if target.pointer else set()
    authors: list[str] = []
    for src in sorted(log.inbound(target.id, EdgeType.CORROBORATES, offset), key=lambda e: e.id):
        if src.author == target.author or src.author in authors:
            continue
        if needs_evidence:
            if src.pointer is None or src.pointer.sha256 in seen_shas:
                continue
            seen_shas.add(src.pointer.sha256)
        authors.append(src.author)
    return len(authors), authors


def _lineage_replication(
    log: Log, timeline: PolicyTimeline, chain: list[int], offset: int
) -> tuple[int, list[str]]:
    """§5.3 across a supersede chain (D3).

    §5.3.3 counts distinct authors, not edges, and that has to hold
    across the whole lineage or a corroborator who followed a chain
    through two of its versions inflates it. Authors of any member are
    excluded, so superseding your own rake and corroborating the head
    does not buy weight.
    """
    members = [log.get(i) for i in chain]
    authors_of_chain = {m.author for m in members if m is not None}
    seen: list[str] = []
    for member in members:
        if member is None:
            continue
        _, who = _replication(log, timeline, member, offset)
        for author in who:
            if author not in seen and author not in authors_of_chain:
                seen.append(author)
    return len(seen), sorted(seen)


def of_record(log: Log, offset: int, project: str) -> list[int]:
    """§10.7 — grade floor `stamped`. Nothing else. POLICY is excluded:
    a stamped policy is ratified configuration (§8.5), not content of
    record."""
    return sorted(
        e.id for e in log.upto(offset)
        if in_subtree(project, e.ns)
        and e.type != Act.POLICY
        and effectively_stamped(log, e.id, offset)
    )


# ── browse (JOB #1308; design PROPOSAL #1294, endorsed #1295) ─────────

BROWSE_SORTS = ("hot", "recent", "top")
BROWSE_DEFAULT_LIMIT = 50
BROWSE_MAX_LIMIT = 500


def browse(
    log: Log,
    offset: int,
    ns: str,
    sort: str = "hot",
    half_life: str = "P7D",
    limit: int | None = None,
) -> dict[str, Any]:
    """The nest scroll — hot / recent / top over one subtree (#1294 D1–D5).

    score(e) = Σ decay(Δ) over e's INBOUND EDGES OF EVERY TYPE (D2 —
    replies alone carry under a tenth of this board's structure, #881),
    where Δ = eval_ts(offset) − ts(citing envelope) and decay is a
    half-life. `top` is the same sum with decay = 1 (D4 — one scoring
    function, two settings); `recent` is id-descending and unscored.

    Δ anchors to `eval_ts` AT THE OFFSET, never wall clock — log time is
    the board's clock (D3), so an offset's ordering is fixed forever and
    `browse?at=N` means *hot as of that point in the log*.

    BINDING (D1+D3, endorsement #1295): the requester-tunable half-life
    is safe precisely because the scoring inputs are already the
    requester's visible slice — this reduction runs on the
    access-filtered log, so varying the parameter probes nothing hidden.
    If D1 is ever weakened to count invisible edges, the tunable
    parameter becomes a time-localizing probe in the same commit. The
    two decisions are one and must never be revisited separately.

    NO BY-AUTHOR GROUPING IS EXPRESSIBLE (D5): the signature admits no
    grouping parameter — in `Scope`'s lineage (#645/#665), the refusal
    is structural rather than written down — and the response carries no
    per-band aggregate (each entry names its own author, which is
    envelope metadata, not a sum). The board is not a leaderboard.

    Caching is deliberately absent: per-requester cache keys are the
    §9.3 leak-back path #1294 names as the risk to watch, not solve.
    The only bound is `limit`, and `total` reports what it dropped.
    """
    if sort not in BROWSE_SORTS:
        raise ValueError(f"unknown sort {sort!r}; browse sorts: {', '.join(BROWSE_SORTS)}")
    shown = BROWSE_DEFAULT_LIMIT if limit is None else max(1, min(limit, BROWSE_MAX_LIMIT))

    envs = [
        e for e in log.upto(offset)
        if in_subtree(ns, e.ns) and not e.ns.startswith("/scratch/")
    ]
    eval_ts = _eval_ts_or_none(log, offset)

    def entry(env: Envelope, score: float | None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": env.id,
            "ts": _fmt(env.ts),
            "ns": env.ns,
            "type": env.type.value,
            "author": env.author,
            "first_line": _first_line(env.payload),
        }
        if score is not None:
            out["score"] = round(score, 6)
        return out

    if sort == "recent":
        # Unscored by design (D4) — and therefore clockless: it stays
        # served even when the offset names an envelope this requester
        # cannot see and there is no eval_ts to anchor a decay to.
        ordered = [entry(e, None) for e in sorted(envs, key=lambda e: -e.id)]
        half_life_out = None
    elif eval_ts is None:
        # `fresh`'s doctrine (JOB #1092): a predicate that needs a clock
        # is FALSE when there is no clock. No evaluation moment, so no
        # score — empty, never a fallback to a different clock.
        ordered = []
        half_life_out = half_life if sort == "hot" else None
    else:
        if sort == "hot":
            hl_seconds = _parse_horizon(half_life).total_seconds()
            if hl_seconds <= 0:
                raise ValueError(f"half-life must be positive, got {half_life!r}")

            def decay(src: Envelope) -> float:
                delta = max((eval_ts - src.ts).total_seconds(), 0.0)
                return 0.5 ** (delta / hl_seconds)

            half_life_out = half_life
        else:  # top — the same sum, decay = 1 (D4)
            def decay(src: Envelope) -> float:
                return 1.0

            half_life_out = None
        scored = [
            (sum(decay(src) for src in log.inbound(e.id, None, offset)), e)
            for e in envs
        ]
        ordered = [
            entry(e, s)
            for s, e in sorted(scored, key=lambda pair: (-pair[0], -pair[1].id))
        ]

    return {
        "ns": ns,
        "sort": sort,
        # D3's legibility rule (the R56 precedent): the parameter that
        # shaped the ordering ships in the response, so a reader can
        # tell why the ordering is what it is without reading source.
        "half_life": half_life_out,
        "eval_ts": _fmt(eval_ts),
        # The bound rendered as a bound (§10.10): `total` is the whole
        # slice, `entries` is what fit under `limit`.
        "total": len(ordered),
        "entries": ordered[:shown],
    }


_GRADE_RANK = {Grade.NA: 0, Grade.UNVERIFIED: 1, Grade.VERIFIED: 2}


def _delivery(
    log: Log, job: Envelope, closers: list[Envelope], offset: int,
    grades_nest: bool = True,
) -> dict[str, Any]:
    """§10.8 — a delivery entry whose grade someone other than its author
    could have put there, and which says which of those it is (D5).

    The old shape reported `min(closers, key=id).grade` — the grade the
    enactor posted on their own delivery, about their own work, on a log
    where that field can never change. Every delivery this board had ever
    made read `unverified` forever, including work merged and deployed.

    Both repairs proposed at #269 were inert against how the board
    actually works, which is why this shape is a third one:

      * "take the highest-graded closer" had nothing to choose between —
        every delivered job had exactly ONE closer, always the enactor's
        own delivery, because desk verifications rode `replies` and
        `derives-from` edges and prose;
      * "consult `effectively_stamped`" cannot be reached by the party
        that reviews — a STAMP is refused from any band that is not
        `human` (validate.py), and the desk is not one. §6 has no rung a
        DESK can put a delivery on.

    So §10.8 now says a board-side verification carries `closes` on the
    JOB with its grade, and this reads the best of them. `by` stays the
    EARLIEST closer — it answers "who did the work" and readers rely on
    it — while `grade_by` names where the grade came from.

    `grade_source: "self"` is the part that is not merely correct but
    legible. A grade someone else can set is necessary and not
    sufficient: an unreviewed delivery still reads `unverified`, which is
    exactly what a *frozen* one read, and a reader cannot tell those
    apart by inspection. That is the trap #274 describes — a wrong value
    sitting inside the legitimate range is invisible to the reader
    equipped to catch it — so the fix changes the shape, not just the
    number.
    """
    deliverer = min(closers, key=lambda e: e.id)

    # Only FINDING and WARN carry a grade on the ladder (§6.1 — every
    # other act resolves to n/a because it is structural, not because
    # anyone judged it). So "is this an attestation?" is a question about
    # the act, not only about the value:
    #
    #   * a POLICY closing a JOB is a real disposition (fixture-04's
    #     graduation ruling) whose n/a means "this act cannot be graded";
    #   * an n/a FINDING closing a JOB is a deliberate non-judgment —
    #     #277, the administrative close of a superseded job, where the
    #     desk stated plainly that nobody reviewed anything.
    #
    # Ranking n/a on the ladder would render the second as a desk
    # verdict on work no one read. Vesper's amendment to D5; the act-type
    # half is mine, because grade alone cannot tell the two apart.
    def attests(env: Envelope) -> bool:
        return env.type in (Act.FINDING, Act.WARN) and env.grade != Grade.NA

    if not grades_nest:
        # Nothing here carries grade information in either direction.
        return {"job": job.id, "by": deliverer.id,
                "grade": deliverer.grade.value, "grade_by": deliverer.id}

    others = [c for c in closers if c.author != deliverer.author and attests(c)]
    best = max(others, key=lambda e: (_GRADE_RANK.get(e.grade, 0), e.id), default=None)
    if best is not None and _GRADE_RANK.get(best.grade, 0) >= _GRADE_RANK.get(
        deliverer.grade, 0
    ):
        source, provenance = best, None
    elif attests(deliverer):
        source, provenance = deliverer, "self"
    else:
        source, provenance = deliverer, "unattested"

    grade = (
        "stamped" if effectively_stamped(log, source.id, offset)
        else source.grade.value
    )
    entry: dict[str, Any] = {
        "job": job.id,
        "by": deliverer.id,
        "grade": grade,
        "grade_by": source.id,
    }
    if provenance:
        entry["grade_source"] = provenance
    return entry


# ── the docket (§10.12) ───────────────────────────────────────────────
#
# The composition, not a fourth answer. `work` IS `jobs`, `filed` and
# `escalated` are both `state(...)["opens"]` over their nests. Nothing
# below re-decides "is this OPEN closed" or "who holds this job" — that
# second implementation is the shared defect of #468 and #511, and X2
# above is what it costs when it lands (two reductions, one question,
# five live claims against two).

INBOX_NS = "/korax/inbox"
ISSUES_LEAF = "issues"
DOCKET_LINE_CHARS = 160


def docket_namespaces(project: str) -> list[str]:
    """The namespaces a docket actually draws from, for the caller that
    has to count what was withheld from it (§9.3).

    THE DOCKET IS THE SECOND REDUCTION WHOSE SERVED SLICE IS NOT ONE
    NAMESPACE, and `/view`'s `scoped()` derives its slice from the query
    arguments — so without this it would count `ns=<project>` and report
    **zero** for every envelope withheld from the inbox section, which is
    not under it. A page that withholds while reporting a number
    structurally unable to include the withholding is the
    false-completeness class R28 exists to remove; #468 is its
    over-reporting twin.

    The feed solved this first (`api.py`'s `/feed` scoped(), D3): count by
    re-running the slice's own predicate, never by re-deriving the slice
    from the filter arguments. This is that rule's second customer.
    """
    return [project, INBOX_NS]


def _grant_root(glob: str) -> str:
    """The concrete prefix of a grant's glob — everything before the first
    wildcard segment. `/korax-dev/**` -> `/korax-dev`; `/**` -> `/`."""
    concrete: list[str] = []
    for segment in glob.strip("/").split("/"):
        if not segment or "*" in segment:
            break
        concrete.append(segment)
    return "/" + "/".join(concrete)


def project_bands(timeline: PolicyTimeline, project: str, offset: int) -> set[str]:
    """Identities holding a grant scoped INTO `project`, at `offset`.

    `in_subtree(project, _grant_root(glob))` and never a string prefix.
    Two traps it steps over, both live on this board:

      * every identity holds the `/**` reader floor, whose root is `/`,
        and `in_subtree(project, "/")` is False — so the floor grant makes
        nobody a project band, which a prefix test would also get right
        today and for the wrong reason;
      * `"/korax-dev/**".startswith("/korax")` is True while
        `in_subtree("/korax", "/korax-dev")` is False. Measuring this with
        prefixes reported 26/27 inbox OPENs as `/korax` escalations where
        the true figure is 14/27 (#783). The board ships a matcher; a
        reduction that reimplements it in string operations is #511's
        shape one layer down.

    Evaluated at `offset` rather than at head, so `docket --at <n>` is
    reproducible: grants live on the log and move, and a reduction whose
    answer depends on when you asked it is not a reduction.
    """
    return {
        grantee
        for grantee, pattern, _band in timeline.grants_at(offset)
        if grantee != "band:*" and in_subtree(project, _grant_root(pattern))
    }


def _first_line(payload: Any) -> str | None:
    """The opening line of a payload, for a reader scanning a list.

    Drawn ONLY from the already-filtered log the reduction was handed, so
    a withheld envelope never reaches it. That is the same guarantee
    `search.py`'s `_excerpt` docstring asserts in prose and nothing
    asserted in a test — #662, from slate's #639: *a later excerpt built
    for a withheld envelope to make counts more useful would pass every
    guard now standing.* This is that later excerpt, so it ships with the
    assertion instead (#111: a documented invariant with nothing asserting
    it is not an invariant).
    """
    if not isinstance(payload, str):
        return None
    for line in payload.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:DOCKET_LINE_CHARS]
    return None


def _open_entries(log: Log, ids: list[int]) -> list[dict[str, Any]]:
    entries = []
    for open_id in ids:
        env = log.get(open_id)
        if env is None:
            continue
        entries.append(
            {
                "id": env.id,
                "ns": env.ns,
                "author": env.author,
                "first_line": _first_line(env.payload),
            }
        )
    return entries


def docket(
    log: Log,
    timeline: PolicyTimeline,
    offset: int,
    project: str,
    identity: str | None = None,
) -> dict[str, Any]:
    """§10.12 — the question every session opens with, in one query.

    Three sections, each already canonical: `work` (the `jobs`
    reduction), `filed` (unclosed OPENs in the project's issues nest),
    `escalated` (unclosed OPENs in `/korax/inbox` belonging to this
    project).

    D1 — `escalated` is scoped by **author-holds-a-grant-in-project OR
    carries-an-edge-into-project**, one disjunction rather than a choice
    of three. Edges alone are structurally blind to the class that
    recurs by design: a grant request carries no refs, because at the
    moment a band files one there is nothing in the project to point at,
    and `charter.md:26` requires one per parallel session forever.
    Measured over this board's 27 inbox OPENs: edges 11, grants 18, union
    21, and the single envelope routed nowhere is a withdrawn request
    from a revoked band. A false positive costs one line a reader skims;
    a false negative strands a session at the visitor floor with nobody
    looking.

    D2 — one reduction with an optional `identity`, never two. `identity`
    NARROWS AND NEVER HIDES: every section keeps its unfiltered count in
    `totals`, so a band cannot mistake their own slice for the program's
    state. Two reductions answering one question is X2 again.
    """
    issues_ns = project.rstrip("/") + "/" + ISSUES_LEAF

    work = jobs(log, timeline, offset, project)
    filed_ids = state(log, timeline, offset, issues_ns)["opens"]
    inbox_ids = state(log, timeline, offset, INBOX_NS)["opens"]

    bands = project_bands(timeline, project, offset)
    escalated_ids = []
    for open_id in inbox_ids:
        env = log.get(open_id)
        if env is None:
            continue
        by_author = env.author in bands
        by_edge = any(
            (target := log.get(ref.id)) is not None
            and in_subtree(project, target.ns)
            for ref in env.refs
            if ref.id <= offset
        )
        if by_author or by_edge:
            escalated_ids.append(open_id)

    filed = _open_entries(log, filed_ids)
    escalated = _open_entries(log, escalated_ids)
    taken = list(work["taken"])

    totals = {
        "open": len(work["open"]),
        "taken": len(taken),
        "filed": len(filed),
        "escalated": len(escalated),
    }

    if identity is not None:
        taken = [t for t in taken if t["holder"] == identity]
        filed = [f for f in filed if f["author"] == identity]
        escalated = [e for e in escalated if e["author"] == identity]

    return {
        "project": project,
        "identity": identity,
        # The slice this answer describes, named in the answer — so a
        # reader can tell what the exclusion counters beside it cover
        # without reconstructing it from the request (§9.3).
        "namespaces": docket_namespaces(project),
        "issues_ns": issues_ns,
        "work": {**work, "taken": taken},
        "filed": filed,
        "escalated": escalated,
        # Unfiltered, always — D2's "narrows and never hides" is only true
        # if the number you were narrowed away from is still on the page.
        "totals": totals,
    }


def _job_replacements(log: Log, job_id: int, offset: int) -> list[int]:
    """JOBs that SUPERSEDE this one — X1's forwarding address."""
    return sorted(
        e.id for e in log.inbound(job_id, EdgeType.SUPERSEDES, offset)
        if e.type == Act.JOB
    )


def _job_released(log: Log, job_id: int, offset: int) -> bool:
    """Is this JOB finished with, for the purpose of releasing what it
    gates? Closed or replaced — the same two dispositions `jobs` uses to
    take a job out of `open`, asked in one place so a blocker cannot be
    'done' to one caller and 'live' to another.

    Deliberately NOT "has a live holder": a job someone is working is
    emphatically not finished, and a taken blocker must keep blocking.
    """
    if log.inbound(job_id, EdgeType.CLOSES, offset):
        return True
    return bool(_job_replacements(log, job_id, offset))


def _blockers(log: Log, job: Envelope, offset: int) -> list[int]:
    """This JOB's LIVE blockers — `gated-by` targets not yet released.

    `gated-by` and not `part-of`: §12.7 makes a campaign's children each
    claimable ("the parent to take the lot, or any subset of the
    children"), so reading breakdown as blocking would empty `ready`
    exactly when a campaign is most claimable. The two relations were
    being written in one breath with only one of them machine-readable
    (#507: `part-of → 385` in its refs, "GATES ON #385's MERGE" in its
    payload) — this is the second one getting a carrier.

    A blocker outside `ns` still blocks: ordering is ordering, and the
    log is consulted directly rather than the subtree scan, so a job
    gated on another project's work reports honestly instead of
    reporting free.
    """
    return sorted(
        target for target in job.refs_of(EdgeType.GATED_BY)
        if target <= offset
        and log.get(target) is not None
        and not _job_released(log, target, offset)
    )


def jobs(log: Log, timeline: PolicyTimeline, offset: int, ns: str) -> dict[str, Any]:
    """§10.8 — open / taken / delivered / lapsed, as the part-of forest.
    Lapsed is rendered distinctly from open: picked-up-and-dropped is
    information the next taker wants."""
    eval_ts = _eval_ts_or_none(log, offset)
    all_jobs = [e for e in log.upto(offset) if e.type == Act.JOB and in_subtree(ns, e.ns)]

    forest: dict[str, list[int]] = {}
    for job in all_jobs:
        for parent in job.refs_of(EdgeType.PART_OF):
            forest.setdefault(str(parent), []).append(job.id)
    for children in forest.values():
        children.sort()

    open_, taken, delivered, lapsed, inadmissible = [], [], [], [], []
    superseded = []
    blocked_by: dict[str, list[int]] = {}
    for job in sorted(all_jobs, key=lambda e: e.id):
        # X1 — being REPLACED is a disposition, and `closes` was the only
        # one this reduction could see. A re-pinned JOB sat in `open`
        # beside the job that replaced it forever (#276: #231 and #271
        # both listed), and the board paid for it by hand — #277 is an
        # administrative CLOSE posted to make the log say something
        # slightly false so a reduction would say something true. Its own
        # bucket, carrying the forwarding address: a reader holding the
        # old id deserves to be sent on, not to have it vanish.
        replacements = _job_replacements(log, job.id, offset)  # shared with _job_released
        if replacements:
            superseded.append({"job": job.id, "by": replacements[0]})
            continue
        # Every job still in play gets its blockers, not only the open
        # ones: a TAKEN job whose blocker is live is a claimant working
        # ahead of their substrate, and a LAPSED one carries its blockers
        # to whoever picks it up next.
        live_blockers = _blockers(log, job, offset)
        if live_blockers:
            blocked_by[str(job.id)] = live_blockers

        closers = log.inbound(job.id, EdgeType.CLOSES, offset)
        if closers:
            blocked_by.pop(str(job.id), None)  # finished work is not blocked
            _, job_pol = timeline.policy_at(job.ns, job.id)
            delivered.append(
                _delivery(log, job, closers, offset, job_pol.grades is not False)
            )
            continue
        holds = resolve(log, job.id, offset)
        inadmissible.extend(h.head.id for h in holds if not h.admissible)
        live = next((h for h in holds if h.live_at(eval_ts)), None)
        if live:
            taken.append(
                {
                    "job": job.id,
                    "holder": live.author,
                    "via": live.current.id,
                    "lease_until": live.lease_until_raw(),
                }
            )
            continue
        dead = [h for h in holds if h.admissible]
        if dead:
            last = dead[-1]
            entry: dict[str, Any] = {
                "job": job.id,
                "prior_holders": sorted({h.author for h in dead}),
            }
            if last.released_by is not None:
                entry["released_by"] = last.released_by.id
                reasons = last.released_by.refs_of(EdgeType.DERIVES_FROM)
                if reasons:
                    entry["reason"] = reasons[0]
            lapsed.append(entry)
            continue
        open_.append(job.id)

    return {
        "eval_ts": _fmt(eval_ts),
        "forest": forest,
        "open": open_,
        "taken": taken,
        "delivered": delivered,
        "superseded": superseded,
        "lapsed": lapsed,
        "inadmissible_claims": sorted(inadmissible),
        # §10.8 — ordering, from `gated-by` only. `forest` above is
        # `part-of` and answers a different question (what is this work
        # part of); these two keys must never be derived from each other.
        "blocked_by": blocked_by,
        # Open, unheld, and nothing live in front of it. LAPSED jobs are
        # claimable too and are deliberately NOT folded in: picked-up-and-
        # dropped is information the next taker wants, and `lapsed`
        # carries `prior_holders` and a release reason that `ready` would
        # flatten away. A reader asking "everything I could take now"
        # unions the two and keeps both stories.
        "ready": [j for j in open_ if str(j) not in blocked_by],
    }
