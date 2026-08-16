"""JOB #2199 (S2) — the thread page, guarded where a browser is not needed.

The #962/#841 split, as every perch suite here uses it: EXECUTED where
the logic is extractable, CONTRACT against a real board where the
question is "does the server still send what this reads", STRUCTURAL
over the served source where neither applies. The browser leg lives in
test_perch_thread_browser.py and is the acceptance; this is the half
that still runs when Chrome is absent.

The executed tests matter most here. `thBacklinks` is the function that
makes S2 possible without a server change — the walk sends each node's
own `refs` but no inbound edges, so backlinks are those refs INVERTED
across the component, computed in the client. That inversion is pure,
so it is run rather than described.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.search import MAX_NODES
from korax.seed import seed_board
from korax.store import Store

from perch_source import PERCH_DIR, markup as _markup, script as _script

NODE = shutil.which("node")
THREAD_JS = PERCH_DIR / "js" / "tabs" / "thread.js"


def thread_source() -> str:
    return THREAD_JS.read_text(encoding="utf-8")


def _run(prog: str):
    """Execute a fragment of thread.js in node and return its JSON."""
    r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _extract(name: str) -> str:
    """One function's source, by name, from thread.js."""
    src = thread_source()
    m = re.search(rf"(function {name}\(.*?\n\}})", src, re.S)
    assert m, f"{name} is gone from thread.js — re-point this test, do not delete it"
    return m.group(1)


# ── executed: the inversion that replaces a server change ─────────────

@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_backlinks_are_refs_inverted_across_the_component() -> None:
    """Three envelopes cite #1; #1's backlinks are those three, and each
    names the edge that made it. This is the whole mechanism S2 rests on."""
    prog = _extract("thBacklinks") + """
      const nodes = [
        { id: 1, refs: [] },
        { id: 2, refs: [{ edge: "replies", id: 1 }] },
        { id: 3, refs: [{ edge: "replies", id: 2 }, { edge: "derives-from", id: 1 }] },
        { id: 5, refs: [{ edge: "derives-from", id: 1 }] },
      ];
      const back = thBacklinks(nodes);
      process.stdout.write(JSON.stringify({
        one: back.get(1), two: back.get(2), three: back.get(3) || null }));
    """
    out = _run(prog)
    assert out["one"] == [
        {"from": 2, "edge": "replies"},
        {"from": 3, "edge": "derives-from"},
        {"from": 5, "edge": "derives-from"},
    ], "every citation of #1 must appear, in citing-id order, with its edge"
    assert out["two"] == [{"from": 3, "edge": "replies"}]
    assert out["three"] is None, "an envelope nobody cites has no backlinks"


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_ref_outside_the_component_makes_no_backlink() -> None:
    """The inversion can only see what the walk returned. A ref to an id
    that is not on the page must NOT invent a backlink there — the page
    would be asserting an edge it cannot show, and the bound notice is
    what covers this case instead."""
    prog = _extract("thBacklinks") + """
      const back = thBacklinks([
        { id: 1, refs: [] },
        { id: 2, refs: [{ edge: "replies", id: 999 }] },
      ]);
      process.stdout.write(JSON.stringify({
        nine: back.get(999) || null, size: back.size }));
    """
    out = _run(prog)
    assert out["nine"] is None
    assert out["size"] == 0, "a citation leaving the component adds nothing"


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_the_focus_is_in_the_order_even_though_the_walk_omits_it() -> None:
    """`neighbourhood` seeds `seen` with the root and emits from hop 1, so
    the root is NOT in `hops`. A flat page trusting `hops` alone would
    silently omit the very envelope the URL named — and it would look
    fine, because the other four cards would render."""
    prog = _extract("thOrder") + """
      const walk = { root: 3, hops: [
        { depth: 1, nodes: [{ id: 4, refs: [] }, { id: 2, refs: [] }] },
        { depth: 2, nodes: [{ id: 1, refs: [] }, { id: 5, refs: [] }] },
      ]};
      const order = thOrder(walk, { id: 3, payload: "the focus", refs: [] });
      process.stdout.write(JSON.stringify({
        ids: order.map(n => n.id),
        focusFlag: order.find(n => n.id === 3).focus === true,
        focusPayload: order.find(n => n.id === 3).payload }));
    """
    out = _run(prog)
    assert out["ids"] == [1, 2, 3, 4, 5], (
        "id-ascending, and the walk's root among them — flat means the "
        "oldest leads, not the one you asked for")
    assert out["focusFlag"] is True
    assert out["focusPayload"] == "the focus", (
        "the focus rides its full envelope: it is the one payload always "
        "wanted, and the only node whose refs the walk never sends")


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_the_order_is_ids_and_not_hop_distance() -> None:
    """A node two hops out can be OLDER than one at a single hop. Ordering
    by hop would put a later envelope above an earlier one and read as a
    conversation that ran backwards."""
    prog = _extract("thOrder") + """
      const walk = { root: 50, hops: [
        { depth: 1, nodes: [{ id: 90, refs: [] }] },
        { depth: 2, nodes: [{ id: 10, refs: [] }] },
      ]};
      process.stdout.write(JSON.stringify(thOrder(walk, null).map(n => n.id)));
    """
    assert _run(prog) == [10, 50, 90]


