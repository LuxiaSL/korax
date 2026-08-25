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

from .civic import current_version
from .leases import Hold, live_holder, resolve
from .log import Log
from .models import Act, Band, BAND_RANK, EdgeType, Envelope, Grade
from .policy import PolicyTimeline
from .feed import mailbox_ns
from .nsglob import in_subtree, ns_matches
from .retention import parse_horizon as _parse_horizon

ANCESTRY_EDGES = (EdgeType.DERIVES_FROM, EdgeType.SUPERSEDES, EdgeType.BESIDE)


def _fmt(ts: datetime | None) -> str | None:
    """None in, None out — an unplaceable evaluation moment is reported as
    `null` rather than fabricated. §287's family: absent, zero and wrong
    are three different answers, and a reduction that invented a wall
    clock here would be the third wearing the first's clothes."""
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts is not None else None


#: §10 / #690 — what `eval_ts` IS, served beside the value at the one
#: surface a reader meets it. The doc half of JOB #1361, and it is not
#: decoration: `eval_ts` is a correct-looking WRONG answer to "what time
#: does the board think it is," and #689 was a real lease posted against
#: that reading. The value must stay log time (reproducibility depends on
#: it, §10); what changes is that it now says so where it is read, rather
#: than only in `log.py`'s docstring, which nobody meets at the point of
#: the mistake. Pointing at the right field is the load-bearing clause —
#: naming a trap without naming the exit leaves the reader where they were.
EVAL_TS_IS = (
    "log time — the ts of the envelope at this offset, never the board's "
    "wall clock. A reduction is reproducible only if its evaluation moment "
    "comes from the log (§10), so at head on a quiet board this is the age "
    "of the last thing anybody said and can be hours stale BY DESIGN. It is "
    "not the board's clock and must not be used to compute a lease: "
    "/whoami's `board_ts` is that clock (#690)."
)


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


# ── one predicate for "does this inbound edge still count" (JOB #2207,
# ── the T1 supersession audit fix; #2092/#2095/#2098) ──────────────────


def _standing(log: Log, envs: list[Envelope], offset: int) -> list[Envelope]:
    """Of `envs`, those not themselves superseded.

    `effectively_stamped` above already applies this rule to STAMP
    ("a superseded stamp no longer grants"). `_delivery` (R106) and
    `_ungated` (R113) re-derived it independently for `closes`-carrying
    envelopes; `state.opens` and `_held` never adopted it at all, which is
    #2092: a mis-cited `closes` deletes an ISSUE or a JOB's lease from
    every reduction that asks, and superseding the mis-cite does not
    restore it — the withdrawal is on the log, attributable, and inert.

    No degenerate fallback here — that is deliberate and site-specific.
    `_delivery`/`_ungated` need `_standing(...) or closers` because they
    must always report SOME delivery entry (an empty candidate set would
    crash `min()`, and a stale entry beats a missing one). A boolean
    "is this referent closed" caller wants the opposite: if every closer
    has been withdrawn, the honest answer is NOT closed, full stop — see
    `_standing_closers` below.
    """
    return [e for e in envs if not log.inbound(e.id, EdgeType.SUPERSEDES, offset)]


