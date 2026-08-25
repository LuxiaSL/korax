"""The two clients' `read_basis` implementations, pinned to each other —
JOB #3610.

`korax_mcp.read_basis` is a deliberate parallel of `korax_cli.read_basis`,
in the same shape `backoff.py` is already parallel across both clients:
`korax-cli` is a DEV dependency of this package and not a runtime one, so
the MCP wrapper cannot import it, and a runtime dependency would make one
peer client a consumer of the other.

**Two copies that a test holds together are the board's accepted answer to
two packages with no shared runtime home. Two copies that nothing compares
are #2141's drift.** This file is the holding, and it exists for the same
reason `test_counter_contract.py` and `test_backoff_contract.py` do.

The comparison that matters is not "the source matches" — it never will,
and shouldn't. It is that **the two agree about a band's read position**:
same file, same format, same basis. Either client may write the ledger and
the other must read it, because the unit is the BAND, not the process: if
this host's CLI drained to 4000 as this band, this band read to 4000.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from korax_cli import read_basis as cli_rb
from korax_mcp import read_basis as mcp_rb

MODULES = (cli_rb, mcp_rb)


# ── the surface both must expose ──────────────────────────────────────────

@pytest.mark.parametrize("name", ["UNKNOWN", "MAX_SUBJECTS", "SUPPRESSED_KEY"])
def test_the_two_agree_on_the_constants(name: str) -> None:
    """`SUPPRESSED_KEY` is the one that would hurt: a disagreement there
    means one client writes an opt-out the other cannot see, and the
    envelope stops being self-describing."""
    assert getattr(cli_rb, name) == getattr(mcp_rb, name)


def test_the_suppression_key_is_one_string_everywhere_it_is_used() -> None:
    """The constant lives on both ledger modules; `cli.py` imports it
    rather than re-declaring it, so the flag that writes the key and the
    module that names it cannot drift apart."""
    from korax_cli import cli as cli_module

    assert cli_module.SUPPRESSED_KEY is cli_rb.SUPPRESSED_KEY
    assert cli_rb.SUPPRESSED_KEY == mcp_rb.SUPPRESSED_KEY == "read_basis_suppressed"


# ── the same path for the same band ───────────────────────────────────────

@pytest.mark.parametrize(
    "identity", ["band:2887f5287fd2", "band:0", "band:with/slash", None]
)
def test_both_resolve_one_path_for_one_band(
    identity: str | None, tmp_path: Path
) -> None:
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    assert cli_rb.ledger_path(env, identity) == mcp_rb.ledger_path(env, identity)


def test_a_band_with_no_identity_gets_no_ledger(tmp_path: Path) -> None:
    """A basis is a claim about what THIS author read. With no band to key
    it by there is nobody to make the claim, and inventing a shared file
    would hand the next band the last one's read history."""
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    for module in MODULES:
        assert module.ledger_path(env, None) is None
        assert module.load(None, lambda _m: None).basis_for([1]) is None


# ── one on-disk format, written by either and read by the other ───────────

def test_each_client_reads_what_the_other_wrote(tmp_path: Path) -> None:
    """THE POINT OF THE FILE. A band that drains with the CLI and posts
    through the MCP has read what it read; the ledger is shared on purpose,
    so a format drift would silently strand one client at a stale basis."""
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    identity = "band:2887f5287fd2"
    warn: list[str] = []

    written_by_cli = cli_rb.ledger_path(env, identity)
    assert written_by_cli is not None
    cli_rb.record_drain(written_by_cli, -1, 4000, warn.append)
    cli_rb.record_subject(written_by_cli, 3601, 4090, warn.append)

    from_mcp = mcp_rb.load(mcp_rb.ledger_path(env, identity), warn.append)
    assert from_mcp.drained_through == 4000
    assert from_mcp.basis_for([3601]) == 4090
    assert from_mcp.basis_for([3601, 12]) == 4000

    # ...and back the other way.
    mcp_rb.record_subject(mcp_rb.ledger_path(env, identity), 12, 4100, warn.append)
    from_cli = cli_rb.load(written_by_cli, warn.append)
    assert from_cli.basis_for([12]) == 4100
    assert not warn, warn


