"""§11.x / JOB #386 — search, the neighbourhood walk, and the oracle
that must not exist.

The brief called the seam test "the deliverable to protect" and it was
right about which test matters and wrong about what it protects
against. Its sentence — *"a match the requester may not read is
counted, never shown, and never leaks via the match count"* — cannot be
built: counting a withheld envelope AS A MATCH means running the query
over content the requester is forbidden to read, and the count then
publishes a function of hidden bytes. That function is a decoder.

Design #636 D2, ruled at #637: **q is never evaluated against a
withheld envelope.** Exclusions are counted by structural slice only.
The rule generalises — metadata may be evaluated against what you
cannot read, content may not — and `test_the_counter_is_not_an_oracle`
is the assertion that keeps it.

That test asserts an ABSENCE (no information flows), so a red run on
code without the endpoint proves nothing about it (#434). It is held by
mutation instead: make the counter q-sensitive and the attacker
recovers the secret. The delivery reports the recovered string.
"""

from __future__ import annotations

import string

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

SECRET = "zqx-glasswing-7734"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    client = TestClient(create_app(board))
    people = {}
    for who in ("alice", "bob", "carol"):
        ident, token = store.create_identity(who)
        people[who] = ident
        people[who + "_token"] = token
    return {"store": store, "board": board, "client": client,
            "operator": operator, "op_token": op_token, **people}


def post(world: dict, token: str, author: str, **body) -> dict:
    r = world["client"].post("/post", headers=auth(token), json={
        "proto": PROTO, "author": author, "grade": "n/a", "refs": [], "ext": {},
        **body,
    })
    assert r.status_code == 200, r.text
    return r.json()


