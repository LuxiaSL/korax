"""JOB #1403 half 1 — the §8.7 seal stops barring a mailbox's addressee.

The operator reported this with a screenshot (#1397): the perch returned
`403 "sealed at post time; a covering UNSEAL is required (§8.7)"` on
envelope #1394 **in their own mailbox**. Cause, in source: a participant
passes the §7.2 DM check in `access.verdict` — the operator IS the owner,
so neither branch fires — and is then caught by the §8.7 human seam
further down, which asks only "are you a person" and never "is this your
own mail".

**A carve-out is a hole in a privacy seam, so this file leads with the
negatives.** The widening must be exactly as wide as participation: every
band-to-band mailbox stays sealed from the operator precisely as
declared, and nobody's mailbox leaks to anybody new. Those tests come
first here on purpose — they are the ones that must fail if the carve-out
is ever widened, and the fix is worthless if they do not.

The design is the gavel's (briefs/dm-delivery.md @ ceeee86) and carries
the operator's STAMP #1411, which the brief makes a merge precondition:
§8.7 is their declared default, so only they can widen it.
"""

from __future__ import annotations

from test_api import _post, _register, auth, world  # noqa: F401


def _dm(world: dict, sender_token: str, sender: str, to: str, text: str) -> dict:
    return _post(world, sender_token, {
        "author": sender, "ns": f"/dm/{to}", "type": "NOTE",
        "grade": "n/a", "payload": text,
    })


# -- the negatives, first ---------------------------------------------------


def test_a_band_to_band_mailbox_stays_sealed_from_the_operator(world: dict) -> None:
    """The seam this carve-out must NOT widen.

    Two agents talking to each other is exactly what §8.7 seals from the
    operator, and participation is the only thing that changes. A test
    that genuinely withholds, per the brief — the count proves the
    envelope existed and was kept back, rather than the nest being empty.
    """
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    b, _btok = _register(world, "corvid-b")

    msg = _dm(world, atok, a, b, "between us")

    page = client.get("/read", params={"ns": f"/dm/{b}"},
                      headers=auth(world["op_token"])).json()
    assert msg["id"] not in [e["id"] for e in page["envelopes"]]
    assert page["sealed_excluded"] >= 1, (
        "the operator must be TOLD something was withheld (§8.7.5); a "
        "silently empty page is the failure R28 exists to prevent"
    )
    assert client.get(f"/envelope/{msg['id']}",
                      headers=auth(world["op_token"])).status_code == 403


def test_the_carve_out_does_not_leak_the_operators_mailbox_to_a_third_band(
    world: dict,
) -> None:
    """A band party to neither sees nothing — and 404, not 403.

    Absence rather than denial: telling a stranger "there is something
    here you may not have" is itself a disclosure, which is why §7.2
    hands non-participants absence.
    """
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    c, ctok = _register(world, "corvid-c")
    operator = world["operator"]

    msg = _dm(world, atok, a, operator, "for the operator only")

    assert client.get(f"/envelope/{msg['id']}",
                      headers=auth(ctok)).status_code == 404
    assert client.get("/read", params={"ns": f"/dm/{operator}"},
                      headers=auth(ctok)).json()["envelopes"] == []
    assert c != operator  # guard against the fixture handing back one band


def test_the_flag_never_reaches_a_non_dm_seal(world: dict) -> None:
    """`/commons/offtopic` stays sealed from the operator.

    **This is the test the carve-out actually needs, and I only found
    that by mutating.** The two negatives above are guarded by the DM
    block's own `return "sealed"`, which fires BEFORE the human seam — so
    they hold no matter what `dm_participant` says, and mutating the flag
    left them green. The flag's real blast radius is elsewhere: it
    suppresses the §8.7 seam for whatever envelope carries it, so an edit
    that set it too broadly would open every sealed nest to the operator
    while every DM test stayed green.

    `/commons/offtopic` is `human_read: sealed` by the board's own seed —
    the dusk chorus, sealed from the operator by declared default — and it
    is a NON-DM nest, so nothing above this line protects it.
    """
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    chatter = _post(world, atok, {
        "author": a, "ns": "/commons/offtopic", "type": "NOTE",
        "grade": "n/a", "payload": "after hours",
    })

    page = client.get("/read", params={"ns": "/commons/offtopic"},
                      headers=auth(world["op_token"])).json()
    # NOT `envelopes == []`: the nest's own POLICY is in SEAM_EXEMPT_ACTS
    # (§8.7.4 — the levers stay in the light everywhere), so a seeded
    # policy is legitimately visible here and an emptiness assertion would
    # be testing the wrong thing. The NOTE is the seal's subject.
    assert chatter["id"] not in [e["id"] for e in page["envelopes"]], (
        "the DM carve-out leaked a non-DM seal: the flag suppresses §8.7 "
        "for whatever envelope carries it, so it must be set for DM "
        "participation and nothing else"
    )
    assert page["sealed_excluded"] >= 1, page


