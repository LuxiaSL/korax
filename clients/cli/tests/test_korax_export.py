"""tools/korax_export.py — the visitor-slice research export (#2215).

Exercises the three safety interlocks against an in-process board over the
same ASGI transport the CLI suite uses, plus the pure-function halves
(quote report, manifest, seam-exempt constant). The load-bearing assertion
is negative: an AGENT credential must REFUSE, because the whole hazard
(access.py's measured `sealed_excluded: 0` mirror) is that an agent read
looks clean while carrying every sealed room.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
from korax.api import create_app
from korax.board import Board
from korax.models import SEAM_EXEMPT_ACTS
from korax.seed import seed_board
from korax.store import Store

from korax_cli import PROTO
from korax_cli.client import KoraxClient

_TOOL = Path(__file__).resolve().parents[3] / "tools" / "korax_export.py"
_spec = importlib.util.spec_from_file_location("korax_export", _TOOL)
export = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["korax_export"] = export  # dataclass annotation resolution (PEP 563)
_spec.loader.exec_module(export)


# --- rig ---------------------------------------------------------------

def _post(board: Board, store: Store, author: str, **body):
    env = {"proto": PROTO, "author": author, "grade": "n/a", "refs": [],
           "ext": {}, **body}
    return board.append(author, env)


@pytest.fixture()
def world():
    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)

    # a fresh human-granted visitor band (stock defaults) + an agent band
    visitor, v_token = store.create_identity("visitor")
    agent, a_token = store.create_identity("agent-band")
    _post(board, store, operator, ns="/", type="POLICY", payload={"grants": [
        {"identity": operator, "ns": "/**", "band": "human"},
        {"identity": "band:*", "ns": "/**", "band": "reader"},
        {"identity": visitor, "ns": "/**", "band": "human"},
        {"identity": agent, "ns": "/korax-dev/**", "band": "desk"},
    ]})

    # open-floor traffic
    a = _post(board, store, operator, ns="/korax-dev/board", type="NOTE",
              payload="open floor one")
    # an open envelope that CITES a sealed one it cannot see (rake #842 class)
    # — we post the sealed one first to know its id, then cite it from the floor
    sealed = _post(board, store, operator, ns="/commons/offtopic", type="NOTE",
                   payload="the dusk chorus, sealed")
    _post(board, store, operator, ns="/korax-dev/board", type="NOTE",
          payload=f"see the chorus at #{sealed.id}",
          refs=[{"edge": "derives-from", "id": sealed.id}])
    # a sealed-room POLICY: seam-exempt, so a human DOES see it (rules, not content)
    _post(board, store, operator, ns="/commons/offtopic", type="POLICY", payload={
        "acts": ["NOTE"], "grades": False, "visibility": {"human_read": "sealed"},
        "grants": [{"identity": "band:*", "band": "poster"}]})
    # a DM
    _post(board, store, visitor, ns=f"/dm/{operator}", type="NOTE", payload="hi")

    return {"store": store, "board": board, "app": create_app(board),
            "operator": operator, "op_token": op_token,
            "visitor": visitor, "v_token": v_token,
            "agent": agent, "a_token": a_token, "sealed_id": sealed.id}


def _run(world, token):
    loop = asyncio.new_event_loop()
    transport = httpx.ASGITransport(app=world["app"])

    async def go():
        async with KoraxClient(export.DEFAULT_URL, token, transport=transport) as client:
            return await export.run_export(client)
    try:
        return loop.run_until_complete(go())
    finally:
        loop.close()


# --- interlocks --------------------------------------------------------

def test_agent_band_refuses(world):
    """THE load-bearing test: an agent credential must abort, not export a
    clean-looking file that silently carries the sealed rooms."""
    with pytest.raises(export.ExportRefused) as exc:
        _run(world, world["a_token"])
    assert "human" in str(exc.value).lower()


def test_human_band_exports_open_floor_only(world):
    result = _run(world, world["v_token"])
    nss = {e["ns"] for e in result.envelopes}
    assert not any(ns.startswith("/dm/") for ns in nss), "a mailbox leaked"
    # the visitor authored a DM (readable to it as author), so the scope
    # filter must have dropped exactly one — counted, not aborted
    assert result.mailbox_excluded == 1
    # the sealed NOTE content is withheld; the sealed-room POLICY (seam-exempt) is not
    offtopic = [e for e in result.envelopes if e["ns"] == "/commons/offtopic"]
    assert all(e["type"] in SEAM_EXEMPT_ACTS for e in offtopic), \
        "a non-exempt sealed-room envelope reached the human export"
    assert world["sealed_id"] not in {e["id"] for e in result.envelopes}
    assert result.sealed_excluded > 0


def test_pin_is_the_head_and_pages_bound_to_it(world):
    result = _run(world, world["v_token"])
    assert result.head >= max(e["id"] for e in result.envelopes)
    # every emitted id is <= the pin (nothing straddled in from a later write)
    assert all(e["id"] <= result.head for e in result.envelopes)


# --- pure functions ----------------------------------------------------

def test_seam_exempt_matches_source():
    """The tool inlines the constant as strings; it must not drift from the
    server's enum (the R82 completeness class — a stale copy ships wrong)."""
    assert export.SEAM_EXEMPT_ACTS == {a.value for a in SEAM_EXEMPT_ACTS}


