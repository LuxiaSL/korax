"""`korax invite` and `korax enlist --invite` — JOB #1839.

The CLI's half of the bootstrap. The load-bearing case is the LAST one:
enlist invoked with NO token in the environment at all, which is the
state of the machine this whole feature exists for.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from korax_cli.cli import CliError, _parse_duration

from conftest import Invoke


def _mint_invite(cli: Invoke, world: dict[str, Any]) -> str:
    """Harvest an invite, FAILING HERE if the mint did not produce one.

    The CI failure this guards (run 31557281367) was not the mint
    breaking — it was a test that harvested an unusable token and built
    `--invite <bad>` out of it, so the error surfaced as argparse
    complaining about the flag two calls later. A harvest that cannot
    fail at the harvest turns every upstream break into a puzzle.
    """
    r = cli("invite", token=world["op_token"])
    assert r.exit_code == 0, f"mint failed: {r.stderr}"
    token = r.json["invite"]
    assert token, "mint returned an empty invite"
    assert not token.startswith("-"), (
        f"invite token leads with '-' ({token[:8]}...): argparse will read it "
        "as an option, not a value"
    )
    return token


# -- the duration parser --------------------------------------------------


@pytest.mark.parametrize(
    "text,seconds",
    [("45s", 45), ("30m", 1800), ("2h", 7200), ("7d", 604800), ("90", 90)],
)
def test_durations_parse(text: str, seconds: int) -> None:
    assert _parse_duration(text) == seconds


@pytest.mark.parametrize("bad", ["", "  ", "abc", "1w", "-5m", "0", "0h", "1.5h"])
def test_bad_durations_refuse_rather_than_guess(bad: str) -> None:
    """An expiry is a security parameter: a typo read as "3 seconds" and
    a typo read as "3 days" are the same mistake pointing opposite ways,
    so neither may be guessed at."""
    with pytest.raises(CliError):
        _parse_duration(bad)


# -- minting -------------------------------------------------------------


def test_operator_mints_an_invite(cli: Invoke, world: dict[str, Any]) -> None:
    r = cli("invite", token=world["op_token"])
    assert r.exit_code == 0, r.stderr
    body = r.json
    assert body["invite"]
    assert body["uses"] == 1
    assert "--invite" in body["next"]  # the message hands over the next step


def test_invite_honours_uses_and_expires(cli: Invoke, world: dict[str, Any]) -> None:
    r = cli("invite", "--uses", "3", "--expires", "30m", token=world["op_token"])
    assert r.exit_code == 0, r.stderr
    assert r.json["uses"] == 3


def test_a_non_human_band_is_refused_by_the_board(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """Client-side there is no gate at all, deliberately — the server's
    403 is the boundary, and a second check here would be a second
    source of truth for §3.4."""
    mint = cli("identity", "new", "ordinary", token=world["op_token"])
    ordinary_token = mint.json["token"]

    r = cli("invite", token=ordinary_token)
    assert r.exit_code != 0
    assert "human" in (r.stdout + r.stderr)


# -- spending, from a machine with nothing --------------------------------


def test_enlist_with_an_invite_and_no_token_at_all(
    cli: Invoke, world: dict[str, Any], tmp_path: Any
) -> None:
    """THE case. `token=None` means no KORAX_TOKEN in the environment —
    the state of a genuinely fresh host, and the one that produced the
    401 in #1837."""
    invite = _mint_invite(cli, world)

    r = cli(
        "enlist", "fresh-machine",
        "--invite", invite,
        "--dir", str(tmp_path),
    )
    assert r.exit_code == 0, r.stderr
    body = r.json
    assert body["id"].startswith("band:")
    assert body["token"]

    # and it wrote the project's MCP config, the half enlist always did
    written = json.loads((tmp_path / ".mcp.json").read_text())
    assert written["mcpServers"]["korax"]["env"]["KORAX_IDENTITY"] == body["id"]


def test_enlist_with_an_invite_posts_the_grant_request(
    cli: Invoke, world: dict[str, Any], tmp_path: Any
) -> None:
    """#1837's observed consequence was that an operator-side mint
    carried no --grant pairs, so no request reached the inbox. The
    invite path must restore that half, or it fixes the 401 and leaves
    the actual damage in place."""
    invite = _mint_invite(cli, world)

    r = cli(
        "enlist", "asking-bird",
        "--invite", invite,
        "--grant", "claimant:/korax-dev/**",
        "--dir", str(tmp_path),
    )
    assert r.exit_code == 0, r.stderr
    assert r.json["requested"] == ["claimant on /korax-dev/**"]
    assert r.json["request"]  # an envelope id, posted BY the new band

    read = cli("read", "--ns", "/korax/inbox", token=world["op_token"])
    payloads = [e["payload"] for e in read.json["envelopes"]]
    assert any("asking-bird" in str(p) for p in payloads)


def test_enlist_without_invite_or_token_still_401s(
    cli: Invoke, tmp_path: Any
) -> None:
    """The untouched path, asserted so a later refactor cannot quietly
    open the board: no credential and no invite is still refused."""
    r = cli("enlist", "nobody", "--dir", str(tmp_path))
    assert r.exit_code != 0
    assert "401" in (r.stdout + r.stderr) or "bearer token" in (r.stdout + r.stderr)
    assert not (tmp_path / ".mcp.json").exists(), (
        "a refused mint must not leave a config behind"
    )


def test_a_spent_invite_refuses_and_names_the_remedy(
    cli: Invoke, world: dict[str, Any], tmp_path: Any
) -> None:
    invite = _mint_invite(cli, world)
    first = cli("enlist", "first-comer", "--invite", invite, "--dir", str(tmp_path))
    assert first.exit_code == 0, first.stderr

    second = cli("enlist", "second-comer", "--invite", invite, "--dir", str(tmp_path))
    assert second.exit_code != 0
    combined = second.stdout + second.stderr
    assert "korax invite" in combined, "#415 — the error must name what to ask for"


def test_a_spent_invite_hint_does_not_contradict_its_message(
    cli: Invoke, world: dict[str, Any], tmp_path: Any
) -> None:
    """The client appends "set KORAX_TOKEN" to any unauthenticated 401.
    On the invite path that hands a fresh machine the one instruction it
    cannot follow — the dead end #1837 is about — so the hint must stay
    out of the way when the board has already named the remedy."""
    invite = _mint_invite(cli, world)
    cli("enlist", "one-and-only", "--invite", invite, "--dir", str(tmp_path))

    spent = cli("enlist", "hopeful", "--invite", invite, "--dir", str(tmp_path))
    combined = spent.stdout + spent.stderr
    assert "already been used" in combined
    assert "KORAX_TOKEN" not in combined, (
        "a fresh machine cannot set a token it does not have"
    )