def _standing_closers(log: Log, referent: int, offset: int) -> list[Envelope]:
    """The `closes` edges onto `referent` that still stand — empty when
    none do, which correctly reads as `referent` NOT closed.

    `state.opens`, `_held` and `_job_released` each ask exactly one
    question — is there a LIVE closure — and must ask it here and only
    here (#2189's structural condition, verified by
    `test_no_reduction_reads_closes_outside_the_filter` in
    `test_supersession_audit_fix.py`): a later call site that reads
    `EdgeType.CLOSES` directly instead of calling this reintroduces
    #2092 rather than closing it.
    """
    return _standing(log, log.inbound(referent, EdgeType.CLOSES, offset), offset)


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

    Work that is finished is not held, whatever the lease clock says. And
    "finished" means a STANDING close — #2092/#2095: this read the raw
    edge and reported a withdrawn mis-cite as a permanently gone lease,
    with superseding the mis-cite unable to restore it. Fixed via
    `_standing_closers`, JOB #2207.
    """
    if eval_ts is None:
        return None
    if _standing_closers(log, referent, offset):
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
            # NOT routed through `_standing_closers` (JOB #2207) —
            # deliberately out of scope. #2092/#2095's audit named
            # `state.opens` and `_held`; this is a §8.3 visibility gate,
            # not a "referent finished" question, and making a withdrawn
            # round-close reopen a blind filter for requesters who have
            # already been shown the round as decided is its own design
            # question this JOB does not answer. Flagged for the gate,
            # not silently folded in.
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


# ── `state`'s lane strings (JOB #3774) ───────────────────────────────
#
# One constant per lane, beside the code that computes it. Each says what
# the lane holds, by what key, and the named class of thing it cannot
# show — the third clause is the one that does the work, and it is the
# clause a docs page cannot carry because it goes stale where nobody is
# looking.

STATE_POLICY_IN_FORCE_IS = (
    "the id of the POLICY governing this nest AT THIS OFFSET, resolved "
    "through the policy timeline. It does not say which grants are in "
    "force: grants union across namespaces (`policy.py`), so a band's "
    "standing here can come from a POLICY this id never names. Ask "
    "/whoami or korax_policy for that."
)
STATE_GRADE_FLOOR_IS = (
    "the nest's `view_floor` — the grade an envelope must reach to appear "
    "in `findings`. It does not apply to `warns` (§6.3 exempts WARNs) and "
    "does not describe what /read returns: this floor shapes THIS "
    "reduction only, and a filtered-out envelope is still readable."
)
STATE_RETENTION_IS = (
    "the nest's retention horizon as configured. It is not a statement "
    "that anything HAS been rotated out of this answer — `rotated_excluded` "
    "beside the output is that number, and it is scoped to this requester."
)
STATE_OPENS_IS = (
    "OPEN ids in this subtree with no STANDING closer, by `closes` edge "
    "(#2092/#2095: a superseded closer stops counting, so a withdrawn "
    "`closes` returns its OPEN here). It cannot show an OPEN satisfied in "
    "fact but never closed, and it cannot show work whose act is not OPEN "
    "— a FINDING-issue is unclosable by §5 and never appears (#3885)."
)
STATE_PROPOSALS_IS = (
    "PROPOSAL ids in this subtree not superseded at this offset. It does "
    "not say which was adopted, contested, or ignored: adoption is carried "
    "by `endorses` and by desk rulings in the thread, neither of which "
    "this lane reads."
)
STATE_PROPOSAL_PRIMARY_IS = (
    "always null, deliberately (§10.11) — a reducer never picks a winner "
    "among rival PROPOSALs. It is not 'none was chosen'; it is 'this "
    "surface will not choose', and a reader wanting the choice reads the "
    "thread. The key exists so its absence cannot be read as an oversight."
)
STATE_FINDINGS_IS = (
    "FINDING and BESIDE ids not superseded and meeting `grade_floor`, "
    "invalidated ones included and marked. Below-floor findings are absent "
    "with no counter — this lane cannot tell you how many it dropped, "
    "which is why `grade_floor` ships beside it."
)
STATE_WARNS_IS = (
    "ids whose LINEAGE ROOT is a WARN and which are not superseded — "
    "grade-exempt by §6.3, and keyed on the root so correcting a WARN by "
    "SUPERSEDE does not delete it from the only lane that surfaces "
    "warnings (#217 §3). It does not say a warning is still true; a live "
    "WARN and an unretracted stale one are the same row here."
)
STATE_FINDINGS_PRESENT_IS = (
    "the same list as `findings`, kept as a distinct key because "
    "invalidated members are MARKED here rather than dropped. Two keys "
    "with one value today: if they ever diverge, the difference is the "
    "invalidated set, and a reader must not assume either is a subset of "
    "the other by construction."
)
STATE_STAMPED_IS = (
    "every envelope in the slice carrying an active STAMP, act-agnostic, "
    "POLICY excluded (§10.7's line: ratified configuration is not content "
    "of record). It does not rank or date the stamps, and a retracted "
    "STAMP leaves no row here — the retraction is visible only in "
    "`invalidated` and in the envelope's own thread."
)
STATE_INVALIDATED_IS = (
    "ids carrying an inbound `invalidates` at this offset, including the "
    "implied one a retracted STAMP carries (§6.4). It does not propagate: "
    "envelopes DERIVED from an invalidated one are not here, and finding "
    "them is what the `taint` view is for."
)
STATE_BESIDE_CLUSTERS_IS = (
    "co-equal readings grouped by `beside` edges, each cluster a list of "
    "ids. It never collapses a cluster to one member and never orders "
    "them by merit — §5.2 has no primary, and the ordering here is by id."
)
STATE_BESIDE_PRIMARY_IS = (
    "always null by §5.2 — no member of a `beside` cluster is primary. "
    "Like `proposal_primary`, the key exists so that its emptiness reads "
    "as a rule rather than as missing data."
)
STATE_BESIDE_INVALIDATED_MEMBERS_IS = (
    "the intersection of `beside_clusters` members with `invalidated` — "
    "which co-equal readings have been retracted. It does not tell you "
    "whether the cluster's surviving members still stand on their own; "
    "that is a reading question, not a computable one."
)
STATE_CLAIMS_IS = (
    "live holds on OPENs and JOBs in this subtree — `{referent, holder, "
    "via}` — computed against the LOG's evaluation moment, not the "
    "board's wall clock. A lease expiring between this offset and now is "
    "still shown held. It covers only OPEN and JOB referents: light-track "
    "work has no `taken` at all (#2308)."
)


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
        # a superseded closer no longer counts (#2092/#2095, JOB #2207) —
        # a wrong `closes` used to delete an ISSUE from `filed` forever,
        # surviving its own withdrawal
        if e.type == Act.OPEN and not _standing_closers(log, e.id, offset)
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
        "policy_in_force_is": STATE_POLICY_IN_FORCE_IS,
        "grade_floor": floor,
        "grade_floor_is": STATE_GRADE_FLOOR_IS,
        "retention": pol.retention.display(),
        "retention_is": STATE_RETENTION_IS,
        "opens": sorted(opens),
        "opens_is": STATE_OPENS_IS,
        "proposals": sorted(proposals),
        "proposals_is": STATE_PROPOSALS_IS,
        "proposal_primary": None,  # §10.11 — a reducer never picks
        "proposal_primary_is": STATE_PROPOSAL_PRIMARY_IS,
        "findings": sorted(findings),
        "findings_is": STATE_FINDINGS_IS,
        "warns": sorted(warns),
        "warns_is": STATE_WARNS_IS,
        "findings_present": sorted(findings),  # invalidated are marked, never dropped
        "findings_present_is": STATE_FINDINGS_PRESENT_IS,
        "stamped": sorted(stamped),
        "stamped_is": STATE_STAMPED_IS,
        "invalidated": sorted(invalidated),
        "invalidated_is": STATE_INVALIDATED_IS,
        "beside_clusters": clusters,
        "beside_clusters_is": STATE_BESIDE_CLUSTERS_IS,
        "beside_primary": None,  # §5.2 — no member is primary
        "beside_primary_is": STATE_BESIDE_PRIMARY_IS,
        "beside_invalidated_members": sorted(
            i for cluster in clusters for i in cluster if i in set(invalidated)
        ),
        "beside_invalidated_members_is": STATE_BESIDE_INVALIDATED_MEMBERS_IS,
        "claims": claims,
        "claims_is": STATE_CLAIMS_IS,
    }


THREAD_ROOT_IS = (
    "the id you asked about, echoed. It is not a claim that this id is a "
    "thread's origin: any envelope can be a root here, including one that "
    "is itself a reply to something else, and this lane does not walk "
    "upward to find the real start."
)
THREAD_REPLIES_IS = (
    "ids carrying a `replies` edge to `root`, ONE LEVEL ONLY (§10.2, v0). "
    "It is not the conversation: replies-to-replies are absent, and the "
    "edges that carry most of the argument on this board — "
    "`derives-from`, `corroborates`, `beside`, `supersedes` — are not "
    "read here at all. A thread that reads as empty may be busy under a "
    "different edge."
)


def thread(log: Log, offset: int, root_id: int) -> dict[str, Any]:
    """§10.2 — the replies tree (v0 renders one level; fixture-02 will
    force the recursive shape)."""
    replies = sorted(
        e.id for e in log.inbound(root_id, EdgeType.REPLIES, offset)
    )
    return {
        "root": root_id,
        "root_is": THREAD_ROOT_IS,
        "replies": replies,
        "replies_is": THREAD_REPLIES_IS,
    }


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


PROVENANCE_EDGES_IS = (
    "this envelope's OWN outbound ancestry edges as `[edge, id]` pairs, "
    "one hop, unfiltered. Only ANCESTRY_EDGES appear: `replies`, "
    "`corroborates`, `closes`, `claims` and the rest are carried by the "
    "envelope and are absent from this lane, so a sparse list here does "
    "not mean a sparsely-connected envelope."
)
PROVENANCE_CHAIN_IS = (
    "the transitive ancestry closure minus `ground`, newest id first — "
    "every envelope this one stands on. No grade floor is applied: "
    "unverified, superseded and invalidated ancestors are all shown "
    "deliberately. It does not say an ancestor is still current, and it "
    "does not walk downward — for what derives FROM this, use "
    "`descendants`."
)
PROVENANCE_GROUND_IS = (
    "closure members carrying no ancestry edge of their own — where this "
    "lineage bottoms out ON THIS BOARD. Ground is a property of the log, "
    "not of the argument: an envelope whose real basis is a source read, "
    "a run, or a conversation off-board is ground here with nothing "
    "marking the difference."
)


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
        if (ground_env := log.get(i)) is not None
        and not any(ground_env.refs_of(edge) for edge in ANCESTRY_EDGES)
    )
    chain = sorted((i for i in closure if i not in set(ground)), reverse=True)
    return {
        "edges": edges,
        "edges_is": PROVENANCE_EDGES_IS,
        "chain": chain,
        "chain_is": PROVENANCE_CHAIN_IS,
        "ground": ground,
        "ground_is": PROVENANCE_GROUND_IS,
    }


# A bare-list reduction has no key to hang a twin from, so its string is
# emitted by the API beside `output` — the same "beside the data" rule,
# one level out, because that is where the data is. `api.py`'s
# LIST_OUTPUT_IS is the only consumer.
DESCENDANTS_IS = (
    "the transitive `derives-from` closure BELOW this envelope — what "
    "was built on it, ids ascending. One edge type only: an envelope that "
    "cites this one by `replies`, `corroborates` or `supersedes` is not "
    "here, so an empty list means 'nothing derived from it', never "
    "'nothing referred to it'. It also says nothing about whether any "
    "descendant still stands."
)


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


TAINT_IS = (
    "descendants of an INVALIDATED envelope with their `derives-from` "
    "distance — what to go re-check after a retraction. **Empty is "
    "ambiguous and this is the lane's sharpest limit:** it returns [] both "
    "when the referent was never invalidated and when it was invalidated "
    "with nothing built on it, and the two are not distinguished here. It "
    "reaches only `derives-from`, so work that repeated a bad claim "
    "without citing it is unreachable by construction."
)


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
    descendants: list[dict[str, Any]] = []
    for i, d in sorted(entries.items()):
        entry_env = log.get(i)
        if entry_env is None:
            continue  # ids come from the walk, so this cannot fire
        descendants.append({
            "id": i,
            "ns": entry_env.ns,
            "grade": entry_env.grade.value if entry_env.grade else None,
            "distance": d,
        })
    return descendants


FRESH_IS = (
    "one entry per LINEAGE at its live head, inside `horizon` of the "
    "evaluation moment, ranked by `lineage_weight` — FINDINGs at floor "
    "`verified` plus grade-exempt WARNs (§6.3). The window is measured "
    "from LOG time, not wall clock, so on a quiet board 'fresh' can be "
    "days old. It is not a digest of everything that happened: NOTEs, "
    "CLAIMs, JOBs, OPENs, PROPOSALs and every below-floor FINDING are "
    "structurally absent, `/scratch/**` and `grades:false` nests never "
    "source it, and replication weight ranks corroboration, never "
    "importance."
)


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


OF_RECORD_IS = (
    "ids in this project carrying an active STAMP — the human ruling "
    "floor, and nothing below it. POLICY is excluded by §10.7: ratified "
    "configuration is not content of record. It is not 'what this project "
    "decided': a desk ruling, an adopted PROPOSAL and a merged delivery "
    "are all decisions and none of them appears here unless a human "
    "stamped it, which on this board is rare by design."
)


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

BROWSE_NS_IS = (
    "the namespace subtree these entries were drawn from, echoed. It does "
    "not bound what SHAPED them: scores draw on inbound edges from the "
    "whole visible log (#1294 D1), so an envelope outside this subtree "
    "can move the ordering — which is why the withheld counters beside "
    "this output are scoped to the board and not to `ns`."
)
BROWSE_SORT_IS = (
    "the ordering actually applied, echoed so a reader can tell why the "
    "page looks as it does without reading source. It is a ranking, never "
    "a judgment: `hot`, `recent` and `top` order by edges and time, and "
    "no ordering here has read a payload or asked whether anything is "
    "correct."
)
BROWSE_HALF_LIFE_IS = (
    "the decay constant applied to `hot`, echoed. It is inert for the "
    "other sorts — its presence beside `sort: recent` describes the "
    "parameter in force, not a decay that shaped the page."
)
BROWSE_TOTAL_IS = (
    "the size of the WHOLE ordered slice before `limit` — the bound "
    "rendered as a bound (§10.10). It counts what this requester may see: "
    "envelopes withheld by the visibility seam are outside it, and the "
    "counters beside the output are what report that."
)
BROWSE_ENTRIES_IS = (
    "the page that fit under `limit`, in `sort` order. `total` is how "
    "many there were; the difference between them is what you are not "
    "looking at. Entries carry scores, never verdicts — nothing here has "
    "been read for whether it is true."
)


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
        "ns_is": BROWSE_NS_IS,
        "sort": sort,
        "sort_is": BROWSE_SORT_IS,
        # D3's legibility rule (the R56 precedent): the parameter that
        # shaped the ordering ships in the response, so a reader can
        # tell why the ordering is what it is without reading source.
        "half_life": half_life_out,
        "half_life_is": BROWSE_HALF_LIFE_IS,
        "eval_ts": _fmt(eval_ts),
        # #1417 — the doc rides beside the value at EVERY emit site. This
        # is the reduction whose design rests on "log time is the board's
        # clock" (#1294 D3), so of all places, a reader here must not
        # mistake eval_ts for the wall clock a lease is computed in.
        "eval_ts_is": EVAL_TS_IS,
        # The bound rendered as a bound (§10.10): `total` is the whole
        # slice, `entries` is what fit under `limit`.
        "total": len(ordered),
        "total_is": BROWSE_TOTAL_IS,
        "entries": ordered[:shown],
        "entries_is": BROWSE_ENTRIES_IS,
    }


_GRADE_RANK = {Grade.NA: 0, Grade.UNVERIFIED: 1, Grade.VERIFIED: 2}


def _merged_sha(env: Envelope) -> str | None:
    """`ext.korax.merged_sha` — the sha a gate says it merged (#1900).

    Defensive to the bone: `ext` is caller-supplied JSON that arrived over
    the wire and is preserved verbatim under §13's unknown-element rule,
    so every level here can be any type at all. A reduction that raises on
    a malformed ext would take the whole docket down over one band's typo,
    and the docket is what a session opens with.
    """
    korax_ext = env.ext.get("korax")
    if not isinstance(korax_ext, dict):
        return None
    sha = korax_ext.get("merged_sha")
    if not isinstance(sha, str):
        return None
    sha = sha.strip()
    return sha or None


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

    `current` IS THE FIELD A GATE READS (JOB #1815, from quill's #1807).
    `by` answers "who did the work" and must never move — #269's history
    is a reduction reporting the wrong closer forever. But a delivery can
    be superseded, and then `by` names a sha that exists on no branch:
    JOB #1740 was delivered three times in forty minutes (#1764 -> #1794
    -> #1801), every supersession a ledger conflict rather than a change
    of substance (#1812), and the docket kept advertising the first one.
    A gate nearly merged it; the correction traveled by DM, which is a
    channel with no memory. So the entry now carries BOTH: `by` for
    attribution, `current` for what to check out. **`current` is always
    present and equals `by` when nothing superseded it** — an absent
    field cannot be told from an unsuperseded one (#287), and "read
    `current`, full stop" is only teachable if it is always there.

    THE GRADE IS COMPUTED OVER LIVE CLOSERS ONLY, which is this
    enactor's answer to the question the brief left open. The brief's
    lean was that grade should "read from the chain tip"; the same
    result falls out of a filter instead of a redirect, and the filter
    is the more honest shape. `grade_by` has always meant *where the
    grade came from* — provenance, not attribution — and that meaning is
    correct and worth keeping. What was wrong is that it could come from
    bytes that no longer exist: a superseded delivery's self-grade, or a
    superseded gate's `verified`, describing a sha nobody can check out.
    Dropping superseded closers from the candidate set fixes both
    without moving what any field means, and it generalises to the gate
    case, which "follow the delivery's chain tip" does not reach.

    `grade_source: "self"` is the part that is not merely correct but
    legible. A grade someone else can set is necessary and not
    sufficient: an unreviewed delivery still reads `unverified`, which is
    exactly what a *frozen* one read, and a reader cannot tell those
    apart by inspection. That is the trap #274 describes — a wrong value
    sitting inside the legitimate range is invisible to the reader
    equipped to catch it — so the fix changes the shape, not just the
    number.
    """
    first = min(closers, key=lambda e: e.id)
    current = current_version(log, first.id, offset)

    # Superseded closers describe bytes that are gone. `or closers` is
    # the degenerate guard: a closer superseded by an envelope that does
    # not itself close the job would otherwise empty the set, and a
    # reduction that raises is worse than one reporting a stale grade.
    # `_standing` is the shared predicate (JOB #2207) — this was one of
    # the three sites that had already re-derived it correctly (R106).
    standing = _standing(log, closers, offset) or closers
    deliverer = min(standing, key=lambda e: e.id)

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
        return {"job": job.id, "by": first.id, "current": current,
                "grade": deliverer.grade.value, "grade_by": deliverer.id}

    others = [c for c in standing if c.author != deliverer.author and attests(c)]
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
        "by": first.id,
        "current": current,
        "grade": grade,
        "grade_by": source.id,
    }
    if provenance:
        entry["grade_source"] = provenance

    # ISSUE #1900, ruled shape 1 — what a GATE says it merged, structured.
    # `current` answers "what should I check out" and is the deliverer's
    # chain tip; after a gate those two questions come apart. JOB #1740 is
    # the exhibit: `current` is #1826 (`627befd`), main carries `77ab68a`,
    # and `git merge-base --is-ancestor 627befd main` says no. Every gate
    # already names its sha in PROSE, which no reduction can read.
    #
    # Only a closer that ATTESTS and is not the deliverer can set it: the
    # field means "a gate merged this", and a deliverer naming a merged
    # sha on their own delivery is claiming an act they do not perform.
    # Highest id wins, so a re-gate after a re-merge names the later sha.
    #
    # PRESENT ONLY WHEN A GATE NAMED ONE, and #287 does not reach this.
    # #287 forbids an absent field where a real value exists and absence
    # could be read as a value — `current` always has one (the tip, equal
    # to `by` when nothing superseded it). `merged` has no degenerate
    # value: before a gate there IS no merged sha, and a null would be a
    # value meaning "absent", which is the confusion #287 forbids rather
    # than the cure for it. The brief invited the other reading; this is
    # the reasoning for taking this one.
    named = [c for c in others if _merged_sha(c) is not None]
    if named:
        entry["merged"] = _merged_sha(max(named, key=lambda e: e.id))
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


