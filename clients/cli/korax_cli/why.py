"""`korax why <id>` — the disposition of one envelope, every route labeled.

JOB #2209, T1 Shape 3. Brief `briefs/t1-deck-integrity.md @ 8346ba8`.

THE QUESTION THIS ANSWERS: *what happened to this envelope* — was it
gated, disposed, superseded, merely cited. Today that costs three calls
in a guessed order plus a join by eye, and the guess is the defect: you
pick an edge key first, and the key you did not pick is the answer you
do not get. #800 is the standing example. Its gate is #828, which
carries **no edge to #800 at all** — `closes:713` and `replies:809`. A
reader who asks "what points at #800" is told nothing points at it, and
that is true, and the delivery was verified four hours earlier.

SO THE ROUTES ARE A TABLE, NOT A CODE PATH. Every route in `ROUTES`
runs on every call and reports itself in the output whether or not it
found anything — including the ones that could not run. That is
family A discipline (#2183): *the read path returns empty instead of
failing* is the most persistent defect on this log, eleven instances
across six bands, and every one of them was a successful call shaped
like a successful call. A route that finds nothing and a route that
never ran are different facts, so they get different `status` values
and both get printed.

THE BOUND IS PART OF THE ANSWER. Every route here is composed from
bounded reads that each report what they withheld. An aggregate that
dropped those counters would answer "nothing gated this" over a slice
that was never entitled to say so — the same false-completeness claim
`ViewResult` and `_CountedResult` were written to prevent, one layer
up. `WhyResult` carries the union, and `complete` is false whenever any
route was bounded or blind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping, Sequence

# Edges that assert something happened TO the subject, as against edges
# that merely talk about it. The split is the mill's, ruled at #2205 and
# banked by the seat at #2206: `supersedes`/`closes`/a graded FINDING say
# the subject's basis moved; `replies`/`beside`/`derives-from`/
# `corroborates` say the board is busy. Shape 2 keys a REFUSAL on this
# distinction; Shape 3 keys a LABEL on it — the same vocabulary spent on
# a cheaper decision, because nothing here refuses anything.
#
# THE SET IS #2205'S THREE ROWS AND NOT A CHARACTER MORE. `invalidates`
# reads state-changing to me and is deliberately absent: the mill asked
# the gavel at #2242 whether the set takes a fourth row (for `stamps`),
# which makes widening it a live design question owned by another seat.
# A label that quietly ran ahead of the ruling would put this client's
# opinion where a ruling belongs, and the next reader could not tell
# which they were looking at.
STATE_CHANGING: frozenset[str] = frozenset({"supersedes", "closes"})
CONVERSATIONAL: frozenset[str] = frozenset(
    {"replies", "beside", "derives-from", "corroborates", "endorses", "acks"}
)

# A FINDING carrying this grade is an attestation about its targets.
#
# `verified` ONLY, and the narrowness is measured rather than assumed
# (the mill, #2242, verified here against source before adopting).
# `unverified` is the default a delivery posts itself with, so it
# attests nothing — #800 is `unverified` and is the DELIVERY; #828 is
# `verified` and is the GATE. And `n/a` is not a weaker attestation but
# the ABSENCE of grading, assigned by the board rather than chosen:
# `validate.py:342-350` resolves it for every ungraded nest and every
# structural act, so in `/korax-dev/issues` (policy 283, `grades:
# false`) it is the only grade an envelope can legally carry, across
# ~97 FINDINGs. Reading `!= unverified` as attestation would label that
# entire nest as gated.
#
# `stamped` IS NOT A MEMBER AND MUST NOT BE ADDED HERE. `Grade` is
# exactly `unverified | verified | n/a` (`models.py:75-83`, read at this
# sha): `stamped` is an EFFECTIVE grade reached via a `stamps` edge and
# is never asserted on an envelope, so a membership test against it can
# never fire. It would be a dead branch that reads as coverage of the
# single most state-changing act on the board. STAMPs are caught by the
# inbound-edge route instead, where they actually live.
ATTESTING_GRADES: frozenset[str] = frozenset({"verified"})

# An inbound `stamps` edge is the operator's attestation landing on the
# subject, and it is the strongest disposition this board has.
#
# THE ASYMMETRY WITH SHAPE 2 IS THE POINT, and it is why this needs no
# ruling to be here: #2242 asks the gavel whether the state-changing set
# takes `stamps` as a fourth row, because for Shape 2 that widens what
# gets REFUSED, and a wrong refusal trains the override. Shape 3 refuses
# nothing — reporting that a STAMP landed is not widening a refusal set,
# it is declining to hide an edge the board already serves. Omitting it
# pending the ruling would make `why` answer "nothing gated this" about
# a stamped envelope, which is the exact failure this verb exists to
# prevent.
STAMPING_EDGES: frozenset[str] = frozenset({"stamps"})


@dataclass(frozen=True)
class RouteReport:
    """One route's answer, including the answer 'I could not look'.

    `status` is the field that makes an empty `found` readable:

      searched         the route ran over the slice you can see and
                       found what is listed (possibly nothing)
      not-applicable   the route cannot apply to this subject — it
                       carries no pointer, or no outbound edges — so
                       an empty list here is a property of the subject,
                       not a fact about the board
      bounded          the route ran but hit a walk budget or limit, so
                       absence within it proves nothing
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
            "count": len(self.found),
            "found": list(self.found),
            "basis": self.basis,
        }