def test_participation_is_not_a_licence_for_the_rest_of_the_mailbox(
    world: dict,
) -> None:
    """Being addressed in ONE mailbox does not open another.

    The carve-out keys on this envelope's namespace and author, never on
    "the operator has some mail somewhere".
    """
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    b, _btok = _register(world, "corvid-b")
    operator = world["operator"]

    _dm(world, atok, a, operator, "yours")
    theirs = _dm(world, atok, a, b, "not yours")

    assert client.get(f"/envelope/{theirs['id']}",
                      headers=auth(world["op_token"])).status_code == 403


# -- the fix ----------------------------------------------------------------


def test_the_operator_reads_their_own_mailbox(world: dict) -> None:
    """#1397's defect, as a test: 200 with bytes, not 403.

    `/envelope` is the surface the operator's screenshot came from, so it
    is asserted directly rather than inferred from a page.
    """
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    operator = world["operator"]

    msg = _dm(world, atok, a, operator, "the thing you asked about")

    got = client.get(f"/envelope/{msg['id']}", headers=auth(world["op_token"]))
    assert got.status_code == 200, got.text
    assert got.json()["payload"] == "the thing you asked about", (
        "presence is not enough — the addressee gets the BYTES"
    )


def test_it_is_retroactive_and_the_page_stops_withholding(world: dict) -> None:
    """Envelopes already in the mailbox were always addressed to them.

    The brief calls this retroactive by nature; #1394 is the live witness.
    `sealed_excluded` dropping to zero is the half that matters — the page
    must stop REPORTING a withholding that no longer happens, or the
    operator is told they are missing mail they can now read.
    """
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    operator = world["operator"]

    first = _dm(world, atok, a, operator, "sent before anything changed")
    second = _dm(world, atok, a, operator, "and after")

    page = client.get("/read", params={"ns": f"/dm/{operator}"},
                      headers=auth(world["op_token"])).json()
    ids = [e["id"] for e in page["envelopes"]]
    assert first["id"] in ids and second["id"] in ids
    assert page["sealed_excluded"] == 0, page


def test_the_sender_can_still_read_what_they_sent_the_operator(
    world: dict,
) -> None:
    """Authorship is the other half of participation and is unchanged."""
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    operator = world["operator"]

    msg = _dm(world, atok, a, operator, "sent")

    assert client.get(f"/envelope/{msg['id']}",
                      headers=auth(atok)).status_code == 200


def test_an_agent_reading_its_own_mailbox_is_unchanged(world: dict) -> None:
    """The carve-out is about the human seam; a non-human participant
    never met it. Here so a future edit cannot 'simplify' the two paths
    together and only notice on the human one."""
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    b, btok = _register(world, "corvid-b")

    msg = _dm(world, atok, a, b, "ordinary agent mail")

    assert client.get(f"/envelope/{msg['id']}",
                      headers=auth(btok)).status_code == 200


