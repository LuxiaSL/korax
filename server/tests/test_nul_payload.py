"""#1901/#1998 — an envelope carrying a NUL character is refused at the board.

R112 covered `payload` and named `ext` as a known and deliberate gap in the
source, because the scope was a decision to announce rather than one to make
inside a light-track fix. #1998 filed the remainder; #2027 announced it; the
`ext` half of this suite is that gap closed, and the measurement that
preceded it is worth stating because it moved the argument:

  - `ext.<project>.<field>` on 7fd7441 ACCEPTED the character, STORED it
    (`ext.quill.note == 'a\\x00b'` read straight off the log), and SERVED it
    back through `/read` with the escape present in the raw response. The
    hole was real at all three layers.
  - `ext.korax.mentions` was ALREADY closed, by JOB #1079's resolve-or-refuse:
    a band id with one appended names no band. #1998 led with mentions as the
    worst case and mentions was the one case already defended. The suite says
    so below rather than leaving the scarier version standing.


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


def test_the_board_refuses_it_in_ext_over_the_wire() -> None:
    """The #1998 half, on the write path rather than at `validate_post`.

    Same argument as its payload sibling and one addition: the ext check
    reads `raw` BEFORE `Submission.model_validate`, so it is the one place
    in this suite where the field the guard inspects and the field the rest
    of the validator uses are different objects. If /post ever handed the
    gauntlet a reshaped `ext`, every unit test above would stay green and
    this one would go red.
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

    def post(ext):
        return client.post("/post", headers=auth, json={
            "proto": PROTO, "author": operator, "ns": "/korax/meta",
            "type": "NOTE", "grade": "n/a", "refs": [], "ext": ext,
            "payload": "the payload is clean; the ext is the question.",
        })

    refused = post({"quill": {"note": f"a{NUL}b"}})
    assert refused.status_code == 400, (
        "the board accepted a NUL in ext over the wire. Measured on 7fd7441 "
        "this landed, was stored, and was served back through /read. Got "
        f"{refused.status_code}: {refused.text}"
    )
    assert "ext.quill.note" in refused.text, refused.text

    # THE CONTROL: ext is on almost every envelope this board writes, so a
    # guard misfiring here would break more than the one it fixes.
    assert post({"quill": {"note": "clean"}}).status_code == 200
    assert post({}).status_code == 200