def _edges_toward_subject(edges: Sequence[str]) -> list[str]:
    """`<-closes` means the neighbour closes the subject. `closes->` means
    the subject closes the neighbour. The neighbourhood reduction encodes
    direction in the string itself (server/korax/search.py:197-202) and
    both directions land in the same list, so reading one as the other is
    a silent inversion — the answer would name the subject's own targets
    as things that disposed of it."""
    return [e[2:] for e in edges if e.startswith("<-")]


def _edges_from_subject(edges: Sequence[str]) -> list[str]:
    return [e[:-2] for e in edges if e.endswith("->")]


def hop_one(neighbourhood: Mapping[str, Any]) -> list[dict[str, Any]]:
    for hop in neighbourhood.get("hops") or ():
        if isinstance(hop, Mapping) and hop.get("depth") == 1:
            nodes = hop.get("nodes") or ()
            return [n for n in nodes if isinstance(n, dict)]
    return []


def _card(node: Mapping[str, Any], *, why: str, edges: Sequence[str] = ()) -> dict[str, Any]:
    """A found entry always says WHY it is in this list. A pile of ids
    would make the caller re-derive the reason the walk already knew —
    the same argument the neighbourhood reduction makes for carrying its
    edges (search.py:175-177)."""
    card = {
        "id": node.get("id"),
        "type": node.get("type"),
        "ns": node.get("ns"),
        "author": node.get("author"),
        "grade": node.get("grade"),
        "ts": node.get("ts"),
        "reached_by": why,
    }
    if edges:
        card["edges"] = list(edges)
    return card


def route_inbound(subject: Mapping[str, Any], hop1: Sequence[Mapping[str, Any]]) -> RouteReport:
    """Route 1 — what points AT this envelope."""
    found: list[dict[str, Any]] = []
    for node in hop1:
        inbound = _edges_toward_subject(node.get("edges") or ())
        if not inbound:
            continue
        card = _card(node, why="edge-to-subject", edges=sorted(set(inbound)))
        # #2205's split, carried as a LABEL rather than a refusal: which of
        # these edges assert that the subject's basis moved, and which are
        # the board being busy. A caller scanning for "did something happen
        # to this" should not have to re-derive the vocabulary.
        card["asserting_edges"] = sorted(set(inbound) & STATE_CHANGING)
        card["conversational_edges"] = sorted(set(inbound) & CONVERSATIONAL)
        found.append(card)
    return RouteReport(
        route="inbound-edges",
        question="what carries an edge TO this envelope?",
        status="searched",
        found=tuple(sorted(found, key=lambda c: c.get("id") or 0)),
        basis=(
            f"/neighbourhood/{subject.get('id')} depth 1, entries whose edge runs "
            "toward the subject"
        ),
    )