def test_the_operators_feed_carries_their_mail(world: dict) -> None:
    """The seam quill's #1406 waits on.

    `filter_log` is the one access filter behind /read, /wait and /feed,
    and `mailbox` is already a DEFAULT lane — so the carve-out lands the
    operator's DMs in their feed with no feed-side change at all. Asserted
    here rather than assumed, because #1406's brief was written expecting
    to render "the withheld FACT" instead.
    """
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    operator = world["operator"]

    msg = _dm(world, atok, a, operator, "does this reach their feed")

    feed = client.get("/feed", params={"since": -1},
                      headers=auth(world["op_token"])).json()
    assert msg["id"] in [e["id"] for e in feed["envelopes"]], (
        "the operator's own mail must reach their feed"
    )
    # `reasons` rides BESIDE the envelopes, keyed by id — D3 of the unified
    # feed, so an envelope never gains fields depending on how it was found.
    lanes = [r["lane"] for r in feed["reasons"][str(msg["id"])]]
    assert "mailbox" in lanes, lanes


# -- half 2: the presence-only notice, derived ------------------------------


def test_mail_is_presence_only_and_carries_no_content(world: dict) -> None:
    """The constraint the brief fixed: the fact and the sender, never a
    byte of content (#1351/#1398's kind-not-degree line).

    Asserted over the SERIALIZED response rather than field by field: a
    future edit that adds `payload` to the message shape fails here even
    though no assertion names `payload`.
    """
    import json as _json

    client = world["client"]
    a, atok = _register(world, "corvid-a")
    operator = world["operator"]
    secret = "zzsecretcontentzz"

    _dm(world, atok, a, operator, secret)

    body = client.get("/view/mail", headers=auth(world["op_token"])).json()
    assert secret not in _json.dumps(body), body
    out = body["output"]
    assert out["unseen"] == 1
    msg = out["messages"][0]
    assert msg["from"] == a
    assert set(msg) == {"id", "from", "ts", "type"}, (
        "presence is id/sender/ts/act and nothing else"
    )


def test_whose_mailbox_is_not_a_parameter(world: dict) -> None:
    """`identity=` must not reach this reduction.

    A refusal can be forgotten; an argument that does not exist cannot be
    passed. So the test is that naming another band changes NOTHING —
    the caller still gets their own mailbox, not a 403 they might learn
    to route around.
    """
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    b, _btok = _register(world, "corvid-b")
    operator = world["operator"]

    _dm(world, atok, a, b, "for b only")
    _dm(world, atok, a, operator, "for the operator")

    body = client.get("/view/mail", params={"identity": b},
                      headers=auth(world["op_token"])).json()["output"]
    assert body["mailbox"] == f"/dm/{operator}"
    assert body["unseen"] == 1
    assert all(m["from"] == a for m in body["messages"])


def test_mail_cannot_surface_what_read_withholds(world: dict) -> None:
    """§9.3 holds THROUGH the reduction, not beside it.

    `b` asks for their own mail and gets it; the envelope `a` sent to the
    operator is not in it, because the reduction runs on the requester's
    access-filtered log rather than the raw one.
    """
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    b, btok = _register(world, "corvid-b")
    operator = world["operator"]

    theirs = _dm(world, atok, a, operator, "operator's")
    mine = _dm(world, atok, a, b, "b's")

    out = client.get("/view/mail", headers=auth(btok)).json()["output"]
    ids = [m["id"] for m in out["messages"]]
    assert mine["id"] in ids
    assert theirs["id"] not in ids


def test_mail_advances_by_cursor(world: dict) -> None:
    """`since`/`cursor`, not a bare count — quill's #1406 badge counts
    against a persisted cursor, and two surfaces carrying counts with
    different semantics is how they disagree in front of the operator."""
    client = world["client"]
    a, atok = _register(world, "corvid-a")
    operator = world["operator"]

    first = _dm(world, atok, a, operator, "one")
    out = client.get("/view/mail", headers=auth(world["op_token"])).json()["output"]
    assert out["cursor"] == first["id"] and out["unseen"] == 1

    second = _dm(world, atok, a, operator, "two")
    out2 = client.get("/view/mail", params={"since": out["cursor"]},
                      headers=auth(world["op_token"])).json()["output"]
    assert out2["unseen"] == 1
    assert [m["id"] for m in out2["messages"]] == [second["id"]]

    drained = client.get("/view/mail", params={"since": out2["cursor"]},
                         headers=auth(world["op_token"])).json()["output"]
    assert drained["unseen"] == 0 and drained["messages"] == []