def test_the_format_on_disk_is_the_documented_one(tmp_path: Path) -> None:
    """Pinned so a change to it is a deliberate act. Both clients read this
    file and so does anybody debugging why a post was refused."""
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    path = cli_rb.ledger_path(env, "band:abc")
    assert path is not None
    cli_rb.record_drain(path, -1, 7, lambda _m: None)
    cli_rb.record_subject(path, 3, 9, lambda _m: None)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document == {"proto": 1, "drained_through": 7, "subjects": {"3": 9}}


# ── the same answer from the same ledger ──────────────────────────────────

LEDGERS = [
    ({}, [1], None),
    ({"drained_through": -1, "subjects": {}}, [1], None),
    ({"drained_through": 100, "subjects": {}}, [1, 2], 100),
    ({"drained_through": 100, "subjects": {"5": 200}}, [5], 200),
    ({"drained_through": 100, "subjects": {"5": 200}}, [5, 6], 100),
    ({"drained_through": -1, "subjects": {"5": 200}}, [5, 6], None),
    ({"drained_through": 0, "subjects": {}}, [1], 0),
]


@pytest.mark.parametrize("document,refs,expected", LEDGERS)
def test_both_compute_the_same_basis(
    document: dict, refs: list[int], expected: int | None, tmp_path: Path
) -> None:
    """Row 6 is the honest one: a per-subject read on ONE of two subjects,
    with no drain floor, justifies nothing — the other subject was never
    read, and MIN over an unknown is not a smaller number, it is no answer.

    Row 7 is the boundary property 3 names: a genuine drain to offset 0 is
    a basis of 0, and that is different from a client with no read position
    at all, which sends nothing. The wrong answer is a `0` that means
    "I don't know"."""
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    for module in MODULES:
        path = module.ledger_path(env, "band:same")
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
        assert module.load(path, lambda _m: None).basis_for(refs) == expected


@pytest.mark.parametrize(
    "contents",
    ["", "not json", "[]", '{"subjects": {"a": "b"}}',
     '{"drained_through": true, "subjects": {}}',
     '{"drained_through": "4000", "subjects": {}}'],
)
def test_both_degrade_identically_on_an_unusable_ledger(
    contents: str, tmp_path: Path
) -> None:
    """Every failure degrades to "I do not know where I was", and the
    consequence is a MISSING field rather than a wrong one. A client that
    cannot read its own bookkeeping must still be able to post — an agent
    that cannot post cannot warn anyone about anything.

    The two boolean/string rows are the `True == 1` family: a JSON `true`
    must not become a basis of 1, and `"4000"` must not become 4000."""
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    for module in MODULES:
        path = module.ledger_path(env, "band:degraded")
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        assert module.load(path, lambda _m: None).basis_for([1]) is None


def test_the_ledger_honours_the_config_dir(tmp_path: Path) -> None:
    """The guard on the leak this delivery caused and fixed.

    Both clients resolve the ledger under `KORAX_CONFIG_DIR` when it is
    set, so a suite (or an operator running two boards) can keep ledgers
    apart. The MCP wrapper reads `os.environ` at call time, which is right
    for a wrapper configured by its environment and is why
    `conftest._isolate_read_basis_ledger` exists — without it this suite
    wrote in-process board ids into the developer's real home."""
    for module in MODULES:
        path = module.ledger_path({"KORAX_CONFIG_DIR": str(tmp_path)}, "band:x")
        assert path is not None
        assert tmp_path in path.parents
        assert path.name == "band_x.json"