def route_closes_on_target(
    subject: Mapping[str, Any],
    targets: Sequence[int],
    target_hops: Mapping[int, Sequence[Mapping[str, Any]]],
) -> RouteReport:
    """Route 2 — THE ONE THE FIXTURE EXISTS FOR.

    A gate names a delivery without pointing at it: #828 closes JOB #713
    and says '#800' only in prose. So the route does not look at the
    subject's inbound edges at all. It takes what the SUBJECT closes,
    and asks what ELSE closed the same thing — a second closer of one
    JOB is either the gate for this delivery or a competing delivery,
    and both are answers to 'what happened to this'.
    """
    if not targets:
        return RouteReport(
            route="closes-on-target",
            question="did anything else dispose of what this envelope closes?",
            status="not-applicable",
            found=(),
            basis=(
                "the subject carries no `closes` edge, so it has no target to "
                "share — this is a property of the subject, not an empty board"
            ),
        )

    subject_id = subject.get("id")
    found: list[dict[str, Any]] = []
    for target in targets:
        for node in target_hops.get(target, ()):
            if node.get("id") == subject_id:
                continue  # the subject reaches its own target; not news
            inbound = _edges_toward_subject(node.get("edges") or ())
            if "closes" not in inbound:
                continue
            grade = node.get("grade")
            why = (
                f"also closes #{target}"
                if grade not in ATTESTING_GRADES
                else f"closes #{target} and is graded {grade}"
            )
            found.append(_card(node, why=why, edges=sorted(set(inbound))))
    return RouteReport(
        route="closes-on-target",
        question="did anything else dispose of what this envelope closes?",
        status="searched",
        found=tuple(sorted(found, key=lambda c: c.get("id") or 0)),
        basis=(
            "targets "
            + ", ".join(f"#{t}" for t in targets)
            + " walked at depth 1; entries that also close them"
        ),
    )


def route_attested_on_target(
    subject: Mapping[str, Any],
    targets: Sequence[int],
    target_hops: Mapping[int, Sequence[Mapping[str, Any]]],
) -> RouteReport:
    """Route 3 — a graded FINDING on the subject's target.

    Separate from route 2 on purpose. A gate that closes the JOB is
    caught there; a gate that only *derives from* or *replies to* the
    JOB while carrying `verified` is caught here, and collapsing the two
    would make the second invisible whenever the first fires.
    """
    if not targets:
        return RouteReport(
            route="attested-on-target",
            question="is anything on this envelope's targets carrying a grade?",
            status="not-applicable",
            found=(),
            basis="the subject carries no outbound edges, so it shares no target",
        )

    subject_id = subject.get("id")
    found: list[dict[str, Any]] = []
    seen: set[int] = set()
    for target in targets:
        for node in target_hops.get(target, ()):
            nid = node.get("id")
            if not isinstance(nid, int):
                # No id means nothing to dedup on: adding None here would
                # make the NEXT id-less node match it and be dropped.
                continue
            if nid == subject_id or nid in seen:
                continue
            if node.get("grade") not in ATTESTING_GRADES:
                continue
            seen.add(nid)
            found.append(
                _card(
                    node,
                    why=f"graded {node.get('grade')} and edged to #{target}",
                    edges=sorted(set(node.get("edges") or ())),
                )
            )
    return RouteReport(
        route="attested-on-target",
        question="is anything on this envelope's targets carrying a grade?",
        status="searched",
        found=tuple(sorted(found, key=lambda c: c.get("id") or 0)),
        basis=(
            "targets "
            + ", ".join(f"#{t}" for t in targets)
            + " walked at depth 1; entries graded "
            + "/".join(sorted(ATTESTING_GRADES))
        ),
    )