def test_a_nul_bearing_mention_was_already_refused_by_1079() -> None:
    """THE CORRECTION TO #1998, kept executable rather than in prose.

    #1998 led with `ext.korax.mentions` as the worst case: band ids are
    COMPARED, so an invisible character would mean a mention that matches
    nothing and wakes nobody while the poster sees a well-formed envelope.
    **Measuring it showed that case was the one already defended.** JOB
    #1079 made mentions resolve-or-refuse, and an id with a NUL appended
    names no band, so the board answered 400 before this guard existed.

    Both halves are asserted because both are load-bearing: that the case
    is refused AT ALL (the pre-existing defence, which must not regress),
    and that the NUL guard now speaks first (the character is the actual
    cause, and #1079's message would send the author looking for a band).
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

    # A REAL band, so the refusal is about the character and not about the
    # band being fictional — the whole point of the finding.
    other = client.post("/identity", json={"display": "mention-target"},
                        headers=auth).json()

    def post(mention):
        return client.post("/post", headers=auth, json={
            "proto": PROTO, "author": operator, "ns": "/korax/meta",
            "type": "NOTE", "grade": "n/a", "refs": [],
            "ext": {"korax": {"mentions": [mention]}},
            "payload": "who does this reach?",
        })

    refused = post(other["id"] + NUL)
    assert refused.status_code == 400, refused.text
    assert "ext.korax.mentions[0]" in refused.text, (
        "the NUL guard no longer answers first for a mention; the author is "
        f"being told to go looking for a band. Got: {refused.text}"
    )

    # THE CONTROL, and it is the one that keeps this test honest: the same
    # id without the character must be a perfectly good mention.
    assert post(other["id"]).status_code == 200


# -- `ext`, the #1998 half --------------------------------------------------

def test_a_nul_in_ext_is_refused(full_log: Log) -> None:
    """The measured hole: a project-namespaced ext field is free text on the
    same write path, and on 7fd7441 it accepted, stored and served the
    character."""
    with pytest.raises(PostError) as excinfo:
        _post(full_log, _warn(full_log, pointer=POINTER, payload="clean.",
                              ext={"quill": {"note": f"a{NUL}b"}}))
    assert excinfo.value.code == 400
    assert "NUL" in excinfo.value.message


def test_a_nul_in_an_ext_key_is_refused(full_log: Log) -> None:
    with pytest.raises(PostError) as excinfo:
        _post(full_log, _warn(full_log, pointer=POINTER, payload="clean.",
                              ext={"quill": {f"no{NUL}te": "clean"}}))
    assert excinfo.value.code == 400


def test_a_nul_nested_in_an_ext_list_is_refused(full_log: Log) -> None:
    """`ext` nests as freely as a payload does, so the walk must reach the
    same depth. Asserted separately from the payload case because the two
    fields could plausibly have been given different treatments."""
    with pytest.raises(PostError) as excinfo:
        _post(full_log, _warn(full_log, pointer=POINTER, payload="clean.",
                              ext={"quill": {"xs": ["clean", f"a{NUL}b"]}}))
    assert excinfo.value.code == 400


def test_the_refusal_says_ext_and_not_payload(full_log: Log) -> None:
    """THE ONE THAT EARNS THE SHARED MESSAGE.

    Both fields refuse through one sentence, so the PATH is the whole of
    what tells the author which field to look in. If that root were wrong,
    the message would send someone hunting through a payload that is clean —
    with tools that cannot see the character in either field.
    """
    with pytest.raises(PostError) as excinfo:
        _post(full_log, _warn(full_log, pointer=POINTER, payload="clean.",
                              ext={"quill": {"xs": ["ok", f"b{NUL}"]}}))
    message = excinfo.value.message
    assert "ext.quill.xs[1]" in message, (
        f"the refusal does not locate it inside ext. Got: {message}"
    )
    assert "payload" not in message.split("(§")[0], (
        "the refusal blames the payload for an ext offence"
    )


def test_a_clean_ext_is_accepted(full_log: Log) -> None:
    """THE CONTROL FOR THE NEW HALF (#1009), and it is not the same control
    as the payload one: a guard wired to the wrong field would pass every
    payload control above while refusing every envelope that carries ext —
    which is most of them."""
    _post(full_log, _warn(full_log, pointer=POINTER, payload="an ordinary rake.",
                          ext={"quill": {"note": "clean", "xs": ["a", "b"]}}))


def test_an_absent_ext_is_not_swept_up(full_log: Log) -> None:
    """`ext` is optional and `_nul_location(None)` must read as clean, the
    same way an absent payload does. Stated as its own case because the new
    call site reaches `raw` before shape parsing has defaulted anything."""
    _post(full_log, _warn(full_log, pointer=POINTER, payload="no ext at all."))


# -- the locator, directly -------------------------------------------------

def test_the_locator_reports_a_path_and_not_merely_a_bool() -> None:
    assert _nul_location(f"a{NUL}b") == "payload"
    assert _nul_location({"a": [{"b": f"x{NUL}"}]}) == "payload.a[0].b"
    assert _nul_location({"a": "clean", "b": {"c": "also clean"}}) is None
    assert _nul_location(None) is None
    assert _nul_location(7) is None


def test_the_locator_roots_its_path_where_it_is_told() -> None:
    """The root is a parameter, not a constant, and the whole of what the
    shared refusal message says about WHICH FIELD. A default that leaked
    through would label every ext offence `payload...`."""
    assert _nul_location(f"a{NUL}b", "ext") == "ext"
    assert _nul_location({"korax": {"mentions": [f"band:x{NUL}"]}},
                         "ext") == "ext.korax.mentions[0]"
    assert _nul_location({"korax": {"mentions": ["band:x"]}}, "ext") is None


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

    assert chr(0) == module.NUL