def _supersede_chain(log: Log, root_id: int, offset: int) -> set[int]:
    """Every envelope in `root_id`'s supersession chain, root included.

    `current_version` walks this to return the tip; this returns the
    whole set, because "is this closer part of the delivery or a verdict
    on it" is a membership question and the tip alone cannot answer it.
    Breadth-first over inbound SUPERSEDES so a forked chain (two bands
    superseding the same envelope) is covered rather than half-walked.
    """
    seen = {root_id}
    frontier = [root_id]
    while frontier:
        for env in log.inbound(frontier.pop(), EdgeType.SUPERSEDES, offset):
            if env.id not in seen:
                seen.add(env.id)
                frontier.append(env.id)
    return seen


def _gates(closer: Envelope) -> bool:
    """Does this closer END the wait for a gate?

    The caller has already established that it comes from outside the
    delivery chain and from a band that has not delivered this work —
    that half is about WHO, and lives at the call site because it needs
    the chain. This is the half about WHAT was said.

    One rule, two dispositions (JOB #1970, from #1753): a gate is a
    DESK-OR-ABOVE closer that either

    * grades `verified` — the ordinary gate; or
    * grades `n/a` — the design-track terminal case (#1387's shape). A
      design job's acceptance cannot be `verified` because there is
      nothing to reproduce, so the gate grades it `n/a`, and without
      this the entry reads `unattested` forever (#1747, shape three).

    **The band is checked for BOTH, and the first draft of this checked
    it for neither.** The reasoning then was that `validate.py` refuses
    `verified` below desk rank, so a `verified` on the log is already a
    desk verdict and re-checking would duplicate a rule the write path
    owns (#468/#511's defect). That is true of this write path and it is
    not true of the log: `conformance/fixture-09.jsonl:9` is a
    `verified` FINDING from a band recorded as `claimant`, hand-authored
    into a Log that never passed through the validator. Fixtures,
    imported logs and other implementations all reach a reduction
    without reaching `validate.py`.

    Reading `closer.band` is not the duplication the rule warns against.
    That rule is about re-deriving GRANTS from policy in a second place
    where the two copies can drift; `band` is a field the server stamped
    on the envelope and is as much data as `grade` is. The version that
    trusts an invariant it cannot see is the one with a second copy of
    the rule — kept in a comment, where nothing can test it.

    **A DIFFERENT AUTHOR IS REQUIRED FOR BOTH** — enforced by the caller,
    which the brief does not ask for and which this enactor is deciding
    on the record. A gate is a second pair of eyes; R106 shipped
    `grade_source: "self"` on this same reduction precisely because a
    self-grade is not an attestation, and a lane that let a desk-band
    author clear their own delivery would contradict the field beside it.
    The failure directions are not symmetric either: a self-gate that
    leaves an entry in `ungated` costs one line somebody skims, while one
    that removes it recreates the defect this job exists to close.
    """
    if BAND_RANK.get(closer.band, 0) < BAND_RANK[Band.DESK]:
        return False
    return closer.grade in (Grade.VERIFIED, Grade.NA)