def route_sha_in_prose(
    subject: Mapping[str, Any], search_body: Mapping[str, Any] | None, sha: str | None
) -> RouteReport:
    """Route 4 — the subject pins a sha; who else says that sha out loud.

    A branch sha travels in prose far more than it travels in edges: a
    gate quotes the sha it merged, a WARN quotes the sha it is warning
    about. None of that is an edge and none of it is reachable by any
    walk.
    """
    if not sha:
        return RouteReport(
            route="sha-in-prose",
            question="does anything quote this envelope's pinned sha?",
            status="not-applicable",
            found=(),
            basis=(
                "the subject carries no pointer sha256, so there is no string to "
                "search for — not a claim that nothing quotes it"
            ),
        )
    if search_body is None:
        return RouteReport(
            route="sha-in-prose",
            question="does anything quote this envelope's pinned sha?",
            status="bounded",
            found=(),
            basis=f"search for {sha[:12]} did not complete; absence here proves nothing",
        )

    subject_id = subject.get("id")
    found = [
        _card(r, why=f"quotes {sha[:12]} in prose")
        for r in (search_body.get("results") or ())
        if isinstance(r, Mapping) and r.get("id") != subject_id
    ]
    truncated = bool(search_body.get("truncated_at_limit"))
    return RouteReport(
        route="sha-in-prose",
        question="does anything quote this envelope's pinned sha?",
        status="bounded" if truncated else "searched",
        found=tuple(sorted(found, key=lambda c: c.get("id") or 0)),
        basis=(
            f"/search q={sha[:12]}…"
            + (" — truncated at limit, so absence beyond it proves nothing" if truncated else "")
        ),
    )


# The declared route table. `korax why` runs every entry here on every
# call and emits every entry's report. Adding a route means adding a row;
# a row that stops being emitted reddens `test_every_route_is_reported`,
# which asserts against THIS tuple rather than against a hand-written
# list of names — so the canary cannot drift away from the code it
# guards (#2141: the control is by construction, not by discipline).
ROUTE_NAMES: tuple[str, ...] = (
    "inbound-edges",
    "closes-on-target",
    "attested-on-target",
    "sha-in-prose",
)


def outbound_targets(hop1: Sequence[Mapping[str, Any]], *, edge: str | None = None) -> list[int]:
    """Ids the subject points at, optionally by one edge kind."""
    out: list[int] = []
    for node in hop1:
        edges = _edges_from_subject(node.get("edges") or ())
        if not edges:
            continue
        if edge is not None and edge not in edges:
            continue
        nid = node.get("id")
        if isinstance(nid, int):
            out.append(nid)
    return sorted(set(out))


def summarise(subject: Mapping[str, Any], reports: Sequence[RouteReport]) -> dict[str, Any]:
    """The four plain-language answers, each naming the route it came from.

    An answer that cannot name its basis is the thing this verb exists to
    replace, so `basis` is not decoration — it is how a reader tells
    "nothing superseded this" from "I did not look".
    """
    by_route = {r.route: r for r in reports}

    def inbound_with(edge: str) -> list[int]:
        rep = by_route.get("inbound-edges")
        if rep is None:
            return []
        return [
            c["id"] for c in rep.found if edge in (c.get("edges") or []) and c.get("id") is not None
        ]

    superseded_by = inbound_with("supersedes")
    closed_by = inbound_with("closes")

    gates: list[int] = []
    for route in ("closes-on-target", "attested-on-target"):
        rep = by_route.get(route)
        if rep is None:
            continue
        gates.extend(
            c["id"]
            for c in rep.found
            if c.get("grade") in ATTESTING_GRADES and c.get("id") is not None
        )
    # An inbound `verified` FINDING gates it too, by the most direct road.
    # So does an inbound STAMP — and the stamp is caught HERE, on the edge,
    # because `stamped` is an effective grade that never appears in the
    # `grade` field (see ATTESTING_GRADES). Testing the grade alone would
    # answer "nothing gated this" about a stamped envelope.
    rep_in = by_route.get("inbound-edges")
    if rep_in is not None:
        gates.extend(
            c["id"]
            for c in rep_in.found
            if c.get("id") is not None
            and (
                c.get("grade") in ATTESTING_GRADES
                or set(c.get("edges") or ()) & STAMPING_EDGES
            )
        )
    stamped_by = []
    if rep_in is not None:
        stamped_by = [
            c["id"]
            for c in rep_in.found
            if c.get("id") is not None and set(c.get("edges") or ()) & STAMPING_EDGES
        ]

    cited: list[int] = []
    for rep in reports:
        for c in rep.found:
            cid = c.get("id")
            if cid is not None and cid not in cited:
                cited.append(cid)

    def answer(ids: Sequence[int], routes: str) -> dict[str, Any]:
        return {
            "answer": bool(ids),
            "ids": sorted(set(ids)),
            "from_routes": routes,
        }

    return {
        "gated": answer(
            gates,
            "closes-on-target + attested-on-target + inbound-edges "
            "(`verified` FINDINGs, and inbound `stamps`)",
        ),
        "disposed": answer(closed_by, "inbound-edges (`closes` toward the subject)"),
        "superseded": answer(superseded_by, "inbound-edges (`supersedes` toward the subject)"),
        "stamped": answer(stamped_by, "inbound-edges (`stamps` toward the subject)"),
        "cited": answer(cited, "every route"),
    }


