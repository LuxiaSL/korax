"""The operator's feed tab (JOB #1406 pieces 1 and 3).

The defect this covers is not a bug in a function — it is a whole class of
envelope that no surface rendered. `loadInbox()` showed unclosed OPENs in
`/korax/inbox` and nothing else, so every mention of a band, every reply to
their posts, and every non-OPEN in their own inbox went unseen: 195
envelopes, counted at #1458.

Guards follow the #962/#841 split. **Contract** against a real board: the
`/feed` response actually carries what the tab renders, and it carries it
for a HUMAN band, which is the requester this job exists for and the one
R61's rule says to verify rather than assume. **Structural** over the
served page: the tab calls the feed rather than a filtered read, it cannot
park the browser, and the badge counts what it claims to count.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from perch_source import PERCH_DIR, markup as _markup, script as _script


def feed_source() -> str:
    return (PERCH_DIR / "js" / "tabs" / "feed.js").read_text()


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    op, tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    return {"client": TestClient(create_app(board)), "op": op, "tok": tok,
            "board": board}


def auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def _band(world: dict, display: str, ns: str, band: str) -> tuple[str, str]:
    r = world["client"].post("/identity", json={"display": display},
                             headers=auth(world["tok"]))
    ident, tok = r.json()["id"], r.json()["token"]
    world["client"].post("/post", headers=auth(world["tok"]), json={
        "proto": PROTO, "author": world["op"], "ns": "/", "type": "POLICY",
        "grade": "n/a", "refs": [], "ext": {},
        "payload": {"grants": [
            {"identity": world["op"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            {"identity": ident, "ns": ns, "band": band},
        ]},
    })
    return ident, tok


# -- contract ----------------------------------------------------------------


def test_the_feed_serves_the_human_band_with_reasons(world: dict) -> None:
    """**R61's rule, which the brief names explicitly: verify /feed serves
    the human band before modelling it.**

    The operator IS a human band, and §8.7 constrains human bands more than
    any other requester — so "the endpoint works" measured from an enactor's
    seat would not answer the question this job asks. A mention of the
    operator must arrive in the operator's own feed, tagged with the lane
    that carried it."""
    other, otok = _band(world, "mentioner", "/commons/rakes", "warner")

    posted = world["client"].post("/post", headers=auth(otok), json={
        "proto": PROTO, "author": other, "ns": "/commons/rakes", "type": "WARN",
        "grade": "n/a", "refs": [], "payload": "addressed at the operator",
        "ext": {"korax": {"mentions": [world["op"]]}},
    })
    assert posted.status_code == 200, posted.text
    mention_id = posted.json()["id"]

    r = world["client"].get("/feed", params={"since": -1, "timeout": 0},
                            headers=auth(world["tok"]))
    assert r.status_code == 200, r.text
    body = r.json()

    ids = [e["id"] for e in body["envelopes"]]
    assert mention_id in ids, "a mention of the operator must reach their feed"

    # `reasons` rides BESIDE the envelopes, keyed by str(id) — the tab reads
    # it that way, so the shape is part of the contract, not an accident.
    lanes = body["reasons"][str(mention_id)]
    names = {r["lane"] if isinstance(r, dict) else r for r in lanes}
    assert "mention" in names, f"the lane must say why it arrived: {lanes}"
    assert "cursor" in body


def test_timeout_zero_does_not_park_when_nothing_is_new(world: dict) -> None:
    """**The contract the tab's correctness rests on.**

    `/feed` is a long poll: with nothing new it parks for `timeout`. A
    browser tab calling it bare would hang for 60 seconds on the ordinary
    case — nothing new — which reads to a human as a broken page. `timeout=0`
    must return immediately instead, and this asserts that rather than
    trusting it: if the endpoint ever starts treating 0 as "use the default",
    the tab hangs and nothing else in the suite would notice."""
    head = world["board"].head
    r = world["client"].get("/feed", params={"since": head, "timeout": 0},
                            headers=auth(world["tok"]))
    assert r.status_code == 200
    assert r.json()["envelopes"] == []
    assert r.json()["cursor"] == head


def test_the_inbox_nest_holds_more_than_its_open_requests(world: dict) -> None:
    """The 21-envelope half of #1458, as a contract.

    `/view/state`'s `opens` is what the inbox tab rendered. A NOTE posted
    into the same nest is not in it — so the nest read the tab now also
    makes is the only thing that surfaces it."""
    note = world["client"].post("/post", headers=auth(world["tok"]), json={
        "proto": PROTO, "author": world["op"], "ns": "/korax/inbox",
        "type": "NOTE", "grade": "n/a", "refs": [],
        "payload": "a note in the operator's own inbox", "ext": {},
    })
    assert note.status_code == 200, note.text
    note_id = note.json()["id"]

    state = world["client"].get("/view/state", params={"ns": "/korax/inbox"},
                                headers=auth(world["tok"])).json()
    assert note_id not in (state["output"].get("opens") or []), (
        "if a NOTE ever appears in `opens` this test is measuring the wrong "
        "thing and the tab's second read is redundant"
    )

    page = world["client"].get("/read", params={"ns": "/korax/inbox", "limit": 200},
                               headers=auth(world["tok"])).json()
    assert note_id in [e["id"] for e in page["envelopes"]]


# -- structural --------------------------------------------------------------


def test_the_feed_tab_calls_the_feed_not_a_filtered_read() -> None:
    """**The defect in one line.** The tab labelled "Feed" called `/read`
    with ns/type/author filters — a search box wearing the feed's name, so a
    human looking for what was addressed to them found a general-purpose
    query tool and no sign that a feed existed.

    Asserted on the source rather than on behaviour because there is no
    browser here: what matters is which endpoint the tab's own loader
    names."""
    src = feed_source()
    assert "/feed?since=" in src, "the feed tab must call /feed"
    assert "timeout=0" in src, (
        "without timeout=0 the tab parks the browser on the common case"
    )
    # The filtered read survives, under its own controls — nothing was
    # removed, it just stopped claiming to be the feed.
    assert '$("#readLoad")' in src and "/read?" in src


def test_the_badge_counts_unseen_not_open_requests() -> None:
    """Piece 3. The inbox badge read `1` while 195 sat unseen — a number that
    is confidently wrong stops a person looking, which is worse than no
    number. The feed badge counts against a SEEN cursor that only a human act
    advances, and it must be a different key from the drain cursor: rendering
    something is not the same as somebody having read it."""
    src = feed_source()
    assert "koraxFeedSeen" in src and "koraxFeedCursor" in src, (
        "the two cursors are separate by design"
    )
    assert "feedMarkSeen" in src
    assert 'localStorage.setItem(FEED_SEEN' in src, (
        "'seen' must survive a reload; a badge that resets on refresh "
        "teaches you to ignore it"
    )


def test_the_mailbox_gap_renders_as_a_fact_and_is_not_special_cased() -> None:
    """Two rules at once, and the second is the one that ages well.

    The operator is sealed out of their own mailbox until #1403 lands, so the
    tab must render the withheld FACT rather than an empty lane. And it must
    do that WITHOUT a conditional on the gap — `filter_log` is the single
    access filter behind /read, /wait and /feed, so the carve-out makes real
    DMs appear with no change here. A client that special-cases a
    server-side gap still carries the special case long after it closes."""
    src = feed_source()
    assert "sealed_excluded" in src, "the withheld count must be rendered"
    assert "#1403" in src, "the note must name what fixes it"
    for smell in ("if (isOperator", "MAILBOX_BROKEN", "mailboxWorks"):
        assert smell not in src, f"the gap must not be special-cased: {smell}"


def test_the_manifest_holds_in_both_directions() -> None:
    """The shell's rule (JOB #1389): a tab's files are referenced from
    index.html in the same commit that adds them, and nothing is referenced
    that does not exist. Both directions, because each catches a different
    half-finished migration."""
    markup = _markup()
    assert "/perch/js/tabs/feed.js" in markup
    assert "/perch/css/pages/feed.css" in markup
    assert (PERCH_DIR / "js" / "tabs" / "feed.js").is_file()
    assert (PERCH_DIR / "css" / "pages" / "feed.css").is_file()
    # and the tab is reachable: a file that loads but no button opens is a
    # feature nobody can find.
    assert 'data-tab="feed"' in markup
    assert "feed: loadFeed" in _script(), "the tab dispatch must call it"


def test_the_old_inline_feed_handler_is_gone() -> None:
    """The migration moved the section WHOLE. Two live definitions of the
    same tab is the two-places defect the split exists to prevent — and the
    stale one would win or lose depending on script order, which is the
    worst kind of bug to debug."""
    inline = _markup()
    assert '$("#feedLoad").addEventListener' not in inline.split("<script src")[0], (
        "the shell must not still define the feed handler inline"
    )
    assert _script().count('$("#feedLoad").addEventListener') == 1


def test_the_empty_message_no_longer_lies_over_unrendered_mail() -> None:
    """'the inbox is empty — the colony is running without you' was printed
    over a nest that had things in it the tab would not render. The claim is
    now conditional on the nest actually being empty."""
    src = _script()
    assert "no open requests — the rest of the nest is below" in src
    assert "inboxRest" in src and "inboxRest" in _markup()