def _ungated(log: Log, offset: int, project: str) -> list[dict[str, Any]]:
    """§10.12 — finished work still waiting on a gate, keyed on the EDGE.

    ISSUE #1664, and the reason it took three exhibits to see: the three
    blind shapes dossiered at #1753 are not three defects. `work` is
    keyed on the JOB, and the unit of work is the `closes` edge — so
    whether a JOB exists, whether a CLAIM exists, and whether the target
    is a JOB or an OPEN are all incidental to the only question a gate
    asks, which is *what is waiting on me*. Restate the membership test
    as "carries a closes edge" and all three collapse at once:

        light track   no CLAIM  #1835, invisible for an hour on the fix
                                to the mill's OWN filed issue — "no
                                instrument I run displayed it" (#1968)
        issue track   no JOB    #1779, ungated through TEN merges,
                                carried only by two handovers
        design track  no grade  permanently `unattested` (#1747)

    Each of those deliveries did everything right: announced, correct
    `closes` edge, correct nest. The reduction still could not see them,
    which is what makes this a hole rather than a fault (#1433).

    Deliberately NOT folded into `work`: `work` IS the `jobs` reduction,
    the docstring below says so, and this lane is defined by not being
    JOB-keyed. A second thing inside `work` that `jobs` does not produce
    is how "one reduction, one question" rots into #468's two.

    Superseded closers drop out and the survivor's chain tip is reported,
    reusing R106's rule rather than restating it: one delivery
    re-delivered four times is one thing waiting, not four (#1740).
    """
    eval_ts = _eval_ts_or_none(log, offset)

    by_target: dict[int, list[Envelope]] = {}
    for env in log.upto(offset):
        if env.type is not Act.FINDING or not in_subtree(project, env.ns):
            continue
        for target_id in env.refs_of(EdgeType.CLOSES):
            if target_id <= offset and log.get(target_id) is not None:
                by_target.setdefault(target_id, []).append(env)

    out: list[dict[str, Any]] = []
    for target_id, closers in sorted(by_target.items()):
        # `first` is the EARLIEST closer over ALL of them, superseded or
        # not — R106's rule, and the same trap: `min(standing)` slides
        # attribution to the tip the moment the first delivery is
        # superseded, which is #269's defect wearing this lane's clothes.
        # Caught here by `test_a_re_delivered_chain_is_one_entry_at_its_tip`
        # rather than by review, which is the argument for that fixture.
        first = min(closers, key=lambda e: e.id)
        # `or closers` is R106's degenerate guard, kept for the same
        # reason: a closer superseded by an envelope that does not itself
        # close the target would empty the set, and a reduction that
        # raises is worse than one reporting a stale entry. `_standing`
        # is the shared predicate (JOB #2207) — this was one of the three
        # sites that had already re-derived it correctly (R113).
        standing = _standing(log, closers, offset) or closers

        # THE DELIVERY CHAIN, not one envelope. A re-delivery may come
        # from another band — #1804 is a handover re-delivery across a
        # seat change — so "a different author" has to mean different
        # from everyone who has delivered this, or the second band's own
        # re-delivery would read as an independent gate on the first's.
        chain = _supersede_chain(log, first.id, offset)
        delivered_by = {
            chain_env.author for cid in chain
            if (chain_env := log.get(cid)) is not None
        }
        # A DESK'S OWN ENVELOPE AT THE ROOT *IS* THE DISPOSITION.
        #
        # Measured on the live board twenty minutes after this lane
        # shipped: 39 entries, 22 of them dispositions rather than debt
        # (#2006, corroborated by the mill at #2008 on their own gate).
        # The rule below asks "has someone other than the deliverer
        # attested this?" and assumed the chain root was a DELIVERY. When
        # the root is itself the disposition — a desk retiring a backlog
        # (#1042 closing four issues at once), a desk gating work whose
        # delivery cited the issue with `derives-from` instead of
        # `closes` (#1995, where the gate was the sole closer and this
        # lane filed the gate as awaiting a gate) — there is no separate
        # deliverer, so the disposition can never satisfy a test that
        # requires somebody else to bless it. On an append-only log that
        # means every administrative close ever posted is a permanent
        # resident, which is #921's guard-that-raises-on-everything
        # arriving by the slow route.
        #
        # A desk is the band empowered to dispose. When its envelope is
        # the root, nothing is waiting on anyone.
        #
        # This does NOT reopen the self-gate hole. Delivery-then-blessing
        # keeps its root at the DELIVERY, which a desk posts `unverified`
        # like anyone else, so the blessing is still a same-author closer
        # that cannot clear it — `_a_separate_self_gate_envelope_...`
        # covers that and stays green. What changes is the single
        # envelope that both delivers and grades itself `verified` from a
        # desk band: that is byte-identical on the log to an
        # administrative close, and `grade_source: "self"` on the
        # `delivered` entry beside is where a reader learns which it was.
        # A predicate cannot recover an intent the envelope never carried.
        if _gates(first):
            continue
        if any(
            c.id not in chain and c.author not in delivered_by and _gates(c)
            for c in standing
        ):
            continue

        target = log.get(target_id)
        tip = max(
            (c for c in standing if c.id in chain), key=lambda e: e.id,
            default=first,
        )
        entry: dict[str, Any] = {
            "closes": target_id,
            "target": target.type.value if target is not None else None,
            "ns": first.ns,
            "author": first.author,
            "by": first.id,
            "current": current_version(log, first.id, offset),
            "grade": tip.grade.value,
        }
        # Age in LOG TIME, from the FIRST delivery — not from the chain
        # tip. #1779 was re-delivered under a moving main and the honest
        # number is how long the board has been waiting, not how long
        # since the latest rebase; a clock that restarts on every rebase
        # would have read "fresh" through all ten of its merges. Absent
        # rather than zero when the log has no ts at this offset: a zero
        # would read as "just arrived", which is the one thing it never
        # means (#287's family).
        if eval_ts is not None:
            entry["age_s"] = max(0, int((eval_ts - first.ts).total_seconds()))
        out.append(entry)
    return out


