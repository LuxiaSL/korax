"""The read projection — structure without rhetoric (JOB #1447).

Remedy 3 of the perf pass. The motivating measurement (#1396): the perch
pulls the whole visible log — 4.36 MB — on first paint to compute about
twenty namespace strings, because the read path has no way to return
envelopes without their payloads.

**THE RISK THIS SUITE EXISTS FOR IS NOT PERFORMANCE.** It is that a new
read surface with §9.3 contact quietly reports counters that do not
describe the page they ride on. The projection must narrow FIELDS of
envelopes the requester may already read, and nothing else — not who may
read, not what is counted as withheld. So the counter-equivalence test is
written first and canaried in both directions (canon v6's amendment of
#112): a comparator that cannot fail is not a comparator.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.seed import seed_board
from korax.store import Store

SUMMARY_OMITS = ("payload", "ext")
SUMMARY_KEEPS = ("id", "ts", "ns", "type", "author", "grade", "refs")


@pytest.fixture()
def world() -> dict:
    store = Store(":memory:")
    op, tok = store.create_identity("operator")
    store.set_meta("genesis_identity", op)
    board = Board(store)
    seed_board(board, op)
    return {"client": TestClient(create_app(board)), "op": op, "tok": tok,
            "board": board, "store": store}


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


def _mixed_slice(world: dict) -> tuple[str, str]:
    """A slice where something IS withheld from the requester, so the
    counters under test are non-zero.

    A zero-versus-zero comparison would pass on a projection that dropped
    the counters entirely, which is the failure this test exists to catch
    — the same vacuous-control shape #1009 pulled this band up on."""
    poster, ptok = _band(world, "chorus-poster", "/commons/offtopic", "poster")
    for i in range(3):
        r = world["client"].post("/post", headers=auth(ptok), json={
            "proto": PROTO, "author": poster, "ns": "/commons/offtopic",
            "type": "NOTE", "grade": "n/a", "refs": [],
            "payload": f"chorus {i} — sealed from the human band by §8.7",
            "ext": {},
        })
        assert r.status_code == 200, r.text
    return poster, ptok


# -- the §9.3 guarantee, first and hardest ----------------------------------


def test_the_projection_reports_the_same_counters_as_the_full_read(
    world: dict,
) -> None:
    """**The acceptance the brief names, and the one the gate should read
    hardest.** Same slice, same requester, one full read and one projected:
    every exclusion counter must be identical. The projection narrows what
    each envelope SHOWS; it must not touch what the page says was withheld
    from it."""
    _mixed_slice(world)

    full = world["client"].get(
        "/read", params={"limit": 500}, headers=auth(world["tok"])).json()
    proj = world["client"].get(
        "/read", params={"limit": 500, "summary": "true"},
        headers=auth(world["tok"])).json()

    # The slice itself must be the same envelopes in the same order — a
    # projection that also filtered would make the counter comparison
    # meaningless.
    assert [e["id"] for e in proj["envelopes"]] == [e["id"] for e in full["envelopes"]]
    assert proj["cursor"] == full["cursor"]

    for key in ("sealed_excluded", "rotated_excluded", "withheld_scope",
                "participation_excluded"):
        assert proj[key] == full[key], f"{key} differs between projected and full"

    # And the comparison is not vacuous: something really was withheld.
    assert full["sealed_excluded"] > 0, (
        "this fixture must produce a non-zero withheld count, or the "
        "equivalence above compares zero to zero and proves nothing"
    )


def test_the_counter_equivalence_test_can_fail(world: dict) -> None:
    """**The canary for the test above, in the direction that matters.**

    #112 as amended in canon v6: a comparator is only worth having if it
    is shown to redden. Here the check is that the counters are read from
    the response rather than assumed — so a response whose counters were
    computed over a DIFFERENT pile must fail the comparison. Simulated by
    corrupting one side, because the real defect (a projection path that
    recomputes counters over its own list) cannot be injected without
    writing the bug."""
    _mixed_slice(world)
    full = world["client"].get(
        "/read", params={"limit": 500}, headers=auth(world["tok"])).json()
    proj = world["client"].get(
        "/read", params={"limit": 500, "summary": "true"},
        headers=auth(world["tok"])).json()

    tampered = dict(proj, sealed_excluded=proj["sealed_excluded"] + 1)
    with pytest.raises(AssertionError):
        assert tampered["sealed_excluded"] == full["sealed_excluded"]

    tampered2 = dict(proj, withheld_scope="board" if
                     proj["withheld_scope"] != "board" else "namespace")
    with pytest.raises(AssertionError):
        assert tampered2["withheld_scope"] == full["withheld_scope"]


def test_the_projection_does_not_widen_what_a_band_can_see(world: dict) -> None:
    """The other §9.3 direction, and the one that would be a real leak: a
    projection must not become a back door to envelopes the requester
    cannot read.

    NOT asserted as "the slice is empty" — my first draft did, and it was
    wrong about the board rather than about the code: `/commons/offtopic`
    holds the operator's own POLICY, and POLICY is in `SEAM_EXEMPT_ACTS`,
    so the seam correctly lets it through. **A test that asserts a false
    fact about the board fails loudest when the code is right**, which is
    the most expensive kind of red. The real property is that the
    projection sees exactly what the full read sees — no more."""
    poster, _ = _mixed_slice(world)

    full = world["client"].get(
        "/read", params={"ns": "/commons/offtopic"},
        headers=auth(world["tok"])).json()
    proj = world["client"].get(
        "/read", params={"ns": "/commons/offtopic", "summary": "true"},
        headers=auth(world["tok"])).json()

    assert [e["id"] for e in proj["envelopes"]] == [e["id"] for e in full["envelopes"]]
    # and the sealed chorus is in neither: the projection is not a door.
    for page in (full, proj):
        assert not [e for e in page["envelopes"] if e["author"] == poster], (
            "the chorus NOTEs are sealed from a human band; neither the full "
            "read nor its projection may carry them"
        )
        assert page["sealed_excluded"] > 0, "and both must say so"


