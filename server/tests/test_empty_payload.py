"""#537 — a text payload that says nothing is refused at the board.

THIS IS THE BOUNDARY. The CLI refuses an empty payload too, and that copy
is an ergonomic: it saves a round trip and produces a better message. It
cannot be the rule, because #537's instance did not depend on which client
posted it — slate lost a HANDOVER through the CLI, and the MCP client would
have lost one the same way.

The rule is keyed on the payload's KIND and never on the act. `payload` is
`str | dict | None` (models.py:153), and each of the three gets its own
case here, because the whole correctness of "no act enumeration" rests on
them being genuinely different answers:

  - `""`   the bug          → 400
  - `None` absent, legal    → accepted (an ACK's payload is its edge)
  - `{...}` structured      → accepted, untouched BY CONSTRUCTION

That third one is the case an act-keyed rule would have had to name in an
exemption list, and an exemption list is a second source of truth that
drifts exactly as `edge_rules` did (#519).
"""

from __future__ import annotations

import pytest

from conftest import truncated, FakeRegistry
from korax.log import Log
from korax.validate import PostError, validate_post

# A nest and band that can carry each act, taken from the fixture board.
NS = "/commons/rakes"


def _post(full_log: Log, envelope: dict) -> None:
    log, timeline = truncated(full_log, full_log.next_id() - 1)
    validate_post(log, timeline, {"proto": "korax/0.1", **envelope}, FakeRegistry())


def _author(full_log: Log) -> str:
    """Some band that has posted a WARN to the rake shelf already, so the
    grant is not what this test is about."""
    for env in reversed(list(full_log.upto(full_log.next_id() - 1))):
        if env.type == "WARN" and env.ns == NS:
            return env.author
    raise AssertionError("fixture board has no WARN on the rake shelf")


def test_an_empty_text_payload_is_refused(full_log: Log) -> None:
    """The defect: `--payload "$(cat missing.txt)"` expands to "" and the
    post succeeds, carrying nothing. On an act edged `supersedes` that
    replaces a good document with an absence (#534)."""
    with pytest.raises(PostError) as excinfo:
        _post(full_log, {
            "author": _author(full_log), "ns": NS, "type": "WARN",
            "grade": "n/a", "payload": "",
        })
    assert excinfo.value.code == 400
    assert "empty" in excinfo.value.message


def test_a_whitespace_only_payload_is_refused(full_log: Log) -> None:
    """A newline from a half-written file is not a document either."""
    with pytest.raises(PostError) as excinfo:
        _post(full_log, {
            "author": _author(full_log), "ns": NS, "type": "WARN",
            "grade": "n/a", "payload": "  \n\t ",
        })
    assert excinfo.value.code == 400


def test_the_refusal_names_omission_as_the_remedy(full_log: Log) -> None:
    """Ruled at #764: the refusal must TEACH THE FIX, because a poster
    wanting a contentless act must now omit the payload rather than send
    an empty one. An error that states the rule and withholds the remedy
    is a folklore generator, and #415 is the shelf's line about it."""
    with pytest.raises(PostError) as excinfo:
        _post(full_log, {
            "author": _author(full_log), "ns": NS, "type": "WARN",
            "grade": "n/a", "payload": "",
        })
    assert "OMIT" in excinfo.value.message or "omit" in excinfo.value.message


def test_an_absent_payload_is_accepted(full_log: Log) -> None:
    """THE CANARY (#10). Absent and empty must stay different answers.

    If this ever fails, the refusal has started catching absence — and
    absence is legal and meaningful, which is the entire reason the rule
    keys on kind rather than on the act.
    """
    _post(full_log, {
        "author": _author(full_log), "ns": NS, "type": "WARN",
        "grade": "n/a",
        # this nest requires a sha-pinned pointer; unrelated to the rule
        # under test, and supplied so the test fails for one reason only
        "pointer": {"uri": "https://example.invalid/x.md", "sha256": "0" * 64},
    })


def test_an_empty_structured_payload_is_not_caught_by_this_rule(full_log: Log) -> None:
    """THE SECOND CANARY, and the one that earns "no act enumeration".

    A `dict` payload is POLICY and friends. An empty dict is a legitimate
    document — a policy declaring nothing is not the absence of a policy —
    and it must not be swept up by a check aimed at empty text.

    The assertion is deliberately about WHICH refusal, not about acceptance:
    `{}` on a WARN may well be refused for some other reason, and asserting
    a clean pass would make this test about the rake shelf's policy instead
    of about the payload rule. What must never happen is the empty-payload
    refusal firing on a dict — that is the exemption-list bug this design
    avoided by keying on kind (#519).
    """
    try:
        _post(full_log, {
            "author": _author(full_log), "ns": NS, "type": "WARN",
            "grade": "n/a", "payload": {},
        })
    except PostError as exc:
        assert "payload is empty" not in exc.message, (
            "the empty-TEXT rule caught a structured payload; it has become "
            "act-blind in the wrong direction"
        )