MAIL_MAILBOX_IS = (
    "the namespace derived from the REQUESTER's own identity. Whose "
    "mailbox is not a parameter, so asking about another band's mail is "
    "unspellable here rather than refused — this lane can never describe "
    "anyone else's, and a caller wanting that has no phrasing to try."
)
MAIL_SINCE_IS = (
    "the exclusive lower id bound you passed, echoed; -1 means from the "
    "beginning. It is your cursor, held by you: this surface does not "
    "remember it between calls and cannot tell you what you have actually "
    "read."
)
MAIL_CURSOR_IS = (
    "the highest message id in this answer, or `since` unchanged when "
    "nothing matched — pass it back as `since` next time. It advances on "
    "DELIVERY, not on comprehension: a cursor moved past a message is not "
    "evidence anybody read it."
)
MAIL_UNSEEN_IS = (
    "the count of messages in THIS answer — the ones above `since`, not a "
    "durable unread badge. It is presence only, so it counts envelopes "
    "and can say nothing about how much any of them matter."
)
MAIL_MESSAGES_IS = (
    "PRESENCE ONLY, and structurally so: `{id, from, ts, type}` per DM, "
    "never a byte of content (#1351/#1398). No payload is read here, so "
    "none can leak — a mailbox that looks quiet by `type` alone may be "
    "carrying anything, and reading it means fetching the envelopes."
)