# -- what the projection actually is ----------------------------------------


def test_summary_omits_the_payload_and_keeps_the_structure(world: dict) -> None:
    _mixed_slice(world)
    proj = world["client"].get(
        "/read", params={"limit": 500, "summary": "true"},
        headers=auth(world["tok"])).json()
    assert proj["envelopes"], "fixture produced nothing to project"

    for e in proj["envelopes"]:
        for gone in SUMMARY_OMITS:
            assert gone not in e, f"{gone} must not survive the projection"
        for kept in SUMMARY_KEEPS:
            assert kept in e, f"{kept} is structure and must survive"
        # presence and size, so a caller can tell there IS content and how
        # much, without being handed it.
        assert isinstance(e["payload_bytes"], int)
        assert isinstance(e["ext_present"], bool)


def test_the_projection_is_smaller_and_the_saving_is_the_payloads(
    world: dict,
) -> None:
    """The point of the job, asserted rather than assumed. Not a
    performance threshold — a shape check that the bytes went where the
    design says they went."""
    _mixed_slice(world)
    full = world["client"].get("/read", params={"limit": 500},
                               headers=auth(world["tok"]))
    proj = world["client"].get("/read", params={"limit": 500, "summary": "true"},
                               headers=auth(world["tok"]))
    assert len(proj.content) < len(full.content)

    payload_bytes = sum(
        len(json.dumps(e.get("payload", ""))) for e in full.json()["envelopes"])
    saved = len(full.content) - len(proj.content)
    assert saved > payload_bytes * 0.5, (
        f"saved {saved} bytes but payloads alone are {payload_bytes}; the "
        "projection is not omitting what it claims to omit"
    )


def test_the_default_is_unchanged(world: dict) -> None:
    """A read with no `summary` must be byte-identical to what it was
    before this job — every existing caller, every client, every parked
    cursor. The projection is opt-in or it is a breaking change."""
    _mixed_slice(world)
    plain = world["client"].get("/read", params={"limit": 500},
                                headers=auth(world["tok"])).json()
    explicit = world["client"].get(
        "/read", params={"limit": 500, "summary": "false"},
        headers=auth(world["tok"])).json()
    assert plain == explicit
    assert all("payload" in e or e["type"] == "PIN" for e in plain["envelopes"][:5])


# -- the clients, and the perch caller that motivated the job ---------------


def test_the_cli_models_the_projection_as_its_own_shape() -> None:
    """R61's rule on a surface I am ADDING, not one I found.

    `Envelope.payload` is optional, so a projected record would validate
    through the full model and arrive as `payload=None` — indistinguishable
    from an envelope that genuinely has no payload. `SummaryEnvelope`
    declares what the projection HAS and does not declare `payload` at all,
    so reading it fails at the point of the mistake."""
    from korax_cli.wire import SummaryEnvelope, SummaryReadPage  # noqa: PLC0415

    rec = {"proto": "korax/0.1", "id": 1, "ts": "2026-08-11T00:00:00Z",
           "author": "band:x", "band": "reader", "ns": "/x", "type": "NOTE",
           "grade": "n/a", "refs": [], "payload_bytes": 12, "ext_present": False}
    parsed = SummaryEnvelope.model_validate(rec)
    assert parsed.payload_bytes == 12 and parsed.ext_present is False
    assert not hasattr(parsed, "payload"), (
        "the projected shape must not carry a payload field at all — a "
        "None there is the fabrication R61 removed from the counters"
    )

    # required with no default: a board that omits them is a shape error,
    # never a zero invented locally.
    import pytest as _pytest  # noqa: PLC0415
    from pydantic import ValidationError  # noqa: PLC0415
    with _pytest.raises(ValidationError):
        SummaryEnvelope.model_validate({k: v for k, v in rec.items()
                                        if k != "payload_bytes"})

    # the page inherits every §9.3 promise unchanged
    for counter in ("sealed_excluded", "rotated_excluded",
                    "participation_excluded", "withheld_scope"):
        assert counter in SummaryReadPage.model_fields


def test_the_perch_boot_path_asks_for_structure(world: dict) -> None:
    """The motivating caller (#1396): `nsIndex` pulls the whole visible log
    on first paint to collect namespace strings. It must ask for the
    projection — and the response must still carry the field it reads."""
    from pathlib import Path  # noqa: PLC0415

    plumbing = (Path(__file__).resolve().parents[1] / "korax" / "perch"
                / "js" / "plumbing.js").read_text()
    assert "summary=true" in plumbing, "the boot read must ask for structure"

    proj = world["client"].get(
        "/read", params={"limit": 5000, "summary": "true"},
        headers=auth(world["tok"])).json()
    assert proj["envelopes"], "fixture produced nothing"
    assert all("ns" in e for e in proj["envelopes"]), (
        "nsIndex reads `ns` off every record; the projection must keep it"
    )
