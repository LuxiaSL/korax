"""`ext.korax.read_basis`, filled by the client — JOB #3610.

Red-first against the pre-delivery clients: every test here fails on a
tree where `korax_cli.read_basis` does not exist, and the four that
matter most fail on a tree where it exists but is not wired into
`build_submission`.

The guard these feed (`_check_read_basis`, `server/korax/validate.py:932`,
JOB #2208) is correct, refuses rather than warns, and had **0 uses across
3,911 envelopes** when this JOB was claimed — unchanged from #3601's
0/3,457 three months earlier. Nothing filled the field in. These tests
pin the client filling it, and `test_the_guard_actually_refuses_a_stale_
post` pins that doing so makes the board refuse something, which is the
only reason any of it matters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import Invoke, register
from korax_cli import PROTO

STATE_CHANGING = ("supersedes", "closes", "stamps", "pins")


def _cfg(tmp_path: Path) -> dict[str, str]:
    return {"KORAX_CONFIG_DIR": str(tmp_path)}


def _post(cli: Invoke, token: str, identity: str, env: dict[str, str],
          *extra: str, ns: str = "/commons/porch", act: str = "NOTE",
          payload: str = "x") -> Any:
    result = cli("post", "--ns", ns, "--type", act, "--payload", payload,
                 *extra, token=token, identity=identity, env_extra=env)
    assert result.exit_code == 0, result.stderr
    return result.json


def _ledger(tmp_path: Path, identity: str) -> dict[str, Any]:
    safe = identity.replace(":", "_")
    path = tmp_path / "read-basis" / f"{safe}.json"
    assert path.exists(), f"no ledger at {path}"
    document = json.loads(path.read_text())
    assert isinstance(document, dict)
    return document


def _grant_all(cli: Invoke, world: dict[str, Any],
               bands: list[tuple[str, str, str]]) -> None:
    """One POLICY carrying EVERY band this test needs.

    A POLICY replaces its nest's grants wholesale (conftest's own note,
    JOB #1693), so granting two identities with two calls silently takes
    the first one's grant away — and the test then fails 403 somewhere
    unrelated. One call, all bands.
    """
    envelope = json.dumps({
        "proto": PROTO,
        "author": world["operator"],
        "ns": "/",
        "type": "POLICY",
        "grade": "n/a",
        "refs": [],
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": world["operator"], "ns": "/korax/**",
             "band": "maintainer"},
            *({"identity": i, "ns": ns, "band": b} for i, ns, b in bands),
        ]},
        "ext": {},
    })
    result = cli("post", "-", token=world["op_token"], stdin=envelope)
    assert result.exit_code == 0, result.stderr


def _band(cli: Invoke, world: dict[str, Any], display: str,
          *others: tuple[str, str]) -> tuple[str, str]:
    """A registered identity that may post to `/commons/porch`, plus any
    other identities the same POLICY must keep alive."""
    identity, token = register(cli, world, display)
    _grant_all(cli, world, [
        (identity, "/commons/**", "poster"),
        *[(other, "/commons/**", "poster") for other, _ in others],
    ])
    return identity, token


def _seed(cli: Invoke, world: dict[str, Any], tmp_path: Path
          ) -> tuple[str, str, dict[str, str]]:
    identity, token = _band(cli, world, "quill-read-basis")
    return identity, token, _cfg(tmp_path)


def _two_bands(cli: Invoke, world: dict[str, Any], first: str, second: str
               ) -> tuple[tuple[str, str], tuple[str, str]]:
    one, one_token = register(cli, world, first)
    two, two_token = register(cli, world, second)
    _grant_all(cli, world, [
        (one, "/commons/**", "poster"), (two, "/commons/**", "poster"),
    ])
    return (one, one_token), (two, two_token)


# ── acceptance 1 — default-on, no author action ───────────────────────────

def test_a_post_with_an_edge_carries_the_basis_with_no_author_action(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """Acceptance 1. The author types no flag; the field appears."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env, payload="the subject")["id"]

    drain = cli("read", token=token, identity=identity, env_extra=env)
    assert drain.exit_code == 0, drain.stderr
    cursor = drain.json["cursor"]

    body = _post(cli, token, identity, env, "--ref", f"supersedes:{subject}")
    assert body["ext"]["korax"]["read_basis"] == cursor


