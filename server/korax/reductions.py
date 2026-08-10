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


def _fmt(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _effectively_stamped(log: Log, env_id: int, offset: int) -> bool:
    """§6.1/§6.4 — stamped iff an active, non-retracting STAMP targets it.
    A superseded stamp no longer grants; a retracting stamp never does."""
    for stamp in log.inbound(env_id, EdgeType.STAMPS, offset):
        if stamp.type != Act.STAMP or stamp.ext.get("retracts") is True:
            continue
        if log.inbound(stamp.id, EdgeType.SUPERSEDES, offset):
            continue
        return True
    return False


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
        and _grade_ok(floor, e.grade, _effectively_stamped(log, e.id, offset))
    ]
    stamped = [i for i in findings if _effectively_stamped(log, i, offset)]
    invalidated = [e.id for e in envs if _invalidated(log, e.id, offset)]
    clusters = _beside_clusters(envs, log, offset)

    claims = []
    eval_ts = log.get(offset).ts if log.get(offset) else None
    for env in envs:
        if env.type in (Act.OPEN, Act.JOB) and eval_ts is not None:
            hold = live_holder(log, env.id, offset, eval_ts)
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
    eval_ts = log.get(offset).ts
    cutoff = eval_ts - _parse_horizon(horizon)
    entries = []
    for env in log.upto(offset):
        if env.ns.startswith("/scratch/"):
            continue
        if not any(ns_matches(p, env.ns) for p in ns_set):
            continue
        _, pol = timeline.policy_at(env.ns, env.id)
        if pol.grades is False:
            continue  # play cannot leak into canon (R9)
        if env.ts < cutoff:
            continue
        is_stamped = _effectively_stamped(log, env.id, offset)
        if env.type == Act.WARN:
            pass  # grade-exempt (§6.3)
        elif env.type == Act.FINDING and _grade_ok("verified", env.grade, is_stamped):
            pass
        else:
            continue
        weight, who = _replication(log, timeline, env, offset)
        entries.append(
            {
                "id": env.id,
                "type": env.type.value,
                "grade": env.grade.value,
                "replication_weight": weight,
                "corroborators": who,
            }
        )
    return sorted(entries, key=lambda e: (-e["replication_weight"], e["id"]))


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


def of_record(log: Log, offset: int, project: str) -> list[int]:
    """§10.7 — grade floor `stamped`. Nothing else. POLICY is excluded:
    a stamped policy is ratified configuration (§8.5), not content of
    record."""
    return sorted(
        e.id for e in log.upto(offset)
        if in_subtree(project, e.ns)
        and e.type != Act.POLICY
        and _effectively_stamped(log, e.id, offset)
    )


def jobs(log: Log, timeline: PolicyTimeline, offset: int, ns: str) -> dict[str, Any]:
    """§10.8 — open / taken / delivered / lapsed, as the part-of forest.
    Lapsed is rendered distinctly from open: picked-up-and-dropped is
    information the next taker wants."""
    eval_ts = log.get(offset).ts
    all_jobs = [e for e in log.upto(offset) if e.type == Act.JOB and in_subtree(ns, e.ns)]

    forest: dict[str, list[int]] = {}
    for job in all_jobs:
        for parent in job.refs_of(EdgeType.PART_OF):
            forest.setdefault(str(parent), []).append(job.id)
    for children in forest.values():
        children.sort()

    open_, taken, delivered, lapsed, inadmissible = [], [], [], [], []
    for job in sorted(all_jobs, key=lambda e: e.id):
        closers = log.inbound(job.id, EdgeType.CLOSES, offset)
        if closers:
            closer = min(closers, key=lambda e: e.id)
            delivered.append({"job": job.id, "by": closer.id, "grade": closer.grade.value})
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
        "lapsed": lapsed,
        "inadmissible_claims": sorted(inadmissible),
    }