# ── contract: what the walk must keep sending ─────────────────────────

@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    op, tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    return {"client": TestClient(create_app(board)), "op": op, "tok": tok}


def test_the_walk_still_carries_per_node_refs(world: dict) -> None:
    """**The contract S2 is built on.** `_summary` sends each node's own
    `refs` with ids. The node's `edges` field carries direction+type
    labels (`replies->`, `<-derives-from`) and NO endpoint — you cannot
    draw a quotelink with it, which is what #1847 recorded. If `refs`
    ever stops riding the walk, the thread page loses both its
    quotelinks and every backlink, and it loses them SILENTLY: the cards
    still render. That is why this is asserted here and not in a
    browser."""
    hdr = {"Authorization": f"Bearer {world['tok']}"}
    post = lambda refs, text: world["client"].post("/post", headers=hdr, json={
        "proto": PROTO, "author": world["op"], "ns": "/commons/rakes",
        "type": "WARN", "grade": "unverified", "refs": refs,
        "payload": text, "ext": {}}).json()

    root = post([], "the root of a small conversation")
    child = post([{"edge": "replies", "id": root["id"]}], "an answer")

    o = world["client"].get(f"/neighbourhood/{root['id']}", headers=hdr).json()
    assert "code" not in o, f"the walk refused: {o}"
    nodes = [n for hop in o["hops"] for n in hop["nodes"]]
    found = next((n for n in nodes if n["id"] == child["id"]), None)
    assert found is not None, "the child must be in the component"
    assert "refs" in found, (
        "the walk stopped sending per-node `refs` — the thread page's "
        "quotelinks and ALL of its backlinks are computed from these, and "
        "their absence renders as a conversation with no citations rather "
        "than as an error")
    assert {(r["edge"], r["id"]) for r in found["refs"]} == {("replies", root["id"])}
    # and the field that is NOT sufficient, so the distinction is pinned
    assert "edges" in found
    assert all(not any(ch.isdigit() for ch in e) for e in found["edges"]), (
        "`edges` carries direction+type only; if it ever grew endpoints "
        "this test should be revisited, not silently relied upon")


def test_the_page_reads_the_walk_and_not_the_thread_reduction() -> None:
    """#881's ruling, inherited: `thread` follows `replies`, under a tenth
    of this board's structure. S2 renders the component or it renders a
    busy board as a quiet one."""
    src = thread_source()
    assert "/neighbourhood/${encodeURIComponent(id)}" in src
    calls = re.findall(r"api\(`([^`]+)`", src)
    assert not [c for c in calls if "view/thread" in c or "view/neighbourhood" in c], (
        "the thread page fell back to `thread` or to a /view/ wrapper")


def test_no_server_change_shipped_with_this_stage() -> None:
    """The brief's scope, asserted against the tree: S2 is perch-and-tests.
    A scope exception was to arrive on the board BEFORE any server edit,
    so a server diff appearing here silently is the thing to catch."""
    src = thread_source()
    assert "/post" in src, "the reply box posts through the existing endpoint"
    # the page invents no endpoint of its own
    for path in re.findall(r"api\(`?[\"']?(/[a-z/]+)", src):
        assert path.split("/")[1] in {"neighbourhood", "post", "envelope", "read"}, (
            f"the thread page called {path} — S2 adds no server surface")


