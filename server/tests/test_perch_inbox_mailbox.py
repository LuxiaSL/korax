"""The Inbox tab reads the viewer's own mailbox (JOB #1776, ISSUE #1773).

Operator bug report #1770: a correctly-delivered DM showed up in the Feed
tab's mailbox lane and nowhere else, because `loadInbox()` only ever
queried `INBOX_NS` (the board-level escalation nest) — the viewer's own
`/dm/<band>` was never read by any surface named for reading it. Not a
delivery bug: R84/R87 fixed everything about DM delivery and readability
except folding the mailbox into the one tab called Inbox.

Guards follow the #962/#841 split used by the sibling feed/inbox tests.
**Contract** against a real board: the exact read `loadInbox()` now makes
(`/read?ns=/dm/<band>`) actually returns a DM posted to that mailbox — the
seal is cited, not re-proven (the owner reading their own sealed mailbox
is existing, tested behaviour; server/tests/test_dm_participation.py is
that territory). **Structural** over the served page: the section exists,
is wired into the load dispatch, is labeled received-only rather than
claiming to be a whole conversation, and the manifest holds.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

from perch_source import PERCH_DIR, markup as _markup, script as _script


def index_source() -> str:
    return (PERCH_DIR / "index.html").read_text()


def auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def test_a_dm_posted_to_the_viewers_mailbox_is_returned_by_the_inbox_read() -> None:
    """The exact call `loadInboxMessages()` makes, run against a real
    board: `/read?ns=/dm/<recipient>` must carry a DM posted to that
    mailbox. This is the read path — whether the render is correct is a
    separate, structural question below; this proves the data is there
    to render."""
    store = Store(":memory:")
    op, op_tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    client = TestClient(create_app(board))

    sender = client.post("/identity", json={"display": "dm-sender"},
                          headers=auth(op_tok)).json()
    sent = client.post("/post", headers=auth(sender["token"]), json={
        "proto": PROTO, "author": sender["id"], "ns": f"/dm/{op}",
        "type": "NOTE", "grade": "n/a", "refs": [], "ext": {},
        "payload": "you have not seen this yet",
    })
    assert sent.status_code == 200, sent.text

    read = client.get(f"/read?ns=/dm/{op}&limit=200", headers=auth(op_tok))
    assert read.status_code == 200, read.text
    ids = [e["id"] for e in read.json()["envelopes"]]
    assert sent.json()["id"] in ids


def test_load_inbox_calls_load_inbox_messages() -> None:
    """The dispatch wiring: `loadInbox()` must fire the mailbox drain
    independently of the escalation-nest reads, the same
    fire-and-forget shape `loadRatifications()` already uses — a
    Messages section that only rendered when opens existed would be
    the R84/R87 gap moved one call deeper rather than closed."""
    src = index_source()
    assert "loadInboxMessages();" in src.split("async function loadInbox()")[1][:400]


def test_the_mailbox_ns_is_the_viewers_own() -> None:
    """The literal construction, asserted on source rather than
    inferred from behaviour: it must be ME's own identity, never a
    hardcoded or scoped-inbox namespace — a DM tab that read someone
    else's mailbox would be a much worse bug than the one it fixes."""
    src = index_source()
    assert '"/dm/" + ME.identity' in src


def test_the_section_is_labeled_received_only() -> None:
    """Brief constraint #2: DMs the viewer SENT live in the other
    party's mailbox (R87's participant carve-out), so a
    received-only section must say so rather than read as a complete
    conversation. Each card's own conversation button is the road to
    the whole thread — the label is what stops a reader assuming
    they are already looking at it."""
    src = index_source()
    assert "received message" in src
    assert "sent messages live in the recipient's own mailbox" in src


def test_no_fabricated_read_state() -> None:
    """Brief constraint #1 (#287): the board tracks no per-envelope
    read state for DMs, so the section must count what exists, never
    invent an unread flag. A smell test rather than a positive
    assertion, because absence is the property being pinned."""
    src = index_source().split("async function loadInboxMessages()")[1]
    src = src[:src.index("\nasync function loadInbox()")]
    for smell in ("unread", "isRead", "read_state", "markRead"):
        assert smell not in src, f"fabricated read-state smell: {smell}"


def test_the_container_exists_and_is_wired() -> None:
    markup = _markup()
    assert '<div id="inboxMessages">' in markup
    assert "$(\"#inboxMessages\")" in _script()