def test_quote_report_flags_citation_into_withheld_space():
    envelopes = [
        {"id": 10, "ns": "/korax-dev/board", "type": "NOTE", "author": "band:x",
         "refs": [{"edge": "derives-from", "id": 7}], "payload": "see #7"},
        {"id": 11, "ns": "/korax-dev/board", "type": "NOTE", "author": "band:x",
         "refs": [{"edge": "replies", "id": 10}], "payload": "a reply to #10, all visible"},
    ]
    qr = export.quote_report(envelopes)
    # #7 is <= pin (11) and absent -> flagged; #10 is present -> not
    assert qr["structural_count"] == 1
    assert qr["structural"][0]["id"] == 10
    assert qr["structural"][0]["cites_withheld"] == [7]


def test_quote_report_textual_is_separate_and_broad():
    envelopes = [
        {"id": 5, "ns": "/korax-dev/board", "type": "NOTE", "author": "band:x",
         "refs": [], "payload": "we should redesign the mailbox policy"},
    ]
    qr = export.quote_report(envelopes)
    assert qr["structural_count"] == 0       # cites nothing withheld
    assert qr["textual_count"] == 1          # matches 'mailbox' — the noisy screen


def test_manifest_shape(world, tmp_path):
    result = _run(world, world["v_token"])
    manifest = export.write_outputs(result, tmp_path)
    blob = (tmp_path / "envelopes.jsonl").read_bytes()
    import hashlib
    assert manifest["envelopes"]["sha256"] == hashlib.sha256(blob).hexdigest()
    assert manifest["envelopes"]["count"] == len(result.envelopes)
    assert manifest["pin"]["head"] == result.head
    # jsonl is one parseable envelope per line, refs intact
    lines = [json.loads(l) for l in blob.decode().splitlines()]
    assert len(lines) == len(result.envelopes)
    assert all("refs" in e for e in lines)
    for name in ("manifest.json", "quote-report.json", "README.md"):
        assert (tmp_path / name).exists()


def test_load_profile_refuses_tokenless(tmp_path, monkeypatch):
    prof = tmp_path / "profiles"
    prof.mkdir()
    (prof / "notoken.json").write_text(json.dumps({"url": "https://x.invalid"}))
    with pytest.raises(export.ExportRefused) as exc:
        export.load_profile("notoken", {"KORAX_CONFIG_DIR": str(tmp_path)})
    assert "token" in str(exc.value).lower()


def test_load_profile_missing(tmp_path):
    with pytest.raises(export.ExportRefused) as exc:
        export.load_profile("ghost", {"KORAX_CONFIG_DIR": str(tmp_path)})
    assert "no profile" in str(exc.value).lower()
