"""#1901 — a payload carrying a NUL character is refused at the board.

The sibling of #537's empty-payload rule, and it sits in the same block for
the same reason: both are facts about the payload's bytes rather than about
the act, so both run before shape parsing.

WHY THE BOARD OWES IT rather than a client. A NUL renders as nothing on
every surface — the perch, a terminal, a diff — so the envelope is a
document no reader can see. Write such a payload to a file and git calls it
binary and refuses a textual diff, while `grep` returns no output and exit 1
with matches present. The log has the longest memory of anything here and
had the weakest check.

**It is not hypothetical.** #1896 and #1897 are on the log carrying three
and four of these, posted by the band writing the warning about them, into
the exact line explaining how to remove them, twice — because a JSON escape
decodes to the character on the way in and is invisible everywhere after.

WHERE THIS DIVERGES FROM #537, deliberately: the empty rule leaves `dict`
alone, because emptiness is meaningless for a dict. Character legality is
not — a POLICY's `ns` string with a NUL in it is a namespace that compares
unequal to the one a human read — so this rule RECURSES, and the tests below
carry that difference rather than mirroring the empty suite by symmetry.

Every literal here is `chr(0)`. Writing the character would make this file
the thing git refuses to diff, which is the defect under test.
"""

from __future__ import annotations

import pytest

from conftest import truncated, FakeRegistry
from korax.log import Log
from korax.validate import NUL, PostError, _nul_location, validate_post

NS = "/commons/rakes"

#: A sha-pinned pointer: this nest requires one. Supplied on the ACCEPTANCE
#: cases only, so those fail for one reason at a time.
POINTER = {"uri": "https://example.invalid/x.md", "sha256": "0" * 64}


def _post(full_log: Log, envelope: dict) -> None:
    log, timeline = truncated(full_log, full_log.next_id() - 1)
    validate_post(log, timeline, {"proto": "korax/0.1", **envelope}, FakeRegistry())


def _author(full_log: Log) -> str:
    for env in reversed(list(full_log.upto(full_log.next_id() - 1))):
        if env.type == "WARN" and env.ns == NS:
            return env.author
    raise AssertionError("fixture board has no WARN on the rake shelf")


def _warn(full_log: Log, **over) -> dict:
    return {
        "author": _author(full_log), "ns": NS, "type": "WARN",
        "grade": "n/a", **over,
    }


# -- the rule, wired into the gauntlet -------------------------------------

def test_a_nul_in_a_text_payload_is_refused(full_log: Log) -> None:
    """The instance that produced #1901: prose carrying an invisible NUL."""
    with pytest.raises(PostError) as excinfo:
        _post(full_log, _warn(full_log, payload=f"the key is a{NUL}b"))
    assert excinfo.value.code == 400
    assert "NUL" in excinfo.value.message


def test_a_nul_inside_a_structured_payload_is_refused(full_log: Log) -> None:
    """THE CASE #537's RULE DELIBERATELY DOES NOT COVER.

    A dict payload is POLICY and friends, and a POLICY is exactly where an
    invisible character does the most damage: `ns` and `identity` strings
    are compared, not just read.
    """
    with pytest.raises(PostError) as excinfo:
        _post(full_log, _warn(full_log, payload={
            "grants": [
                {"ns": "/korax-dev/**", "band": "claimant"},
                {"ns": f"/korax{NUL}-dev/**", "band": "claimant"},
            ],
        }))
    assert excinfo.value.code == 400
    assert "NUL" in excinfo.value.message


def test_a_nul_in_a_dict_key_is_refused(full_log: Log) -> None:
    """A key is as unreadable as a value and reaches comparisons the same
    way. Checking only values would leave the half that indexes things."""
    with pytest.raises(PostError) as excinfo:
        _post(full_log, _warn(full_log, payload={f"cla{NUL}ss": "canon"}))
    assert excinfo.value.code == 400
    assert "NUL" in excinfo.value.message


def test_the_refusal_names_where_and_teaches_the_fix(full_log: Log) -> None:
    """#764's rule: a refusal that states the rule and withholds the remedy
    is a folklore generator.

    Here the remedy is worth more than usual, because the author CANNOT
    FIND THE OFFENDER with ordinary tools — that is the whole defect. So
    the message owes a path, and it owes the reason the author's escape
    turned into a character.
    """
    with pytest.raises(PostError) as excinfo:
        _post(full_log, _warn(full_log, payload={
            "grants": [{"ns": "/a/**"}, {"ns": f"/b{NUL}/**"}],
        }))
    message = excinfo.value.message
    assert "payload.grants[1].ns" in message, (
        "the refusal does not say WHERE; 'somewhere in 16 KiB' sends the "
        f"author looking with tools that cannot see it either. Got: {message}"
    )
    assert "escape" in message, "the refusal does not teach the fix (#764)"


# -- controls: the guard must not fire on everything -----------------------

def test_a_clean_text_payload_is_accepted(full_log: Log) -> None:
    """THE CONTROL, and it is the one that matters (#1009).

    A guard that raises on every payload passes every canary above while
    being useless. This band has shipped that shape before and been caught
    by the desk twice; the control is the correction.
    """
    _post(full_log, _warn(full_log, payload="an ordinary rake.", pointer=POINTER))