# ── structural: the honesty rules, over the served source ─────────────

def test_a_truncated_walk_renders_as_a_bound_and_says_backlinks_are_partial() -> None:
    """Two claims, and the second is the one only S2 has to make: when the
    walk truncates, the INVERSION is bounded too. Backlinks are then a
    lower bound, and a page that showed them flatly would be asserting
    completeness the walk never offered (§10.10, R67)."""
    src = thread_source()
    assert "walk.truncated" in src
    assert "node_budget" in src, "the bound must say what bounded it"
    assert "lower" in src and "bound" in src, (
        "a truncated walk must say its backlinks are a LOWER BOUND — the "
        "envelope outside the budget that cites one of these is real")


def test_the_in_budget_case_says_so_positively() -> None:
    """"No seal" must not be ambiguous between "complete" and "not
    checked". The absence of a bound is only informative if the page says
    something when the component closed."""
    assert "th-complete" in thread_source()


def test_the_id_chip_opens_the_modal_rather_than_navigating() -> None:
    """Ruled decision 3. `openEnvelope` keeps its name because eleven
    render sites bind it from inside template literals (#1941) where a
    rename is a ReferenceError no static check can see; what changed is
    what it does."""
    src = thread_source()
    assert re.search(r"async function openEnvelope\(id\)", src)
    assert "showModal()" in src
    body = re.search(r"async function openEnvelope\(id\) \{(.*?)\n\}", src, re.S)
    assert body, "openEnvelope is gone"
    assert "setHash" not in body.group(1), (
        "the #id chip must not move the URL — 'without breaking the "
        "current screen or URL' is the ruling")


def test_the_modal_offers_exactly_the_three_ruled_actions() -> None:
    html = _markup()
    for action in ("thModalGo()", "thModalReply()", "thModalPeek(this)"):
        assert action in html, f"the modal lost its {action} action"
    assert 'id="envModal"' in html


def test_the_route_lands_on_the_thread() -> None:
    """S1 shipped `#/e/<id>`; S2 changes where it arrives and NOT its
    shape, so every link ever written to it keeps working."""
    src = _script()
    m = re.search(r'if \(seg\[0\] === "e" && seg\[1\]\) return \{ tab: "(\w+)"', src)
    assert m and m.group(1) == "thread", (
        "#/e/<id> must route to the thread page")
    assert 'id="tab-thread"' in _markup()
    # the raw envelope surface survives at its own name
    assert 'seg[0] === "envelope"' in src
    assert 'id="tab-envelope"' in _markup()


def test_the_router_does_not_echo_its_own_hash() -> None:
    """S1's echo rule: route() reads the hash, so it must call loadThread
    and never openThread — the latter writes the hash it just read."""
    src = _script()
    route_body = re.search(r"function route\(\) \{(.*?)\n\}", src, re.S)
    assert route_body, "route() is gone"
    assert "loadThread(r.id)" in route_body.group(1)
    assert "openThread(" not in route_body.group(1)


def test_payloads_load_on_expand_rather_than_all_at_once() -> None:
    """MAX_NODES is 60. Rendering a component eagerly would be 60 fetches
    on one navigation — the storm the brief forbids — so the collapse
    gesture is also the loader and the cache is the existing one."""
    src = thread_source()
    assert "envelopeCached" in src, "expansion must go through the shared cache"
    assert MAX_NODES == 60, (
        "the walk's budget moved; the thread page's fetch-on-expand "
        "reasoning is written against 60 and should be re-read")
    toggle = re.search(r"async function thToggle\(.*?\n\}", src, re.S)
    assert toggle and "envelopeCached" in toggle.group(0), (
        "the payload fetch must ride the expand gesture")


def test_the_seam_vocabulary_is_the_shared_one() -> None:
    """A ref across R14's seam renders as the withheld chip, the same
    words as every other tab. A page that hand-rolled its own would be
    claiming a completeness vocabulary the board spent R28/R56/R67
    getting right."""
    src = thread_source()
    assert "withheldChip(" in src
    assert "fbWithheld(" in src
    assert "function withheldChip" not in src, "the chip is defined in render.js"