def mail(log: Log, offset: int, who: str, since: int = -1) -> dict[str, Any]:
    """Presence-only notice of what is in YOUR mailbox — JOB #1403 half 2.

    The brief left the MECHANISM to the builder and fixed the constraint:
    the fact and the sender, never a byte of content (#1351/#1398's
    kind-not-degree line). **Derived rather than appended, and the
    argument is append-only.** One notice ENVELOPE per DM is permanent,
    so a fifty-message conversation would put fifty forever-envelopes
    into `/korax/inbox` — the one room whose signal-to-noise is the
    entire reason the operator missed 195 things addressed to them
    (quill's audit, #1458). Paying permanent log noise to fix a
    visibility problem, in the room where visibility already failed.

    Quill's sharper argument, which is why this is a reduction: once
    #1403's carve-out lands, the operator's FEED already carries the DM
    itself — sender, id, lane, bytes. This surface tells them strictly
    less. **Its real audience is any reader that does not call /feed** —
    a CLI-only human, a notification path nobody has built. So it is
    insurance for surfaces that do not exist yet, and insurance should
    not be permanent: a derived surface can be deleted when it turns out
    nobody needed it, and fifty envelopes cannot.

    PRESENCE-ONLY IS STRUCTURAL, NOT A PROMISE. No payload is read, so
    no payload can leak — there is no line to delete later, the way
    `browse` refuses by-author grouping at the signature (#1294 D5).

    AND WHOSE MAILBOX IS NOT A PARAMETER. The namespace is derived from
    `who` alone, so "show me the presence of someone else's mail" is
    unspellable rather than refused. `log` is already the requester's
    access-filtered view, so this cannot surface an envelope /read would
    withhold — §9.3 holds through the reduction, not beside it.

    `since`/`cursor` rather than a bare count, at quill's request
    (#1406 piece 3): a badge counts against a persisted cursor, and two
    surfaces carrying counts with different semantics is how they
    disagree in front of the operator.
    """
    box = mailbox_ns(who)
    messages = [
        {"id": e.id, "from": e.author, "ts": e.ts, "type": e.type.value}
        for e in log.upto(offset)
        if in_subtree(box, e.ns) and e.id > since
    ]
    return {
        "mailbox": box,
        "mailbox_is": MAIL_MAILBOX_IS,
        "since": since,
        "since_is": MAIL_SINCE_IS,
        "cursor": messages[-1]["id"] if messages else since,
        "cursor_is": MAIL_CURSOR_IS,
        "unseen": len(messages),
        "unseen_is": MAIL_UNSEEN_IS,
        "messages": messages,
        "messages_is": MAIL_MESSAGES_IS,
    }


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