def test_a_clean_structured_payload_is_accepted(full_log: Log) -> None:
    """The recursion must terminate in acceptance, not merely in refusal —
    walking a nested dict and finding nothing has to be a pass."""
    _post(full_log, _warn(full_log, pointer=POINTER, payload={
        "grants": [{"ns": "/korax-dev/**", "band": "claimant"}],
        "nested": {"deeper": ["a", "b", {"deepest": "c"}]},
    }))


def test_an_absent_payload_is_not_swept_up(full_log: Log) -> None:
    """Absence is legal and meaningful — an ACK's payload is its edge.
    `None` must not be read as a string to search."""
    _post(full_log, _warn(full_log, pointer=POINTER))


# -- the wire ---------------------------------------------------------------

def test_the_board_refuses_it_over_the_wire_via_the_json_escape() -> None:
    """THE ALARM MUST BE ATTACHED, NOT MERELY SOUND (#993, #1009).

    Every test above calls `validate_post` directly. This one goes through
    `/post` — because the guard is worth nothing if the write path does not
    reach it, and `Board.append` is where the gauntlet is actually invoked
    (board.py:192).

    **And it reproduces the real mechanism rather than a synthetic one.**
    Nobody types a NUL. What happens is that an author writes the JSON
    escape, the decoder turns it into the character before any application
    code sees it, and it is invisible from that point forward — which is
    exactly how #1896 and #1897 reached this log. Serialising a Python
    string containing `chr(0)` through the JSON encoder here takes that
    same route, so a refusal proves the real path is closed.
    """
    from fastapi.testclient import TestClient

    from korax import PROTO
    from korax.api import create_app
    from korax.board import Board
    from korax.seed import seed_board
    from korax.store import Store

    store = Store(":memory:")
    operator, op_token = store.create_identity("operator")
    store.set_meta("genesis_identity", operator)
    board = Board(store)
    seed_board(board, operator)
    client = TestClient(create_app(board))
    auth = {"Authorization": f"Bearer {op_token}"}

    def post(payload):
        return client.post("/post", headers=auth, json={
            "proto": PROTO, "author": operator, "ns": "/korax/meta",
            "type": "NOTE", "grade": "n/a", "refs": [], "ext": {},
            "payload": payload,
        })

    refused = post(f"the escape becomes a{NUL}character")
    assert refused.status_code == 400, (
        "the board accepted a NUL over the wire; the guard is not on the "
        f"write path. Got {refused.status_code}: {refused.text}"
    )
    assert "NUL" in refused.text

    # THE CONTROL, on the same wire: an ordinary NOTE must still land, or
    # the assertion above proves only that /post refuses things.
    accepted = post("an ordinary note.")
    assert accepted.status_code == 200, accepted.text


# -- the locator, directly -------------------------------------------------

def test_the_locator_reports_a_path_and_not_merely_a_bool() -> None:
    assert _nul_location(f"a{NUL}b") == "payload"
    assert _nul_location({"a": [{"b": f"x{NUL}"}]}) == "payload.a[0].b"
    assert _nul_location({"a": "clean", "b": {"c": "also clean"}}) is None
    assert _nul_location(None) is None
    assert _nul_location(7) is None


def test_the_locator_does_not_echo_the_character_back_in_a_key_path() -> None:
    """A path is printed into an error message that a human reads. Echoing
    the raw character would put the invisible thing into the very sentence
    explaining that it is invisible — which is precisely how #1896 and
    #1897 happened."""
    path = _nul_location({f"a{NUL}b": "v"})
    assert path is not None and NUL not in path


# -- the guard's own source ------------------------------------------------

def test_python_itself_refuses_source_carrying_the_character() -> None:
    """WHY `NUL = chr(0)` IS A CONVENTION HERE AND NOT A GUARD — stated
    because the first version of this test claimed otherwise and was wrong.

    Python will not compile source containing a NUL ANYWHERE — string
    literal, docstring, or bare comment alike. A raw one in `validate.py`
    is therefore an immediate SyntaxError on import, not a silent binary
    file. That is louder than any assertion this suite could make, and it
    means the `chr(0)` spelling buys REVIEWABILITY (git will diff the file,
    grep will read it), not correctness.

    **THE ASYMMETRY WORTH CARRYING: JAVASCRIPT HAS NO SUCH RULE.** A NUL in
    a `.js` file parses, runs, and silently makes the file undiffable —
    which is precisely how #1877 shipped two of them. A source-level guard
    is owed where the language does not provide one, and it is not owed
    here. That is the argument for scoping the perch guard to `perch/`.
    """
    for where, source in (
        ("string literal", 'x = "a' + NUL + 'b"\n'),
        ("comment", "# a" + NUL + "b\nx = 1\n"),
        ("docstring", '"""a' + NUL + 'b"""\nx = 1\n'),
    ):
        with pytest.raises(SyntaxError):
            compile(source, "<probe>", "exec")
            pytest.fail(f"python compiled a NUL in a {where}")

    import korax.validate as module

    assert module.NUL == chr(0)
