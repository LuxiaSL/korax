"""`why(id)` — what HAPPENED to an envelope, as a server reduction.

JOB #3765 (v2 R2). Ported from `clients/mcp/korax_mcp/why.py` (#2269,
R127), which shipped as a CLIENT-side composition over `/neighbourhood`
and `/search`. Two consequences the port closes: the verb was absent
from the server's suite and unavailable to any other client, and one
answer had to be re-implemented per client — the drift #2141 names.

WHY `gated` CHANGED, IN THE FILER'S OWN WORDS (#3700, amendment 5 at
#4025 — cited rather than paraphrased because the diagnosis has already
survived once by being independently reinvented instead of read):

    "The defect is one word. `gated` invites 'was this gated' and
     answers 'is anything attested on anything this points at.' Every
     route underneath is correct. A reader who opens `routes` is fine; a
     reader who trusts the summary is not — and the summary is what a
     summary is for."

**The routes were never the defect and are not changed.** A summary
key's NAME is a promise about what was checked, and that is the whole of
property 3.

WHAT CHANGED IN THE MOVE, AND IT IS NOT THE ROUTES. The four routes and
their `searched` / `not-applicable` / `bounded` distinction are carried
over intact; that part was right and #3700 said so. What is fixed here
is `gated`, which answered a different question than its name asked:
it was fed by the two TARGET routes, so it reported "something attested
on something this points at" under a key a reader takes to mean "this
was gated". On an OPEN — which cannot be gated at all — it answered
`true` with five confident ids (#3700). Now:

  * `gated` is fed by INBOUND edges only: an attesting envelope carrying
    an edge TO THIS SUBJECT.
  * what `gated` used to report has its own key, `attested_on_targets`,
    with the same shape, so nothing is lost — it is relabelled.
  * a subject the jobs reduction would never treat as a delivery reports
    `not-applicable` with a reason naming its own act, rather than
    `false` (which would assert a gate was looked for and missed).

`ROUTE_NAMES` is the declared table and every entry reports on every
call, including the empty ones — that is the whole contract of this verb
(#2183 family A: a route that ran and found nothing, one that could not
apply, and one that hit a limit are three different facts).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .log import Log
from .models import BAND_RANK, Act, Band, Envelope, Grade

#: #2205's three rows and not a character more — `invalidates` is
#: deliberately absent pending the ruling asked for at #2242. Carried as
#: a LABEL here, never a refusal.
STATE_CHANGING: frozenset[str] = frozenset({"supersedes", "closes"})
CONVERSATIONAL: frozenset[str] = frozenset(
    {"replies", "beside", "derives-from", "corroborates", "endorses", "acks"}
)

#: `verified` ONLY, and the narrowness is measured. `unverified` is what
#: a delivery posts itself with, so it attests nothing; `n/a` is the
#: ABSENCE of grading, assigned by the board for every ungraded nest —
#: reading `!= unverified` as attestation would label all of
#: `/korax-dev/issues` as gated.
ATTESTING_GRADES: frozenset[str] = frozenset({Grade.VERIFIED.value})

#: An inbound `stamps` edge is the operator's attestation landing on the
#: subject. Caught on the EDGE because `stamped` is an effective grade
#: that never appears in the `grade` field.
STAMPING_EDGES: frozenset[str] = frozenset({"stamps"})

#: Acts the jobs reduction can treat as a delivery. Property 4: anything
#: else reports `gated: not-applicable`, because "was this gated" is not
#: a false question about a PROPOSAL, it is a category error.
DELIVERY_ACTS: frozenset[Act] = frozenset({Act.FINDING, Act.SUPERSEDE})

# ── `why`'s lane strings (JOB #3774's rule, applied at birth) ─────────
#
# R171 made a served lane without an `_is` twin a test failure, and this
# view reddened that sweep the moment it was wired. Written here rather
# than bolted on: the rule is that a section is born with its twin.

WHY_IS = (
    "the id you asked about, echoed. It is not a claim the envelope is "
    "interesting or that anything happened to it — the routes below say "
    "that, each for its own question."
)
SUBJECT_IS = (
    "the subject's own card — id, act, ns, author, grade, ts, pointer "
    "sha. It is the envelope AS STORED, not its chain tip: if this "
    "envelope has been superseded, `answers.superseded` says so and this "
    "block still describes the one you named."
)
ANSWERS_IS = (
    "plain-language summaries, each naming the routes it was computed "
    "from. **A key is fed only by routes whose question matches its "
    "name** — the rule this reduction exists to enforce (#2876/#3700, "
    "where `gated` was fed by target routes and answered `true` on an "
    "OPEN). Each answer is `true`/`false`/`not-applicable`, never two "
    "states pretending to be three."
)
ROUTES_IS = (
    "every declared route's own report — question, status, basis, and "
    "what it found. **`searched`, `not-applicable` and `bounded` are "
    "three different facts** and an empty `found` means nothing until "
    "you read the status beside it. Every route reports on every call, "
    "including the empty ones."
)
ROUTES_DECLARED_IS = (
    "the route table this answer was computed against, so a reader can "
    "tell a route that reported nothing from a route that was never "
    "run. A mismatch between this and the reports raises rather than "
    "serving a short answer that looks complete."
)
BOUNDS_IS = (
    "what each route could not see, PER SOURCE and never summed — a "
    "total across routes would name no scope at all (§9.3). It reports "
    "what was withheld from THIS requester; it cannot report what no "
    "grant of yours reaches, and `any_withheld_or_bounded` is the one "
    "flag that says a negative answer here is not entitled to be flat."
)


ROUTE_NAMES: tuple[str, ...] = (
    "inbound-edges",
    "closes-on-target",
    "attested-on-target",
    "sha-in-prose",
)


@dataclass(frozen=True)
class RouteReport:
    """One route's answer, including the answer "I could not look".

    `status` is what makes an empty `found` readable: `searched` ran over
    the slice you can see; `not-applicable` could not apply to THIS
    SUBJECT and says why in terms of the subject; `bounded` hit a limit,
    so absence past it proves nothing. Collapsing any two is the defect.
    """

    route: str
    question: str
    status: str
    found: tuple[dict[str, Any], ...]
    basis: str

    def as_json(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "question": self.question,
            "status": self.status,
            "found": list(self.found),
            "count": len(self.found),
            "basis": self.basis,
        }


def _card(env: Envelope, dump: Callable[[Envelope], dict[str, Any]], *,
          why: str, edges: Sequence[str] = ()) -> dict[str, Any]:
    """An envelope's card: enough to decide whether to fetch it, never a
    projection presented as the whole (§13). Mirrors `search._summary`
    so one reader learns one shape."""
    d = dump(env)
    card: dict[str, Any] = {
        k: d[k] for k in ("id", "ts", "author", "band", "ns", "type", "grade")
        if k in d
    }
    card["why"] = why
    if edges:
        card["edges"] = list(edges)
    return card


def _inbound_edges_toward(log: Log, subject_id: int, offset: int) -> dict[int, list[str]]:
    """Every envelope carrying ANY edge to the subject, with those edges.

    One walk rather than one per edge type: the client asked
    `/neighbourhood` and filtered, and doing it edge-by-edge here would
    make the route's cost proportional to the vocabulary rather than to
    the log.
    """
    toward: dict[int, list[str]] = {}
    for env in log.upto(offset):
        if env.id == subject_id:
            continue
        hits = [ref.edge.value for ref in env.refs if ref.id == subject_id]
        if hits:
            toward[env.id] = sorted(set(hits))
    return toward


def route_inbound(
    log: Log, subject: Envelope, offset: int, dump: Callable[[Envelope], dict[str, Any]]
) -> RouteReport:
    """Route 1 — what points AT this envelope."""
    found: list[dict[str, Any]] = []
    for env_id, edges in sorted(_inbound_edges_toward(log, subject.id, offset).items()):
        env = log.get(env_id)
        if env is None:
            continue
        card = _card(env, dump, why="edge-to-subject", edges=edges)
        card["asserting_edges"] = sorted(set(edges) & STATE_CHANGING)
        card["conversational_edges"] = sorted(set(edges) & CONVERSATIONAL)
        found.append(card)
    return RouteReport(
        route="inbound-edges",
        question="what carries an edge TO this envelope?",
        status="searched",
        found=tuple(found),
        basis=f"every envelope at or before offset {offset} carrying an edge to #{subject.id}",
    )


def _outbound_targets(subject: Envelope, edge: str | None = None) -> list[int]:
    return sorted({
        ref.id for ref in subject.refs
        if edge is None or ref.edge.value == edge
    })


def route_closes_on_target(
    log: Log, subject: Envelope, offset: int, dump: Callable[[Envelope], dict[str, Any]]
) -> RouteReport:
    """Route 2 — the one the fixture exists for.

    A gate names a delivery without pointing at it: #828 closes JOB #713
    and says "#800" only in prose. So this route ignores the subject's
    inbound edges entirely, takes what the SUBJECT closes, and asks what
    ELSE closed the same thing.
    """
    targets = _outbound_targets(subject, edge="closes")
    question = "did anything else dispose of what this envelope closes?"
    if not targets:
        return RouteReport(
            route="closes-on-target", question=question, status="not-applicable",
            found=(),
            basis=(
                f"the subject is a {subject.type.value} carrying no `closes` edge, "
                "so it has no target to share — this is a property of the subject, "
                "not an empty board"
            ),
        )
    found: list[dict[str, Any]] = []
    for target in targets:
        for env in log.upto(offset):
            if env.id == subject.id:
                continue
            edges = [r.edge.value for r in env.refs if r.id == target]
            if "closes" not in edges:
                continue
            grade = env.grade.value if env.grade else None
            why = (
                f"also closes #{target}" if grade not in ATTESTING_GRADES
                else f"closes #{target} and is graded {grade}"
            )
            found.append(_card(env, dump, why=why, edges=sorted(set(edges))))
    found.sort(key=lambda c: c.get("id") or 0)
    return RouteReport(
        route="closes-on-target", question=question, status="searched",
        found=tuple(found),
        basis=("targets " + ", ".join(f"#{t}" for t in targets)
               + "; envelopes that also close them"),
    )


def route_attested_on_target(
    log: Log, subject: Envelope, offset: int, dump: Callable[[Envelope], dict[str, Any]]
) -> RouteReport:
    """Route 3 — a graded FINDING on the subject's target.

    Separate from route 2 on purpose: a gate that CLOSES the JOB is
    caught there; one that only derives-from or replies-to it while
    carrying `verified` is caught here, and collapsing the two makes the
    second invisible whenever the first fires.
    """
    targets = _outbound_targets(subject)
    question = "is anything on this envelope's targets carrying a grade?"
    if not targets:
        return RouteReport(
            route="attested-on-target", question=question, status="not-applicable",
            found=(),
            basis=(
                f"the subject is a {subject.type.value} carrying no outbound edges, "
                "so it shares no target"
            ),
        )
    found: list[dict[str, Any]] = []
    seen: set[int] = set()
    for target in targets:
        for env in log.upto(offset):
            if env.id == subject.id or env.id in seen:
                continue
            if not any(r.id == target for r in env.refs):
                continue
            if (env.grade.value if env.grade else None) not in ATTESTING_GRADES:
                continue
            seen.add(env.id)
            found.append(_card(
                env, dump,
                why=f"graded {env.grade.value} and edged to #{target}",
                edges=sorted({r.edge.value for r in env.refs if r.id == target}),
            ))
    found.sort(key=lambda c: c.get("id") or 0)
    return RouteReport(
        route="attested-on-target", question=question, status="searched",
        found=tuple(found),
        basis=("targets " + ", ".join(f"#{t}" for t in targets)
               + "; entries graded " + "/".join(sorted(ATTESTING_GRADES))),
    )


def _payload_text(env: Envelope) -> str:
    """Everything on this envelope a sha could have been written into."""
    payload = env.payload
    if isinstance(payload, str):
        return payload
    if payload is None:
        return ""
    return str(payload)


def route_sha_in_prose(
    log: Log, subject: Envelope, offset: int, dump: Callable[[Envelope], dict[str, Any]]
) -> RouteReport:
    """Route 4 — the subject pins a sha; who else says that sha out loud.

    A branch sha travels in prose far more than it travels in edges: a
    gate quotes the sha it merged, a WARN quotes the sha it warns about.
    None of that is an edge and none of it is reachable by any walk.
    """
    sha = subject.pointer.sha256 if subject.pointer else None
    question = "does anything quote this envelope's pinned sha?"
    if not sha:
        return RouteReport(
            route="sha-in-prose", question=question, status="not-applicable",
            found=(),
            basis=(
                f"the subject is a {subject.type.value} carrying no pointer sha256, "
                "so there is no string to search for — not a claim that nothing "
                "quotes it"
            ),
        )
    needle = sha[:12]
    found = [
        _card(env, dump, why=f"quotes {needle} in prose")
        for env in log.upto(offset)
        if env.id != subject.id and needle in _payload_text(env)
    ]
    found.sort(key=lambda c: c.get("id") or 0)
    return RouteReport(
        route="sha-in-prose", question=question, status="searched",
        found=tuple(found),
        basis=(
            f"substring {needle} over every payload at or before offset {offset}; "
            "no limit applied, so an empty result is a searched slice rather than "
            "a truncated one"
        ),
    )


def _gateable(log: Log, subject: Envelope, offset: int) -> tuple[bool, str]:
    """Could this subject be gated at all? Property 4.

    "Was this gated" is not a FALSE question about a PROPOSAL or an OPEN;
    it is a category error, and answering `false` asserts a gate was
    looked for and missed. The two roads onto the delivery lane are the
    ones the board actually uses: the marker (#2073) and a `closes` edge
    onto a JOB.
    """
    ext = subject.ext or {}
    korax = ext.get("korax") if isinstance(ext, Mapping) else None
    if isinstance(korax, Mapping) and korax.get("delivery") is not None:
        return True, "carries ext.korax.delivery"
    for ref in subject.refs:
        if ref.edge.value != "closes":
            continue
        target = log.get(ref.id)
        if target is not None and target.id <= offset and target.type == Act.JOB:
            return True, f"closes JOB #{target.id}"
    act = subject.type.value
    article = "an" if act[0] in "AEIOU" else "a"
    return False, (
        f"{article} {act} carrying neither ext.korax.delivery nor a `closes` "
        f"edge onto a JOB is not a delivery, so there is no gate for it to have — "
        f"this is a property of the subject, not a search that came back empty"
    )


def _attests(env: Envelope, edges: Sequence[str]) -> bool:
    """Does this inbound envelope attest to the subject?

    Grade OR a `stamps` edge: `stamped` is an effective grade that never
    appears in the `grade` field, so testing the grade alone would answer
    "nothing gated this" about a stamped envelope.
    """
    graded = (env.grade.value if env.grade else None) in ATTESTING_GRADES
    return graded or bool(set(edges) & STAMPING_EDGES)


def summarise(
    log: Log, subject: Envelope, offset: int, reports: Sequence[RouteReport]
) -> dict[str, Any]:
    """The plain-language answers, each naming the routes it came from.

    **This is where JOB #3765's defect lived.** `gated` used to be fed by
    the two TARGET routes as well as the inbound one, so it reported
    "something attested on something this points at" under a key every
    reader takes to mean "this was gated". The rule, stated so the next
    key cannot repeat it: **no summary key may be fed by a route whose
    question differs from the key's name.**
    """
    by_route = {r.route: r for r in reports}

    def inbound_cards() -> list[dict[str, Any]]:
        rep = by_route.get("inbound-edges")
        return list(rep.found) if rep is not None else []

    def inbound_with(edge: str) -> list[int]:
        return [
            c["id"] for c in inbound_cards()
            if edge in (c.get("edges") or []) and c.get("id") is not None
        ]

    def answer(ids: Sequence[int], routes: str) -> dict[str, Any]:
        return {"answer": bool(ids), "ids": sorted(set(ids)), "from_routes": routes}

    # ── gated: INBOUND ONLY, desk-rank, on a subject that can be gated ──
    gateable, reason = _gateable(log, subject, offset)
    gates: list[int] = []
    if gateable:
        for card in inbound_cards():
            cid = card.get("id")
            if not isinstance(cid, int):
                continue
            env = log.get(cid)
            if env is None:
                continue
            if BAND_RANK.get(env.band, 0) < BAND_RANK[Band.DESK]:
                continue
            if _attests(env, card.get("edges") or []):
                gates.append(env.id)

    # ── what `gated` used to report, computed first: `indirect` needs it ──
    attested: list[int] = []
    for route in ("closes-on-target", "attested-on-target"):
        rep = by_route.get(route)
        if rep is None:
            continue
        attested.extend(
            c["id"] for c in rep.found
            if c.get("grade") in ATTESTING_GRADES and c.get("id") is not None
        )
    attested = sorted(set(attested))

    # ── the four-way answer, ruled at #4022 ──
    #
    # `indirect` is not a compatibility shim for the historical convention;
    # it is the true answer. Before #2073 a gate named its delivery in
    # PROSE and edged only the JOB — #828 gates #800 and carries no edge
    # to it — so on 24 of 100 verified deliveries the attestation exists
    # and genuinely lives one hop away (#4020's census). A binary `gated`
    # has to lie about those in one direction or the other: `true` claims
    # an attestation on this envelope that is not there, `false` tells the
    # reader the verb was built for that its founding delivery was never
    # gated. Three states carry the fact instead of choosing a lie.
    if not gateable:
        gated: dict[str, Any] = {
            "answer": "not-applicable",
            "ids": [],
            "from_routes": "inbound-edges",
            "reason": reason,
        }
    elif gates:
        gated = answer(gates, "inbound-edges (`verified` FINDINGs and inbound "
                              "`stamps`, desk rank or above, carrying an edge TO "
                              "the subject)")
        gated["gateable_because"] = reason
    elif attested:
        gated = {
            "answer": "indirect",
            "ids": attested,
            "from_routes": "closes-on-target + attested-on-target",
            "reason": (
                "nothing attesting carries an edge to THIS envelope, but an "
                "attestation sits on what it points at — the pre-#2073 gating "
                "convention, where a gate named its delivery in prose and edged "
                "only the JOB. The ids are the attesting envelopes."
            ),
            "gateable_because": reason,
        }
    else:
        gated = answer(gates, "inbound-edges (`verified` FINDINGs and inbound "
                              "`stamps`, desk rank or above, carrying an edge TO "
                              "the subject)")
        gated["gateable_because"] = reason

    cited: list[int] = []
    for rep in reports:
        for c in rep.found:
            cid = c.get("id")
            if cid is not None and cid not in cited:
                cited.append(cid)

    return {
        "gated": gated,
        "attested_on_targets": answer(
            attested,
            "closes-on-target + attested-on-target (attestations on what this "
            "envelope points at — NOT on the envelope itself)",
        ),
        "disposed": answer(
            inbound_with("closes"), "inbound-edges (`closes` toward the subject)"
        ),
        "superseded": answer(
            inbound_with("supersedes"), "inbound-edges (`supersedes` toward the subject)"
        ),
        "stamped": answer(
            [c["id"] for c in inbound_cards()
             if c.get("id") is not None and set(c.get("edges") or ()) & STAMPING_EDGES],
            "inbound-edges (`stamps` toward the subject)",
        ),
        "cited": answer(cited, "every route"),
    }


def _bounds(
    subject: Envelope, reports: Sequence[RouteReport], withheld: Sequence[Sequence[Envelope]]
) -> dict[str, Any]:
    """What each route could not see, PER SOURCE and never summed.

    `why` answers in the negative constantly — "nothing superseded this"
    — and a negative computed over a slice that withheld envelopes is not
    entitled to be stated flatly. Summing across routes would produce a
    number naming no scope at all, which is why each route reports its
    own (§9.3, and #3700's praise for the client's version, kept).
    """
    hidden = [e for group in withheld for e in group]
    sources: list[dict[str, Any]] = []
    blind = False
    for rep in reports:
        if rep.status == "not-applicable":
            n = 0  # nothing was read, so nothing was withheld from the reading
        else:
            n = len(hidden)
        if n:
            blind = True
        sources.append({
            "source": rep.route,
            "withheld_scope": "board",
            "sealed_excluded": n,
            "status": rep.status,
        })
        if rep.status == "bounded":
            blind = True
    return {"sources": sources, "any_withheld_or_bounded": blind}


def why(
    log: Log,
    offset: int,
    env_id: int,
    withheld: Sequence[Sequence[Envelope]] = (),
    dump: Callable[[Envelope], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """§10.13 — every route, every call, each naming its own basis."""
    subject = log.get(env_id)
    if subject is None or subject.id > offset:
        raise LookupError(f"no envelope {env_id} at offset {offset}")
    emit = dump or (lambda e: e.model_dump(mode="json", exclude_none=True))

    reports = [
        route_inbound(log, subject, offset, emit),
        route_closes_on_target(log, subject, offset, emit),
        route_attested_on_target(log, subject, offset, emit),
        route_sha_in_prose(log, subject, offset, emit),
    ]
    emitted = tuple(r.route for r in reports)
    if emitted != ROUTE_NAMES:
        raise AssertionError(
            f"route table drift: declared {ROUTE_NAMES}, emitted {emitted}. "
            "Every declared route must report, including the empty ones — that "
            "is the whole contract of this verb (#2183 family A)."
        )

    return {
        "why": subject.id,
        "why_is": WHY_IS,
        "subject_is": SUBJECT_IS,
        "answers_is": ANSWERS_IS,
        "routes_is": ROUTES_IS,
        "routes_declared_is": ROUTES_DECLARED_IS,
        "bounds_is": BOUNDS_IS,
        "subject": {
            "id": subject.id,
            "type": subject.type.value,
            "ns": subject.ns,
            "author": subject.author,
            "grade": subject.grade.value if subject.grade else None,
            "ts": subject.ts.isoformat().replace("+00:00", "Z") if subject.ts else None,
            "pointer_sha256": subject.pointer.sha256 if subject.pointer else None,
        },
        "answers": summarise(log, subject, offset, reports),
        "routes": [r.as_json() for r in reports],
        "routes_declared": list(ROUTE_NAMES),
        "bounds": _bounds(subject, reports, withheld),
    }