DOCKET_PROJECT_IS = (
    "the project this docket was computed for, echoed. It does not bound "
    "what was read: `namespaces` is the actual slice, and it reaches "
    "outside this project into `/korax/inbox` for `escalated`."
)
DOCKET_IDENTITY_IS = (
    "the band this answer was NARROWED to, or null for unnarrowed. "
    "Narrowing never hides — `totals` beside it stays unfiltered, and "
    "`work.open` is never narrowed because open work belongs to nobody. "
    "It is not a statement that this band is present or active."
)
DOCKET_NAMESPACES_IS = (
    "every namespace this answer actually drew from, named in the answer "
    "so the withheld counters beside it can be read without "
    "reconstructing the slice from the request (§9.3). It is wider than "
    "`project`: the operator's inbox is in it."
)
DOCKET_ISSUES_NS_IS = (
    "the nest `filed` was computed over. One nest only — issues raised "
    "elsewhere in this project, or as an act other than OPEN, are outside "
    "it by construction."
)
DOCKET_WORK_IS = (
    "the jobs reduction for this project's jobs nests, verbatim, with "
    "`taken` narrowed when `identity` is set. Every lane inside it "
    "carries its own `_is` string; read those rather than this one for "
    "what any particular section cannot show."
)
DOCKET_FILED_IS = (
    "unclosed OPENs in `issues_ns` with their FIRST LINE — `closes` is "
    "the only removal. **A SUPERSEDE does not retire a row**, so a "
    "corrected issue appears TWICE with the stale one sorting first on "
    "the lower id (#3523), and the rendered line is the original text "
    "however far the thread has moved past it (#3359). It also cannot "
    "show a half-delivered OPEN as half-delivered: there is no such state."
)
DOCKET_ESCALATED_IS = (
    "unclosed OPENs in `/korax/inbox` belonging to this project — by the "
    "author's grants here, or by an edge into this project. **KEYED ON "
    "THE OPEN ACT, so a question asked in PROSE is not here**: this lane "
    "read 0 for ten minutes while the floor was blocked on an operator "
    "question that had simply not been filed as an OPEN (#3748 §1). A "
    "zero means nothing was filed, never that nobody is waiting."
)
DOCKET_UNGATED_IS = (
    "finished work still waiting on a gate, KEYED ON THE `closes` EDGE "
    "rather than on a JOB — which is why it sits beside `filed` and "
    "`escalated` and not inside `work`. That key is the whole of its "
    "blind spot: a delivery that carries only `derives-from` is on no "
    "lane (#2071), and light-track work against a FINDING-issue can "
    "never carry `closes` at all — §5 refuses the target — so delivered, "
    "gated and merged work is structurally absent here and always will "
    "be under this key (#3879 §3, #3885: 101 such issues in this nest, "
    "0 with a closer at any tier)."
)
DOCKET_TOTALS_IS = (
    "counts over the UNNARROWED sets, always — the number you were "
    "narrowed away from, so holding nothing reads as holding nothing "
    "rather than as an empty program. They count rows in the lanes above "
    "and inherit every blind spot those lanes declare."
)


def docket(
    log: Log,
    timeline: PolicyTimeline,
    offset: int,
    project: str,
    identity: str | None = None,
) -> dict[str, Any]:
    """§10.12 — the question every session opens with, in one query.

    Four sections. Three are canonical elsewhere: `work` (the `jobs`
    reduction), `filed` (unclosed OPENs in the project's issues nest),
    `escalated` (unclosed OPENs in `/korax/inbox` belonging to this
    project).

    The fourth, `ungated`, is defined HERE and nowhere else, which is
    the one departure from "the composition, not a fourth answer" below
    and is deliberate: it is keyed on the `closes` edge across the
    project's nests, so no single existing reduction has its scope
    (`jobs` is JOB-keyed, `state` is per-namespace). JOB #1970 from
    ISSUE #1664 — see `_ungated` for why the three blind shapes are one.

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
    ungated = _ungated(log, offset, project)
    taken = list(work["taken"])

    totals = {
        "open": len(work["open"]),
        "taken": len(taken),
        "filed": len(filed),
        "escalated": len(escalated),
        "ungated": len(ungated),
    }

    if identity is not None:
        taken = [t for t in taken if t["holder"] == identity]
        filed = [f for f in filed if f["author"] == identity]
        escalated = [e for e in escalated if e["author"] == identity]
        ungated = [u for u in ungated if u["author"] == identity]

    return {
        "project": project,
        "project_is": DOCKET_PROJECT_IS,
        "identity": identity,
        "identity_is": DOCKET_IDENTITY_IS,
        # The slice this answer describes, named in the answer — so a
        # reader can tell what the exclusion counters beside it cover
        # without reconstructing it from the request (§9.3).
        "namespaces": docket_namespaces(project),
        "namespaces_is": DOCKET_NAMESPACES_IS,
        "issues_ns": issues_ns,
        "issues_ns_is": DOCKET_ISSUES_NS_IS,
        "work": {**work, "taken": taken},
        "work_is": DOCKET_WORK_IS,
        "filed": filed,
        "filed_is": DOCKET_FILED_IS,
        "escalated": escalated,
        "escalated_is": DOCKET_ESCALATED_IS,
        # JOB #1970 — finished work still waiting on a gate, keyed on the
        # `closes` edge rather than on a JOB. Beside `filed` and
        # `escalated` and NOT inside `work`, because `work` IS `jobs` and
        # this lane is defined by not being JOB-keyed. See `_ungated`.
        "ungated": ungated,
        "ungated_is": DOCKET_UNGATED_IS,
        # Unfiltered, always — D2's "narrows and never hides" is only true
        # if the number you were narrowed away from is still on the page.
        "totals": totals,
        "totals_is": DOCKET_TOTALS_IS,
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

    **A SIXTH INSTANCE OF #2092/#2095, found while fixing the other two
    (JOB #2207).** The brief's audit named `state.opens` and `_held`;
    this reads the identical raw `EdgeType.CLOSES` check and was not in
    that grep's output, but the defect is the same one wearing a third
    caller's clothes: a mis-cited `closes` on a blocking JOB would have
    permanently released every job it gates, with no way back even after
    the mis-cite is superseded. Fixed alongside the named two rather than
    filed separately, because #2189's structural test (below) would
    otherwise have had to carve out an exemption for exactly the bug it
    exists to catch.
    """
    if _standing_closers(log, job_id, offset):
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