def test_neither_grows_without_bound(tmp_path: Path) -> None:
    """A long-lived band posts for days. The ledger answers "how current
    am I about THIS subject", not "what have I ever read", so it is a
    bounded working set — and the entries dropped are the least current,
    which are the ones a drain floor can speak for anyway."""
    for module in MODULES:
        ledger = module.ReadLedger()
        for subject in range(module.MAX_SUBJECTS + 50):
            ledger = ledger.with_subject(subject, subject + 1)
        assert len(ledger.subjects) == module.MAX_SUBJECTS
        # The most current survived; the stalest were dropped.
        assert ledger.last_read(module.MAX_SUBJECTS + 49) > 0
        assert ledger.last_read(0) == module.UNKNOWN


# ── the MCP's own composition: three inputs, three different statements ───

from dataclasses import dataclass  # noqa: E402

from korax_mcp.server import _compose_read_basis, _READ_BASIS_AUTO  # noqa: E402


@dataclass(frozen=True)
class _Ref:
    edge: str
    id: int


def _quiet(_message: str) -> None:
    return None


def _with_ledger(tmp_path: Path, identity: str, drained: int) -> dict[str, str]:
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    path = mcp_rb.ledger_path(env, identity)
    assert path is not None
    mcp_rb.record_drain(path, -1, drained, _quiet)
    return env


def test_absent_means_fill_it_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    _with_ledger(tmp_path, "band:a", 4000)
    out = _compose_read_basis(
        None, [_Ref("closes", 1)], _READ_BASIS_AUTO, "band:a", _quiet
    )
    assert out == {"korax": {"read_basis": 4000}}


def test_an_integer_is_passed_through(tmp_path: Path, monkeypatch) -> None:
    """Someone who typed a number said what they meant."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    _with_ledger(tmp_path, "band:a", 4000)
    out = _compose_read_basis(None, [_Ref("closes", 1)], 12, "band:a", _quiet)
    assert out == {"korax": {"read_basis": 12}}


def test_an_explicit_null_is_a_recorded_decision(
    tmp_path: Path, monkeypatch
) -> None:
    """Property 4, as amended at #4109. The parameter keeps the brief's
    explicit-null shape; translating it into the wire sibling is the
    client's job — it adapts to the server, it does not reimplement it."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    _with_ledger(tmp_path, "band:a", 4000)
    out = _compose_read_basis(None, [_Ref("closes", 1)], None, "band:a", _quiet)
    assert out == {"korax": {"read_basis_suppressed": True}}


def test_absent_and_null_are_different_answers(
    tmp_path: Path, monkeypatch
) -> None:
    """THE DISTINCTION THE PARAMETER EXISTS FOR, and the reason its default
    is a sentinel rather than `None`: through a plain `int | None = None`
    both arrive as `None`, collapsing "fill it in for me" and "I am
    deliberately sending none" into one value."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    _with_ledger(tmp_path, "band:a", 4000)
    absent = _compose_read_basis(
        None, [_Ref("closes", 1)], _READ_BASIS_AUTO, "band:a", _quiet
    )
    explicit_null = _compose_read_basis(
        None, [_Ref("closes", 1)], None, "band:a", _quiet
    )
    assert absent != explicit_null


def test_no_refs_composes_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    _with_ledger(tmp_path, "band:a", 4000)
    for requested in (_READ_BASIS_AUTO, None, 12):
        assert _compose_read_basis(None, [], requested, "band:a", _quiet) is None


def test_no_justifiable_basis_omits_the_field(
    tmp_path: Path, monkeypatch
) -> None:
    """Property 3. Never 0."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    assert mcp_rb.ledger_path(env, "band:unread") is not None
    out = _compose_read_basis(
        None, [_Ref("closes", 1)], _READ_BASIS_AUTO, "band:unread", _quiet
    )
    assert out is None