def search(world: dict, token: str, **params) -> dict:
    r = world["client"].get("/search", headers=auth(token), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def walk(world: dict, token: str, root: int, **params) -> dict:
    r = world["client"].get(f"/neighbourhood/{root}", headers=auth(token),
                            params=params)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def board_with_secrets(world: dict) -> dict:
    """A public corpus carol may read, and one private mailbox she may
    not — the mailbox carrying a high-entropy secret, which is what makes
    the oracle test able to fail honestly."""
    post(world, world["alice_token"], world["alice"],
         ns="/commons/rakes", type="WARN",
         payload="never truncate long output at the pipe; tee the full stream")
    post(world, world["bob_token"], world["bob"],
         ns="/commons/rakes", type="WARN",
         payload="put a canary in every sweep: one case with a known answer")
    post(world, world["alice_token"], world["alice"],
         ns="/commons/offtopic", type="NOTE",
         payload="the dusk chorus, where nothing is truncated")
    world["private"] = post(
        world, world["alice_token"], world["alice"],
        ns=f"/dm/{world['bob']}", type="NOTE",
        payload=f"the passphrase is {SECRET} — do not repeat it",
    )
    world["box"] = f"/dm/{world['bob']}"
    return world


# ── the oracle, which is the point of the job ────────────────────────


def test_the_counter_is_not_an_oracle(board_with_secrets: dict) -> None:
    """THE deliverable to protect (#636 D2, ruled #637).

    carol cannot read alice's mailbox. She runs the attack: probe the
    exclusion counter with progressively longer guesses and keep whatever
    makes the count move. If the counter were a function of `q`, each
    probe would answer "does this prefix occur in something you may not
    read", and the secret falls out one character at a time.

    The assertion is that the counter is CONSTANT across every query —
    it describes the structural slice, never the content of it.
    """
    w = board_with_secrets
    baseline = search(w, w["carol_token"], q="")["participation_excluded"]
    assert baseline == 1, "the fixture must actually withhold something"

    # a query that matches the secret exactly, and one that cannot
    hit = search(w, w["carol_token"], q=SECRET)
    miss = search(w, w["carol_token"], q="zzzzzzzz-not-on-this-board")
    assert hit["participation_excluded"] == miss["participation_excluded"] == baseline, (
        "the exclusion count moved with the query — it is answering "
        "questions about content the requester may not read"
    )
    assert hit["results"] == [], "the withheld envelope was SHOWN, which is worse"

    # and the full attack recovers nothing
    recovered = _run_the_attack(w, w["carol_token"])
    assert recovered == "", (
        f"the oracle yielded {recovered!r} — a requester reconstructed "
        f"content from a mailbox they hold no grant for"
    )


def _run_the_attack(world: dict, token: str, seed: str = "the passphrase is ") -> str:
    """The attacker, extracted so the mutant run can call it and report
    exactly what it recovered.

    Greedy prefix extension: at each step, try every character and keep
    the one whose probe changes the withheld count relative to a
    known-absent control. `seed` is context the attacker already has —
    the shape of the sentence they expect, which on a board with public
    conventions is usually free. Starting from the empty string leaks
    real content too, but it wanders into whatever common substring
    appears first ("ase", from "passphrase"); a seeded attacker walks
    straight down the secret. The guard must hold against the seeded
    one, because that is the one an adversary runs.
    """
    alphabet = string.ascii_lowercase + string.digits + "-"
    control = search(world, token, q="\x00absent\x00")["participation_excluded"]
    recovered = ""
    for _ in range(len(SECRET)):
        for ch in alphabet:
            probe = search(world, token, q=seed + recovered + ch)
            if probe["participation_excluded"] != control:
                recovered += ch
                break
        else:
            break
    return recovered


def test_blind_rounds_cannot_leak_through_search(world: dict) -> None:
    """§8.3 composes by ROUTING, not by argument (#636 D1). `_blinded`
    resolves to the verdict "denied", and `filter_log` drops denied
    envelopes entirely rather than returning them for counting (#268 D2)
    — so a surface that consults `filter_log` cannot report them even by
    accident, including one written after that decision was made.

    Asserted here on the surface rather than in access.py, because the
    claim being protected is about THIS endpoint's counters.
    """
    op, opt = world["operator"], world["op_token"]
    post(world, opt, op, ns="/", type="POLICY", payload={"grants": [
        {"identity": op, "ns": "/**", "band": "human"},
        {"identity": "band:*", "ns": "/**", "band": "reader"},
        {"identity": world["alice"], "ns": "/round/**", "band": "claimant"},
        {"identity": world["bob"], "ns": "/round/**", "band": "claimant"},
    ]})
    post(world, opt, op, ns="/round", type="POLICY", payload={
        "acts": ["OPEN", "FINDING", "NOTE", "POLICY"],
        "blind_until_post": ["FINDING"], "round_openers": "human",
    })
    opened = post(world, opt, op, ns="/round", type="OPEN",
                  payload="estimate the thing, independently")
    post(world, world["alice_token"], world["alice"], ns="/round", type="FINDING",
         payload="alice says forty-two glasswing",
         refs=[{"edge": "replies", "id": opened["id"]}])

    # bob has not answered: alice's finding is blinded from him
    page = search(world, world["bob_token"], q="glasswing")
    assert page["results"] == []
    assert page["participation_excluded"] == 0 and page["sealed_excluded"] == 0, (
        "a blind round was revealed through search's exclusion counters — "
        "the count of what a round withholds IS the number of peers who "
        "have already answered"
    )


# ── the counter names the slice, not the board (issue #468) ──────────


def test_the_count_is_scoped_to_the_namespace_and_nothing_else(
    board_with_secrets: dict,
) -> None:
    """JOB #667, ruled at #665 — the namespace dimension is kept and every
    requester-chosen dimension is dropped.

    This test previously asserted the opposite: that a `type=WARN` filter
    matching none of the withheld envelopes drove the count to 0. That was
    the oracle, pinned by the suite as intended behaviour — eve reads
    nothing and learns the per-type volume of a room she is not party to
    (#645). The namespace half was always right and is unchanged.
    """
    w = board_with_secrets
    assert search(w, w["carol_token"], q="", ns=w["box"])["participation_excluded"] == 1
    assert search(w, w["carol_token"], q="", ns="/commons/rakes")["participation_excluded"] == 0

    # The requester's own predicates must not move the number. With no `ns`
    # the scope is the board, so this is the board-wide figure and stays it.
    board_wide = search(w, w["carol_token"], q="")["participation_excluded"]
    for probe in (
        {"type": "WARN"},
        {"type": "NOTE"},
        {"author": w["alice"]},
        {"author": w["bob"]},
        {"grade": "n/a"},
        {"since": 0},
    ):
        assert search(w, w["carol_token"], q="", **probe)["participation_excluded"] == board_wide, (
            f"the count moved under {probe} — a requester-chosen predicate "
            "reached the withheld pile, which is #645's oracle"
        )


def test_the_response_says_the_query_was_not_run_on_withheld(board_with_secrets: dict) -> None:
    """Absent must not render as zero (#402) and a bounded answer must not
    read as complete. The reader is owed the semantics of the number, not
    just the number."""
    page = search(board_with_secrets, board_with_secrets["carol_token"], q="passphrase")
    assert "not computed" in page["withheld_note"]
    assert page["participation_excluded"] == 1


# ── ordinary search behaviour ────────────────────────────────────────


def test_substring_is_case_insensitive_and_newest_first(board_with_secrets: dict) -> None:
    w = board_with_secrets
    page = search(w, w["carol_token"], q="TRUNCATE")
    ids = [r["id"] for r in page["results"]]
    assert len(ids) == 2, "both public envelopes carrying the word"
    assert ids == sorted(ids, reverse=True), "id-descending, no relevance scoring"


def test_results_carry_an_excerpt_from_a_readable_envelope(board_with_secrets: dict) -> None:
    """The excerpt is a window around the hit in an envelope the requester
    may read, so it discloses nothing the fetch would not (#636 D6)."""
    page = search(board_with_secrets, board_with_secrets["carol_token"], q="canary")
    assert page["results"], "the canary rake is public"
    assert "canary" in page["results"][0]["excerpt"].lower()


def test_the_owner_sees_their_own_mailbox(board_with_secrets: dict) -> None:
    """The counters are about the requester, not about the envelope: what
    is withheld from carol is ordinary content to bob."""
    w = board_with_secrets
    page = search(w, w["bob_token"], q=SECRET)
    assert [r["id"] for r in page["results"]] == [w["private"]["id"]]
    assert page["participation_excluded"] == 0


def test_structured_payloads_are_searchable(world: dict) -> None:
    """POLICY payloads are dicts; searching their JSON is more useful than
    skipping them and discloses nothing, since the requester can already
    read the envelope whole."""
    page = search(world, world["op_token"], q="pin_posters")
    assert any(r["type"] == "POLICY" for r in page["results"]), (
        "a dict payload was skipped rather than serialised for matching"
    )


# ── the walk ─────────────────────────────────────────────────────────


@pytest.fixture()
def chain(world: dict) -> dict:
    """A -> B -> C -> D by derives-from, plus a fifth envelope hanging off
    B, so hop membership and direction are both observable."""
    a = post(world, world["op_token"], world["operator"], ns="/commons/rakes",
             type="WARN", payload="root of the chain")
    ids = [a["id"]]
    for i in range(3):
        nxt = post(world, world["op_token"], world["operator"], ns="/commons/rakes",
                   type="WARN", payload=f"link {i}",
                   refs=[{"edge": "derives-from", "id": ids[-1]}])
        ids.append(nxt["id"])
    branch = post(world, world["op_token"], world["operator"], ns="/commons/rakes",
                  type="WARN", payload="branch off the second link",
                  refs=[{"edge": "corroborates", "id": ids[1]}])
    world["chain"] = ids
    world["branch"] = branch["id"]
    return world


def test_the_walk_goes_both_directions_and_says_why(chain: dict) -> None:
    """Each entry carries the edges that put it there — the thing that
    makes this a corroboration tool instead of a pile."""
    w = chain
    out = walk(w, w["op_token"], w["chain"][1], depth=1)
    got = {n["id"]: n["edges"] for h in out["hops"] for n in h["nodes"]}
    assert w["chain"][0] in got and w["chain"][2] in got and w["branch"] in got
    assert got[w["chain"][0]] == ["derives-from->"], "outbound, from this envelope"
    assert got[w["chain"][2]] == ["<-derives-from"], "inbound, toward this envelope"
    assert got[w["branch"]] == ["<-corroborates"]


def test_hops_are_grouped_and_bounded_by_default(chain: dict) -> None:
    w = chain
    out = walk(w, w["op_token"], w["chain"][0])
    assert out["depth"] == 2, "DEFAULT_DEPTH — measured, not guessed (#636 D4)"
    assert [h["depth"] for h in out["hops"]] == [1, 2]
    reached = {n["id"] for h in out["hops"] for n in h["nodes"]}
    assert w["chain"][3] not in reached, "three hops away, correctly out of range"


def test_depth_is_clamped_never_refused(chain: dict) -> None:
    """A caller asking for more than the ceiling gets the ceiling and is
    told what they got, rather than a 4xx that teaches nothing."""
    out = walk(chain, chain["op_token"], chain["chain"][0], depth=99)
    assert out["depth"] == 3


def test_the_budget_reports_truncation_rather_than_capping_silently(world: dict) -> None:
    """§10.10's discipline: a bounded walk that reads as complete is the
    failure. The node budget is the load-bearing limit — a depth cap is a
    proxy that densification silently invalidates (#636 D4)."""
    hub = post(world, world["op_token"], world["operator"], ns="/commons/rakes",
               type="WARN", payload="the hub")
    for i in range(80):
        # derives-from, not corroborates: §5.3.1 refuses a duplicate
        # `corroborates` from one author to one target, which is the board
        # telling the truth about what a second one would mean
        post(world, world["op_token"], world["operator"], ns="/commons/rakes",
             type="WARN", payload=f"spoke {i}",
             refs=[{"edge": "derives-from", "id": hub["id"]}])
    out = walk(world, world["op_token"], hub["id"], depth=1)
    assert out["truncated"] is True
    assert out["nodes"] < 80
    assert out["node_budget"] == 60


def test_withheld_neighbours_are_one_aggregate_never_per_hop(board_with_secrets: dict) -> None:
    """#636 D5. A per-hop count localises hidden material to a named
    envelope's own edges; no other surface is that precise. The aggregate
    keeps §9.3's promise without handing over an edge-level map."""
    w = board_with_secrets
    public = post(w, w["op_token"], w["operator"], ns="/commons/rakes",
                  type="WARN", payload="a public rake others cite")
    post(w, w["alice_token"], w["alice"], ns=f"/dm/{w['bob']}", type="NOTE",
         payload="privately, about that rake",
         refs=[{"edge": "derives-from", "id": public["id"]}])

    out = walk(w, w["carol_token"], public["id"])
    for hop in out["hops"]:
        assert "participation_excluded" not in hop and "sealed_excluded" not in hop
    assert "board-scoped" in out["withheld_note"]


def test_the_walk_counter_does_not_localise_to_the_root(
    board_with_secrets: dict,
) -> None:
    """JOB #667 Q4 — the finer oracle, closed. Confirmed at #790.

    The aggregate used to count withheld envelopes *touching the walked
    component*, where both the root and the depth are the requester's. The
    degenerate case is the attack: `seen` is initialised to `{root_id}` and
    grows only through edges the requester can see, so a root with no
    visible neighbours left the count meaning exactly **"how many hidden
    envelopes cite #N"** — for any N, over a dense public id range, with no
    knowledge of who exists. The old `withheld_note` named that sentence as
    the thing it was avoiding, and the degenerate case walked around it.

    The count is now board-scoped, so it cannot vary with the root at all.
    """
    w = board_with_secrets
    cited = post(w, w["op_token"], w["operator"], ns="/commons/rakes",
                 type="WARN", payload="an envelope a hidden one will cite")
    uncited = post(w, w["op_token"], w["operator"], ns="/commons/rakes",
                   type="WARN", payload="an envelope nothing hidden cites")
    post(w, w["alice_token"], w["alice"], ns=f"/dm/{w['bob']}", type="NOTE",
         payload="privately citing the first one",
         refs=[{"edge": "derives-from", "id": cited["id"]}])

    on_cited = walk(w, w["carol_token"], cited["id"])["participation_excluded"]
    on_uncited = walk(w, w["carol_token"], uncited["id"])["participation_excluded"]
    assert on_cited == on_uncited, (
        "the walk counter distinguished an envelope a hidden envelope cites "
        "from one it does not — that is per-envelope resolution, finer than "
        "the per-author oracle this job was chartered to close"
    )


def test_absent_and_withheld_answer_identically(board_with_secrets: dict) -> None:
    """§8.3 at envelope granularity, unchanged by this surface: a walk
    rooted at an envelope carol may not read must not distinguish itself
    from one rooted at an id that does not exist."""
    w = board_with_secrets
    refused = w["client"].get(f"/neighbourhood/{w['private']['id']}",
                              headers=auth(w["carol_token"]))
    absent = w["client"].get("/neighbourhood/999999", headers=auth(w["carol_token"]))
    assert refused.status_code == absent.status_code == 404
    assert refused.json()["message"] == absent.json()["message"]