def merge_counters(bodies: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Carry the underlying reads' exclusion counters up into the answer.

    THE POINT: `why` answers in the negative constantly — "nothing
    superseded this" — and a negative computed over a slice that withheld
    envelopes is not entitled to be stated flatly. Each composed read
    already says what it withheld; dropping those on the way up would
    rebuild family A one layer higher, in the verb written to cure it.

    Counters are reported per source and never summed: `/neighbourhood`
    and `/search` scope their counts differently (`withheld_scope` says
    which), so an addition would produce a number naming no scope at all.
    """
    sources: list[dict[str, Any]] = []
    blind = False
    for body in bodies:
        entry = {
            "source": body.get("_why_source", "unknown"),
            "withheld_scope": body.get("withheld_scope"),
            "sealed_excluded": body.get("sealed_excluded"),
            "participation_excluded": body.get("participation_excluded"),
        }
        if body.get("truncated"):
            entry["truncated"] = True
            blind = True
        if _nonzero(body.get("sealed_excluded")) or _nonzero(body.get("participation_excluded")):
            blind = True
        sources.append(entry)
    return {"sources": sources, "any_withheld_or_bounded": blind}


def _nonzero(count: Any) -> bool:
    """An exclusion counter is a number, or a presence-only dict (§9.3).
    A dict means "some, and you are not told how many" — which is not
    zero, and reading it as falsey is #2060's shape exactly: a refusal
    that measured as content."""
    if isinstance(count, Mapping):
        return True
    if isinstance(count, bool):
        return count
    if isinstance(count, (int, float)):
        return count != 0
    return False


def build(
    subject: Mapping[str, Any],
    hop1: Sequence[Mapping[str, Any]],
    target_hops: Mapping[int, Sequence[Mapping[str, Any]]],
    search_body: Mapping[str, Any] | None,
    sha: str | None,
    counter_bodies: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Compose the whole answer from already-fetched material.

    Kept free of I/O so the route logic is testable against fixtures
    without a board — the routes are the part with the reasoning in them,
    and a test that has to stand up a server to check a label ends up not
    checking the label.
    """
    targets = outbound_targets(hop1)
    closes_targets = outbound_targets(hop1, edge="closes")

    reports = [
        route_inbound(subject, hop1),
        route_closes_on_target(subject, closes_targets, target_hops),
        route_attested_on_target(subject, targets, target_hops),
        route_sha_in_prose(subject, search_body, sha),
    ]

    emitted = tuple(r.route for r in reports)
    if emitted != ROUTE_NAMES:
        # Control by construction: the table and the emission cannot drift
        # apart silently, because the drift raises here rather than
        # printing a short answer that looks complete.
        raise AssertionError(
            f"route table drift: declared {ROUTE_NAMES}, emitted {emitted}. "
            "Every declared route must report, including the empty ones — that "
            "is the whole contract of this verb (#2183 family A)."
        )

    return {
        "why": subject.get("id"),
        "subject": {
            "id": subject.get("id"),
            "type": subject.get("type"),
            "ns": subject.get("ns"),
            "author": subject.get("author"),
            "grade": subject.get("grade"),
            "ts": subject.get("ts"),
            "pointer_sha256": sha,
        },
        "answers": summarise(subject, reports),
        "routes": [r.as_json() for r in reports],
        "routes_declared": list(ROUTE_NAMES),
        "bounds": merge_counters(counter_bodies),
    }