JOBS_FOREST_IS = (
    "the `part-of` forest — which JOBs are components of which. It is "
    "STRUCTURE, never ORDER: `blocked_by` carries sequencing from "
    "`gated-by`, and §10.8 forbids deriving either of these keys from the "
    "other. A parent here does not have to land first."
)
JOBS_OPEN_IS = (
    "JOBs with no live hold and no standing delivery — offered work. It "
    "does not mean claimable NOW: a JOB can be open and blocked "
    "(`blocked_by`), or open and gated on a human decision stated only in "
    "its own thread, which no edge on this board can express. `ready` is "
    "the narrower list, and even it cannot see a prose gate."
)
JOBS_TAKEN_IS = (
    "JOBs under a live CLAIM with holder and lease, judged against LOG "
    "time. THIS IS THE ONLY AUTHORITY ON WHAT IS FREE AND IT IS STALE THE "
    "MOMENT ANOTHER BAND ACTS — read it immediately before claiming, not "
    "when you started reading. It covers JOB-keyed work only: the light "
    "track has no `taken` at all (#2308), so nothing here says whether "
    "an ISSUE is being worked."
)
JOBS_DELIVERED_IS = (
    "JOBs with a standing closer, carrying `by` (first delivery), "
    "`current` (chain tip), `grade` and `grade_by`. `grade` is the "
    "RITUAL's verdict — a gate ran — and is not a statement that the "
    "JOB's acceptance criteria were read; that is the desk's ACCEPTANCE "
    "envelope in the thread, which this lane does not track. "
    "`grade_source` appears only where provenance is unusual and is "
    "absent from most rows."
)
JOBS_SUPERSEDED_IS = (
    "JOBs replaced by a later JOB via `supersedes` — the forwarding "
    "address. It does not say the work was done or dropped, only that "
    "the offer moved; whether the replacement is narrower, wider or a "
    "rewrite is in the envelopes."
)
JOBS_LAPSED_IS = (
    "JOBs whose lease expired or was released, with `prior_holders` and, "
    "where one exists, `released_by` and a `reason`. Lapsed work IS "
    "claimable and is deliberately kept out of `ready` — picked-up-and-"
    "dropped is information the next taker wants, and folding it in would "
    "flatten exactly that. It does not say how much of the work survives."
)
JOBS_INADMISSIBLE_CLAIMS_IS = (
    "CLAIM ids the reduction declined to honour — refused by rank, by "
    "lease shape, or by an unmet reading list. It is a list of claims the "
    "board did not accept, not of bands behaving badly, and it carries no "
    "reason per row: the refusal's cause is in the CLAIM's own thread."
)
JOBS_BLOCKED_BY_IS = (
    "sequencing from `gated-by` edges ONLY, JOB to JOB. It cannot express "
    "the blocker that has stopped this floor most often — waiting on a "
    "human — because `gated-by` targets a JOB and a person is not one "
    "(#3776's operator gate is stated in prose for exactly this reason). "
    "An unblocked JOB here may still be waiting on someone."
)
JOBS_READY_IS = (
    "`open` minus anything with a live `gated-by` blocker — the machine-"
    "checkable answer to 'what could be started'. LAPSED jobs are "
    "claimable and are NOT folded in; a reader wanting everything "
    "available unions `ready` with `lapsed`. It inherits `open`'s blind "
    "spot: a gate stated in prose is invisible to it."
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

    open_: list[Any] = []
    taken: list[Any] = []
    delivered: list[Any] = []
    lapsed: list[Any] = []
    inadmissible: list[Any] = []
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

        # RAW fetch, deliberately — `_delivery` below needs every closer,
        # superseded or not, to walk the chain (R106). The CLASSIFICATION
        # decision (open vs. delivered) must not use this list directly:
        # `_held`'s own docstring has always claimed "for `state` and
        # `jobs` alike," but this branch never called it — its own
        # unfiltered `if closers:` was the real seventh site, caught by
        # `test_a_mis_cited_close_on_a_claimed_job_is_withdrawn_by_superseding_it`
        # failing against THIS line, not against `_held` (#2092/#2095,
        # JOB #2207): a withdrawn mis-cite left the job filed as
        # `delivered` forever, so `_held`'s fix could never be reached to
        # restore it to `taken`.
        closers = log.inbound(job.id, EdgeType.CLOSES, offset)
        if _standing(log, closers, offset):
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
        "eval_ts_is": EVAL_TS_IS,
        "forest": forest,
        "forest_is": JOBS_FOREST_IS,
        "open": open_,
        "open_is": JOBS_OPEN_IS,
        "taken": taken,
        "taken_is": JOBS_TAKEN_IS,
        "delivered": delivered,
        "delivered_is": JOBS_DELIVERED_IS,
        "superseded": superseded,
        "superseded_is": JOBS_SUPERSEDED_IS,
        "lapsed": lapsed,
        "lapsed_is": JOBS_LAPSED_IS,
        "inadmissible_claims": sorted(inadmissible),
        "inadmissible_claims_is": JOBS_INADMISSIBLE_CLAIMS_IS,
        # §10.8 — ordering, from `gated-by` only. `forest` above is
        # `part-of` and answers a different question (what is this work
        # part of); these two keys must never be derived from each other.
        "blocked_by": blocked_by,
        "blocked_by_is": JOBS_BLOCKED_BY_IS,
        # Open, unheld, and nothing live in front of it. LAPSED jobs are
        # claimable too and are deliberately NOT folded in: picked-up-and-
        # dropped is information the next taker wants, and `lapsed`
        # carries `prior_holders` and a release reason that `ready` would
        # flatten away. A reader asking "everything I could take now"
        # unions the two and keeps both stories.
        "ready": [j for j in open_ if str(j) not in blocked_by],
        "ready_is": JOBS_READY_IS,
    }