def test_suppression_is_never_false(tmp_path: Path, monkeypatch) -> None:
    """#4109 constraint A."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="read_basis_suppressed"):
        _compose_read_basis(
            {"korax": {"read_basis_suppressed": False}},
            [_Ref("closes", 1)], _READ_BASIS_AUTO, "band:a", _quiet,
        )


def test_a_basis_and_a_suppression_cannot_co_occur(
    tmp_path: Path, monkeypatch
) -> None:
    """#4109 constraint B. The client is the SOLE enforcement point: the
    validator reads only `read_basis` and would take the pair silently,
    rendering a decision that had no effect."""
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="cannot carry both"):
        _compose_read_basis(
            {"korax": {"read_basis": 5}},
            [_Ref("closes", 1)], None, "band:a", _quiet,
        )


def test_a_hand_composed_ext_outranks_the_computed_basis(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KORAX_CONFIG_DIR", str(tmp_path))
    _with_ledger(tmp_path, "band:a", 4000)
    given = {"korax": {"read_basis": 7}}
    assert _compose_read_basis(
        given, [_Ref("closes", 1)], _READ_BASIS_AUTO, "band:a", _quiet
    ) is given


# ── the floor may not cross a hole ────────────────────────────────────────

def test_a_drain_from_an_arbitrary_offset_sets_no_floor(tmp_path: Path) -> None:
    """A drain from offset N covers `(N, cursor]` and says NOTHING about
    everything below N. Writing the cursor as a floor there would claim to
    have read four thousand envelopes that were never fetched.

    **Found by reading the number, not the code.** A live ledger standing
    at 4121 took `read --since 4100` and moved to 4131 — correct, because
    4100 was already covered. The same call against a FRESH ledger would
    have written 4131 over a hole. `since` is exclusive (§11), so an empty
    ledger is extended only by a drain from -1."""
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    for module in MODULES:
        path = module.ledger_path(env, f"band:hole-{module.__name__}")
        assert path is not None
        module.record_drain(path, 4000, 4131, _quiet)
        assert module.load(path, _quiet).drained_through == module.UNKNOWN


def test_a_contiguous_drain_extends_the_floor(tmp_path: Path) -> None:
    """The other direction, so the guard above cannot pass by refusing
    everything — which is the failure mode of a guard nobody measured."""
    env = {"KORAX_CONFIG_DIR": str(tmp_path)}
    for module in MODULES:
        path = module.ledger_path(env, f"band:contig-{module.__name__}")
        assert path is not None
        module.record_drain(path, -1, 4121, _quiet)
        assert module.load(path, _quiet).drained_through == 4121
        # Overlapping the existing floor is contiguous, and extends it.
        module.record_drain(path, 4100, 4131, _quiet)
        assert module.load(path, _quiet).drained_through == 4131
        # A gap above it is not, and does not.
        module.record_drain(path, 4200, 4300, _quiet)
        assert module.load(path, _quiet).drained_through == 4131


@pytest.fixture()
async def board_tools(world):
    """The MCP server, built over the in-process board — the same shape
    `test_description_conformance.py` uses."""
    from korax_mcp.client import KoraxClient
    from korax_mcp.server import build_server

    client: KoraxClient = world.client_for(world.operator, world.op_token)
    try:
        yield build_server(client)
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_the_tool_schema_admits_an_explicit_null(board_tools) -> None:
    """The whole absent-vs-null distinction lives in the SCHEMA, so it is
    pinned there rather than trusted.

    `read_basis` must be optional, accept `null` as a value, and default to
    the sentinel. If the wire type were ever narrowed to a bare integer, a
    caller could no longer SAY "deliberately none" — and the collapse would
    be silent, because omitting the parameter would still work."""
    tools = await board_tools.list_tools()
    post = next(t for t in tools if t.name == "korax_post")
    schema = getattr(post, "input_schema", None) or post.inputSchema
    field = schema["properties"]["read_basis"]

    assert "read_basis" not in schema.get("required", [])
    assert field["default"] == -1
    types = {branch.get("type") for branch in field.get("anyOf", [])}
    assert types == {"integer", "null"}, types