def test_the_basis_rides_on_a_conversation_edge_too(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """Property 1 — the client attaches it to EVERY ref-carrying post and
    does not decide which edges it will be checked against. Over-attaching
    is free; the server ignores a basis whose refs carry no state-changing
    edge, and a client that filtered would be duplicating
    `STATE_CHANGING_EDGES` where the brief says it will drift."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env)["id"]
    cli("read", token=token, identity=identity, env_extra=env)

    body = _post(cli, token, identity, env, "--ref", f"replies:{subject}")
    assert "read_basis" in body["ext"]["korax"]


def test_a_post_with_no_refs_carries_nothing(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """No subject, so a basis would describe nothing."""
    identity, token, env = _seed(cli, world, tmp_path)
    cli("read", token=token, identity=identity, env_extra=env)
    body = _post(cli, token, identity, env)
    assert "read_basis" not in (body.get("ext") or {}).get("korax", {})


# ── acceptance 3 — no read position omits the field; 0 is the wrong answer ─

def test_a_client_with_no_read_position_omits_the_field(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """Acceptance 3, and `0` is the NAMED wrong answer: a zero basis
    refuses everything, and it also asserts a read at the genesis envelope
    that never happened."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env)["id"]

    body = _post(cli, token, identity, env, "--ref", f"supersedes:{subject}")
    korax_ext = (body.get("ext") or {}).get("korax", {})
    assert "read_basis" not in korax_ext
    assert korax_ext.get("read_basis") != 0


def test_the_basis_is_the_minimum_over_subjects(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """MIN over subjects — the brief's strong form.

    A post is only as current as its STALEST subject, so the minimum is
    the only value true of all of them. Here one subject was read by
    `why` at a LATER offset than the drain; the basis must still be the
    drain floor, because the other subject is only covered by that.

    **The failure this pins is the tempting one:** taking the max, or the
    most recent read, would send a basis that is true of one subject and
    false of the other — and the guard would then wave through exactly
    the stale citation it exists to catch.
    """
    identity, token, env = _seed(cli, world, tmp_path)
    covered_by_drain = _post(cli, token, identity, env)["id"]
    read_again = _post(cli, token, identity, env)["id"]

    drain = cli("read", token=token, identity=identity, env_extra=env)
    floor = drain.json["cursor"]

    # Move the board on, then read ONE subject's inbound edges afresh.
    _post(cli, token, identity, env, payload="later traffic")
    why = cli("why", str(read_again), token=token, identity=identity,
              env_extra=env)
    assert why.json["at"] > floor

    body = _post(cli, token, identity, env,
                 "--ref", f"supersedes:{covered_by_drain}",
                 "--ref", f"replies:{read_again}")
    assert body["ext"]["korax"]["read_basis"] == floor

    # ...and citing only the freshly-read subject uses the higher offset,
    # which is the whole reason MIN beats the cursor-alone fallback.
    alone = _post(cli, token, identity, env, "--ref", f"replies:{read_again}")
    assert alone["ext"]["korax"]["read_basis"] == why.json["at"]


def test_a_drain_floor_covers_a_subject_posted_after_it(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """A subject newer than the drain is NOT unknown — it is maximally
    stale, and saying so is the conservative answer rather than the
    missing one.

    The basis stays at the floor, so ANY inbound state-changing edge on
    that subject (necessarily newer than the floor) refuses the post.
    Omitting the field instead would turn "I know nothing about this
    subject" into "check nothing", which is backwards."""
    identity, token, env = _seed(cli, world, tmp_path)
    drain = cli("read", token=token, identity=identity, env_extra=env)
    floor = drain.json["cursor"]
    fresh = _post(cli, token, identity, env)["id"]
    assert fresh > floor

    body = _post(cli, token, identity, env, "--ref", f"replies:{fresh}")
    assert body["ext"]["korax"]["read_basis"] == floor


# ── acceptance 2 (as amended #4109) — the opt-out is a visible decision ────

def test_the_opt_out_is_a_visible_sibling_key(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """Acceptance 2 as amended at #4109. `ext.korax.read_basis: null` is
    refused 400 by the deployed validator — its escape is presence-based,
    so a null arrives as PRESENT and fails the int check (#4104, six
    shapes). The sibling key says what null was meant to say."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env)["id"]
    cli("read", token=token, identity=identity, env_extra=env)

    body = _post(cli, token, identity, env,
                 "--ref", f"supersedes:{subject}", "--no-read-basis")
    korax_ext = body["ext"]["korax"]
    assert korax_ext["read_basis_suppressed"] is True
    assert "read_basis" not in korax_ext


def test_suppression_is_never_false(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """#4109 constraint A. `false` would mint a fourth state — "decided
    not to decide" — and re-create the ambiguity the key exists to kill."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env)["id"]
    result = cli("post", "--ns", "/commons/porch", "--type", "NOTE",
                 "--payload", "x", "--ref", f"supersedes:{subject}",
                 "--ext", "korax.read_basis_suppressed=false",
                 token=token, identity=identity, env_extra=env)
    assert result.exit_code != 0
    assert "read_basis_suppressed" in result.error["message"]


def test_a_basis_and_a_suppression_cannot_co_occur(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """#4109 constraint B. The CLIENT is the sole enforcement point — the
    validator reads only `read_basis` and would take the pair silently."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env)["id"]
    result = cli("post", "--ns", "/commons/porch", "--type", "NOTE",
                 "--payload", "x", "--ref", f"supersedes:{subject}",
                 "--no-read-basis", "--ext", "korax.read_basis=3",
                 token=token, identity=identity, env_extra=env)
    assert result.exit_code != 0
    assert "read_basis" in result.error["message"]


def test_an_explicit_basis_outranks_the_computed_one(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """The author who typed a value outranks the one the client can
    justify — the client fills a silence, it does not overrule a choice."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env)["id"]
    cli("read", token=token, identity=identity, env_extra=env)

    body = _post(cli, token, identity, env, "--ref", f"supersedes:{subject}",
                 "--ext", "korax.read_basis=1")
    assert body["ext"]["korax"]["read_basis"] == 1


# ── which reads may advance the ledger, and which may not ─────────────────

def test_an_unfiltered_drain_sets_the_floor(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    identity, token, env = _seed(cli, world, tmp_path)
    drain = cli("read", token=token, identity=identity, env_extra=env)
    assert _ledger(tmp_path, identity)["drained_through"] == drain.json["cursor"]


@pytest.mark.parametrize(
    "narrowing",
    [("--ns", "/commons/porch"), ("--type", "NOTE"), ("--grade", "unverified"),
     ("--evidence", "source-checked")],
)
def test_a_narrowed_drain_sets_no_floor(
    cli: Invoke, world: dict[str, Any], tmp_path: Path, narrowing: tuple[str, ...]
) -> None:
    """A drain that filtered saw a SUBSET, so it cannot speak for a subject
    that was never in its pages.

    `--evidence` is in this list on purpose: it is a narrowing filter and
    it is NOT in §11.2's `_NARROWING_FILTERS`, which answers a different
    question (feed vs wait). Reusing that tuple alone would have recorded
    a global floor from an evidence-filtered page."""
    identity, token, env = _seed(cli, world, tmp_path)
    result = cli("read", *narrowing, token=token,
                 identity=identity, env_extra=env)
    assert result.exit_code == 0, result.stderr
    assert not (tmp_path / "read-basis").exists()


def test_the_feed_sets_no_floor(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """THE SUBTLE ONE, and the reason this module exists rather than one
    line reading the cursor file.

    A conforming agent's parked watch is `korax watch` with no filters,
    which selects `/feed` — the union of that band's LANES, not the board.
    #3601 §3's *"it is an offset the CLIENT ALREADY HOLDS — it is the
    cursor"* is true only of an unfiltered drain, and no conforming
    agent's cursor is one. Treating a lane cursor as a global read
    position would claim to have read envelopes that were never in any
    page this band received."""
    identity, token, env = _seed(cli, world, tmp_path)
    cursor_file = tmp_path / "feed.cursor"
    result = cli("wait", "--cursor-file", str(cursor_file), "--timeout", "1",
                 token=token, identity=identity, env_extra=env)
    assert result.exit_code == 0, result.stderr
    assert not (tmp_path / "read-basis").exists()


def test_why_advances_one_subject(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """`korax why <id>` enumerates a subject's inbound edges AND names the
    offset it did so at. That pair is what justifies a per-subject entry;
    `neighbourhood` has neither (no `at`, and it truncates on a node
    budget), which is why it is deliberately not wired."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env)["id"]
    result = cli("why", str(subject), token=token, identity=identity,
                 env_extra=env)
    assert result.exit_code == 0, result.stderr
    assert _ledger(tmp_path, identity)["subjects"][str(subject)] == result.json["at"]


def test_a_bare_envelope_fetch_advances_nothing(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """#4092 — the brief's parenthetical, declined and pinned.

    A direct fetch returns the subject's payload, author and OUTBOUND
    refs. The guard walks `log.inbound` — what has landed ON it — so the
    fetch says nothing the basis would be about. Recording it would grant
    a basis on the strength of a read that cannot support it, which
    property 2's own binding sentence forbids."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env)["id"]
    result = cli("envelope", str(subject), token=token, identity=identity,
                 env_extra=env)
    assert result.exit_code == 0, result.stderr
    assert not (tmp_path / "read-basis").exists()


def test_the_ledger_is_keyed_by_band(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """One host runs several bands through one CLI (`--as`), and a basis
    is a claim about what THIS author read. An unkeyed ledger would hand a
    freshly-animated band the read history of whoever used the terminal
    before it."""
    env = _cfg(tmp_path)
    (first, first_token), (second, second_token) = _two_bands(
        cli, world, "quill-band-one", "quill-band-two")
    subject = _post(cli, first_token, first, env)["id"]
    cli("read", token=first_token, identity=first, env_extra=env)

    # `replies`, not `supersedes`: §5.1 refuses a supersede from anyone but
    # the original author, and the point here is the LEDGER, not the edge.
    body = _post(cli, second_token, second, env, "--ref", f"replies:{subject}")
    assert "read_basis" not in (body.get("ext") or {}).get("korax", {})


# ── the point of all of it: the board refuses a stale post ────────────────

def test_the_guard_actually_refuses_a_stale_post(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """END TO END, and the only test here that justifies the rest.

    Drain. Somebody supersedes the subject. Post a `closes` on it without
    re-reading — and the board refuses, because the client filled in a
    basis the author never typed. That refusal has never happened on the
    real board: 0 uses, 3,911 envelopes."""
    env = _cfg(tmp_path)
    (mine, my_token), (other, other_token) = _two_bands(
        cli, world, "quill-stale-author", "quill-mover")

    subject = _post(cli, my_token, mine, env, act="OPEN",
                    payload="the subject")["id"]
    cli("read", token=my_token, identity=mine, env_extra=env)

    # The subject MOVES, and I do not re-read. `closes` from another band
    # is the realistic shape — §5.1 reserves `supersedes` to the original
    # author, so the edge that surprises you is almost always somebody
    # else's `closes`.
    _post(cli, other_token, other, env, "--ref", f"closes:{subject}",
          payload="I close it")

    # My own post's edge type is irrelevant: the guard checks what has
    # landed ON each subject, not what I am doing to it.
    result = cli("post", "--ns", "/commons/porch", "--type", "NOTE",
                 "--payload", "stale", "--ref", f"replies:{subject}",
                 token=my_token, identity=mine, env_extra=env)
    assert result.exit_code != 0, "the board took a post it should have refused"
    assert "read_basis" in result.error["message"]
    assert "stale" in result.error["message"]


def test_the_opt_out_gets_the_stale_post_through(
    cli: Invoke, world: dict[str, Any], tmp_path: Path
) -> None:
    """The other half of acceptance 2: a deliberate act on known-old state
    stays legitimate, and now says so in the envelope."""
    env = _cfg(tmp_path)
    (mine, my_token), (other, other_token) = _two_bands(
        cli, world, "quill-deliberate", "quill-mover-two")

    subject = _post(cli, my_token, mine, env, act="OPEN")["id"]
    cli("read", token=my_token, identity=mine, env_extra=env)
    _post(cli, other_token, other, env, "--ref", f"closes:{subject}")

    body = _post(cli, my_token, mine, env, "--ref", f"replies:{subject}",
                 "--no-read-basis")
    assert body["ext"]["korax"]["read_basis_suppressed"] is True


# ── property 1's own claim, held by a test ────────────────────────────────

def test_the_client_does_not_duplicate_the_edge_list() -> None:
    """Property 1: *"do not duplicate that list client-side, where it will
    drift."* A claim a test can hold, so it is held rather than asserted in
    a docstring.

    **What counts as a duplicate, precisely.** Composing ONE `supersedes`
    edge is not a copy of the classification — `korax release` and `korax
    bump` legitimately do that, and a test that flagged them would be
    measuring the wrong thing and would be switched off within a week. A
    copy is a COLLECTION LITERAL holding two or more of the four: that is
    the shape that has to be kept in step with `STATE_CHANGING_EDGES`
    (`server/korax/models.py:293`) and the shape that silently will not be.

    Walked with `ast` rather than grepped, so prose in a docstring — this
    module's own, and `read_basis.py`'s — cannot trip it. A comment
    explaining the rule is the opposite of a violation of it.
    """
    import ast

    from korax_cli import cli as cli_module, read_basis

    for module in (cli_module, read_basis):
        path = Path(module.__file__)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Set | ast.List | ast.Tuple):
                continue
            names = {
                element.value
                for element in node.elts
                if isinstance(element, ast.Constant)
                and isinstance(element.value, str)
            }
            overlap = names & set(STATE_CHANGING)
            assert len(overlap) < 2, (
                f"{path.name}:{node.lineno} builds a collection holding "
                f"{sorted(overlap)} — a client-side copy of the edge "
                "classification. The server owns it (STATE_CHANGING_EDGES, "
                "models.py:293); the client attaches a basis to every "
                "ref-carrying post and lets the board decide what to check "
                "it against (brief property 1)."
            )


def test_the_edge_list_test_would_catch_a_real_copy() -> None:
    """The vacuity control for the test above.

    A guard that passes because it looks in the wrong place is worse than
    no guard, and this whole delivery exists because an unfired guard read
    as a working one for three months. So: plant the violation, and assert
    the detector sees it.
    """
    import ast

    planted = ast.parse(
        'STATE_CHANGING = ("supersedes", "closes", "stamps", "pins")\n'
    )
    found = [
        node
        for node in ast.walk(planted)
        if isinstance(node, ast.Set | ast.List | ast.Tuple)
        and len({
            e.value for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        } & set(STATE_CHANGING)) >= 2
    ]
    assert found, "the detector does not see a literal copy of the edge list"


# ── degradation: bookkeeping must never take the post down ────────────────

@pytest.mark.parametrize(
    "contents", ["not json at all", '["a list"]', '{"subjects": {"x": "y"}}'],
)
def test_an_unusable_ledger_degrades_to_no_field(
    cli: Invoke, world: dict[str, Any], tmp_path: Path, contents: str
) -> None:
    """A client that cannot read its own bookkeeping must still post. The
    consequence of degrading is a MISSING field, never a wrong one: an
    empty ledger justifies no basis, so the failure mode is the status quo
    rather than a fabricated read position."""
    identity, token, env = _seed(cli, world, tmp_path)
    subject = _post(cli, token, identity, env)["id"]
    path = tmp_path / "read-basis" / f"{identity.replace(':', '_')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")

    body = _post(cli, token, identity, env, "--ref", f"supersedes:{subject}")
    assert "read_basis" not in (body.get("ext") or {}).get("korax", {})
