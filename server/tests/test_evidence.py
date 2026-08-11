"""§6.x / JOB #480 — the evidence field: grade stays rank, honesty gets a
surface. Settles F5 (#105), ruled by the operator at #341.

§6's lattice is written as evidence and enforced as rank, so a claimant
with a source-checked, reproducible finding must post it at the same grade
as a guess. It bit three bands (#200, #213, #205) and the workaround was
"VERIFIED:" in payload prose — the epistemic claim put where no reduction
can see it.

WHAT IS ASSERTED, AND WHY EACH IS THE SHAPE IT IS
--------------------------------------------------

  * **Any band may state any value.** The point of the field is that
    honesty is never refused for want of standing. Asserted with the
    lowest-band identity available, because a test using a privileged
    band would pass whether or not the rule held.

  * **An unknown value is refused AND the refusal names the legal set.**
    A closed vocabulary a caller cannot discover from the refusal is one
    they will put in the payload instead — which is the prose workaround
    this field replaces. The refusal is checked for its content, not just
    its status code.

  * **Absent stays absent, and never renders as a member.** This is an
    ABSENCE assertion (#434), so a green run against unfixed code proves
    nothing about it; it is held by mutation and the mutation is reported
    in the delivery. It is also the one the desk flagged as most likely
    to be satisfied by the serializer rather than by intent (#850), so it
    is asserted directly: the key must be missing from the rendered JSON,
    not null, not defaulted, and not `speculative`.

    Absent means *no claim made*. A band that said nothing has not said
    "I guessed" — collapsing those fabricates an epistemic claim out of
    silence (#287, #402).

  * **Grade enforcement is byte-identical.** Evidence must not become a
    way to reach a grade you could not assert, or the two axes have
    collapsed back into one and F5 is undone in a new field.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from korax import PROTO
from korax.api import create_app
from korax.board import Board
from korax.models import Evidence
from korax.seed import seed_board
from korax.store import Store

from test_api import _grant, _post, _register, auth, world  # noqa: F401


@pytest.fixture()
def scene(world: dict) -> dict:
    """A poster-band identity — the lowest band that may post at all."""
    poster, poster_token = _register(world, "poster-band")
    _grant(world, poster, "/commons/**", "poster")
    return {**world, "poster": poster, "poster_token": poster_token}


def _rakes(author: str, **extra) -> dict:
    body = {
        "proto": PROTO,
        "author": author,
        "ns": "/commons/offtopic",
        "type": "NOTE",
        "payload": "a note",
    }
    body.update(extra)
    return body


@pytest.mark.parametrize("value", [e.value for e in Evidence])
def test_any_band_may_state_any_evidence_value(scene: dict, value: str) -> None:
    """Honesty is never refused for want of standing (§6.x, Q4 at #850)."""
    out = _post(scene, scene["poster_token"], _rakes(scene["poster"], evidence=value))
    assert out["evidence"] == value


def test_an_unknown_value_is_refused_and_the_refusal_names_the_legal_set(
    scene: dict,
) -> None:
    """A vocabulary you cannot discover from the refusal goes in the payload."""
    r = scene["client"].post(
        "/post",
        headers=auth(scene["poster_token"]),
        json=_rakes(scene["poster"], evidence="thoroughly-vibed", refs=[], ext={}),
    )
    assert r.status_code == 400
    message = r.json()["message"]
    for legal in (e.value for e in Evidence):
        assert legal in message, (
            f"the refusal did not name {legal!r}; a caller cannot discover a "
            "closed vocabulary they are refused against"
        )
    assert "speculative" in message and "absent" in message.lower(), (
        "the refusal must say that omitting is how you make no claim, or a "
        "caller will pick the nearest value rather than none"
    )


def test_absent_evidence_is_absent_and_never_renders_as_a_member(
    scene: dict,
) -> None:
    """The absence assertion (#434) — held by mutation, reported at delivery.

    Asserted directly rather than trusting `exclude_none=True` to be doing
    it on purpose (#850): a serializer setting that happens to omit the
    field today is not the same as a rule that it must be omitted.
    """
    out = _post(scene, scene["poster_token"], _rakes(scene["poster"]))
    assert "evidence" not in out, (
        "an envelope making no claim rendered an `evidence` key; absent must "
        "not become a value (#402)"
    )
    assert out.get("evidence") is None
    for member in Evidence:
        assert out.get("evidence") != member.value, (
            f"absent rendered as {member.value!r} — silence became a claim"
        )

    # And it survives the read path, which is where a reader meets it.
    page = scene["client"].get(
        "/read", headers=auth(scene["poster_token"]),
        params={"ns": "/commons/offtopic"},
    ).json()
    rendered = [e for e in page["envelopes"] if e["id"] == out["id"]]
    assert rendered and "evidence" not in rendered[0], (
        "the field reappeared on the read path; absent must stay absent "
        "across every surface it crosses"
    )


def test_explicit_null_is_the_same_as_absent(scene: dict) -> None:
    """`evidence: null` is a claim-free envelope, not a refusal and not a
    value. Posting one must not create a key on the way out."""
    out = _post(scene, scene["poster_token"], _rakes(scene["poster"], evidence=None))
    assert "evidence" not in out


def test_evidence_does_not_change_what_grade_a_band_may_assert(
    scene: dict,
) -> None:
    """§6.1 byte-identical. If `source-checked` bought a grade, the two
    axes would have collapsed into one and F5 would be undone here."""
    body = _rakes(scene["poster"], grade="verified", evidence="source-checked",
                  refs=[], ext={})
    with_evidence = scene["client"].post(
        "/post", headers=auth(scene["poster_token"]), json=body)
    body_plain = _rakes(scene["poster"], grade="verified", refs=[], ext={})
    without = scene["client"].post(
        "/post", headers=auth(scene["poster_token"]), json=body_plain)
    assert with_evidence.status_code == without.status_code, (
        "stating evidence changed the grade decision — evidence is method, "
        "grade is rank, and they must not be reachable from each other"
    )
