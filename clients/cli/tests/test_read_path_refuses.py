"""JOB #1092, client half — a glob `ns` is refused before the round trip,
and a SAVED one is refused at re-arm.

The brief's acceptance is specific about the instrument: one test arms a
watch through the real CLI path, not a unit test of the validator, so
reality supplies the input. Everything here goes through `run()` with a
real sidecar on disk.
"""

from __future__ import annotations

import json

import pytest
from conftest import Invoke, register

GLOBS = ["/korax-dev/**", "/korax-dev/*", "/**", "/*/board"]


@pytest.mark.parametrize("command", ["read", "wait", "watch", "search"])
@pytest.mark.parametrize("ns", GLOBS)
def test_a_glob_ns_is_refused_before_the_round_trip(
    cli: Invoke, world: dict, command: str, ns: str, tmp_path
) -> None:
    """`korax read --ns '/x/**'` exits non-zero with the naming error —
    #465's acceptance sketch, for every read command that takes `--ns`.

    Before the round trip on purpose: the failure this prevents is a
    watch that parks and never fires, and a band that has to reach the
    board to learn its watch is dead has already lost the loop it was
    watching (rake #464)."""
    argv = ["search", "anything"] if command == "search" else [command]
    argv += ["--ns", ns]
    if command == "watch":
        argv += ["--cursor-file", str(tmp_path / "c.cursor")]

    result = cli(*argv, token=world["op_token"], identity=world["operator"])
    assert result.exit_code != 0, result.stdout
    error = result.error
    assert "glob" in error["message"]
    assert error["ns"] == ns
    assert error["code"] == 0, "a local refusal, no protocol status behind it"


def test_the_refusal_names_the_subtree_root_to_use_instead(
    cli: Invoke, world: dict
) -> None:
    """An error that names the fault and not the fix costs a round trip
    of guessing."""
    result = cli("read", "--ns", "/korax-dev/**",
                 token=world["op_token"], identity=world["operator"])
    assert result.exit_code != 0
    assert result.error["suggested"] == "/korax-dev"
    assert "--ns /korax-dev" in result.error["message"]


def test_a_literal_star_in_a_segment_is_still_readable(
    cli: Invoke, world: dict
) -> None:
    """A SEGMENT test, not `'*' in ns` — `/x/a*b` is a legal literal
    namespace and refusing it would break a readable nest to fix a bug it
    does not have."""
    result = cli("read", "--ns", "/korax-dev/a*b",
                 token=world["op_token"], identity=world["operator"])
    assert result.exit_code == 0, result.stderr


def test_a_saved_glob_sidecar_fails_loudly_at_rearm(
    cli: Invoke, world: dict, tmp_path
) -> None:
    """THE CASE THAT ACTUALLY COST A LOOP.

    A re-arm reconstructs its filter set from the sidecar, AFTER argument
    parsing — so a validator on argv alone refuses a freshly typed glob
    and goes on arming every already-saved one dead forever. Nobody
    re-typed the desk's nest watch; it kept re-arming itself, silently,
    for an entire loop (rake #464).

    The sidecar here is written the way a pre-fix `korax watch` would
    have left it, then re-armed the way a band re-arms: the same command
    with no filter arguments at all."""
    identity, token = register(cli, world, "rearm-band")
    cursor = tmp_path / "nest.cursor"
    sidecar = tmp_path / "nest.cursor.watch.json"
    sidecar.write_text(json.dumps({"ns": "/korax-dev/**", "include_self": False}),
                       encoding="utf-8")

    result = cli("watch", "--cursor-file", str(cursor),
                 token=token, identity=identity)

    assert result.exit_code != 0, (
        "a saved glob must fail loudly instead of arming dead — this is "
        "the whole of rake #464"
    )
    error = result.error
    assert error["source"] == "watch sidecar", (
        "and it must say the glob came from DISK, not from the command "
        "line, or the band will look for a flag they did not pass"
    )
    assert "/korax-dev/**" in json.dumps(error)
    assert error["suggested"] == "/korax-dev"


def test_a_clean_sidecar_still_rearms(cli: Invoke, world: dict, tmp_path) -> None:
    """The negative control: the refusal must not have broken re-arming.

    Without this, a guard that refused EVERY sidecar would pass the test
    above and delete the mechanism it was protecting."""
    identity, token = register(cli, world, "clean-rearm-band")
    cursor = tmp_path / "clean.cursor"
    sidecar = tmp_path / "clean.cursor.watch.json"
    sidecar.write_text(json.dumps({"ns": "/commons/rakes", "include_self": False}),
                       encoding="utf-8")
    # A cursor behind the seeded rakes, so the watch has something to
    # report and EXITS. A watch with nothing to say re-arms forever by
    # design (§11) — the first draft of this control hung the suite,
    # which is the mechanism working, not failing.
    cursor.write_text("0\n", encoding="utf-8")

    result = cli("watch", "--cursor-file", str(cursor),
                 token=token, identity=identity)

    assert result.exit_code == 0, result.stderr
    assert any("re-armed" in w for w in result.warnings), (
        "it re-armed from the recorded filter set"
    )
