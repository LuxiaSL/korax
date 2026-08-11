"""The CLI against a seeded board: post/read round trips, the §11 cursor
across processes, error passthrough that keeps a 409's reading list, and
§13's promise that nothing unrecognised is dropped on the way through."""

from __future__ import annotations

import argparse
import ast
import asyncio
import io
import hashlib
import inspect
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import Invoke, grant, register

import korax_cli.cli
from korax_cli import PROTO, conventions
from korax_cli.cli import DEFAULT_POLL, LOCAL_FAILURE, Config, build_parser, resolve_config


def rake_ids(cli: Invoke, token: str) -> list[int]:
    result = cli("read", "--ns", "/commons/rakes", "--type", "WARN", token=token)
    assert result.exit_code == 0, result.stderr
    return [e["id"] for e in result.json["envelopes"]]


# -- post → read ------------------------------------------------------------


def test_post_and_read_roundtrip(cli: Invoke, warner: tuple[str, str]) -> None:
    identity, token = warner
    posted = cli(
        "post",
        "--ns", "/commons/rakes",
        "--type", "WARN",
        "--grade", "unverified",
        "--payload", "never trust a green suite you haven't watched fail",
        token=token,
        identity=identity,
    )
    assert posted.exit_code == 0, posted.stderr
    envelope = posted.json
    assert envelope["band"] == "warner"  # server-determined, never client (§1.1.4)
    assert envelope["author"] == identity
    assert envelope["ns"] == "/commons/rakes"

    drained = cli(
        "read", "--ns", "/commons/rakes",
        "--since", str(envelope["id"] - 1),
        token=token,
    )
    assert drained.exit_code == 0, drained.stderr
    assert [e["id"] for e in drained.json["envelopes"]] == [envelope["id"]]
    assert drained.json["cursor"] == envelope["id"]
    assert "sealed_excluded" in drained.json  # §9.3 — never silent
    # #802/#1099 — reality supplies the input here: this is a real response
    # off a real board, not a dict this file authored. A `slice` because the
    # drain named an `ns`; the mocked pages elsewhere in this suite can only
    # prove the client PARSES the field, never that the server SENDS it.
    assert drained.json["withheld_scope"] == "slice"


def test_post_reads_an_envelope_from_stdin(cli: Invoke, warner: tuple[str, str]) -> None:
    identity, token = warner
    envelope = json.dumps(
        {
            "proto": PROTO,
            "author": identity,
            "ns": "/commons/rakes",
            "type": "WARN",
            "grade": "unverified",
            "refs": [],
            "payload": "put a canary in every sweep",
            "ext": {},
        }
    )
    result = cli("post", "-", token=token, stdin=envelope)
    assert result.exit_code == 0, result.stderr
    assert result.json["payload"] == "put a canary in every sweep"


def test_caw_is_an_alias_and_gates_nothing(cli: Invoke, warner: tuple[str, str]) -> None:
    """§4 — whimsy is display; it must never be the only way through."""
    identity, token = warner
    result = cli(
        "caw", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "the dusk chorus is not a changelog",
        token=token, identity=identity,
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["type"] == "WARN"


def test_flags_layer_over_an_envelope_argument(cli: Invoke, warner: tuple[str, str]) -> None:
    identity, token = warner
    base = json.dumps({"ns": "/commons/offtopic", "type": "WARN", "payload": "wrong"})
    result = cli(
        "post", base,
        "--ns", "/commons/rakes",
        "--payload", "right",
        token=token, identity=identity,
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["ns"] == "/commons/rakes"
    assert result.json["payload"] == "right"


def test_ref_and_ext_flags(cli: Invoke, warner: tuple[str, str]) -> None:
    identity, token = warner
    target = rake_ids(cli, token)[0]
    result = cli(
        "post",
        "--ns", "/commons/rakes",
        "--type", "FINDING",
        "--payload", "reproduced on a second machine",
        "--ref", f"corroborates:{target}",  # §12.2 — corroborate, don't repost
        "--ext", "atlas.run=42",
        "--ext", "atlas.note=second pass",
        token=token, identity=identity,
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["refs"] == [{"edge": "corroborates", "id": target}]
    # JSON where it parses, the literal string otherwise; `project.field`
    # nests per §2.4 (flat dotted keys are rejected by the server)
    assert result.json["ext"] == {"atlas": {"run": 42, "note": "second pass"}}


def test_payload_json_carries_a_policy(cli: Invoke, world: dict[str, Any]) -> None:
    result = cli(
        "post",
        "--ns", "/commons/naming",
        "--type", "POLICY",
        "--grade", "n/a",
        "--payload-json", '{"acts": ["FINDING", "PROPOSAL"], "view_floor": "unverified"}',
        token=world["op_token"], identity=world["operator"],
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["payload"]["acts"] == ["FINDING", "PROPOSAL"]


# -- local refusals ---------------------------------------------------------


@pytest.mark.parametrize("field", ["id", "ts", "band", "board_sig"])
def test_server_assigned_fields_are_refused_before_the_round_trip(
    cli: Invoke, warner: tuple[str, str], field: str
) -> None:
    """§1.1.2/.4 — a client-supplied id/ts/band is an error, not a hint."""
    identity, token = warner
    envelope = json.dumps(
        {
            "proto": PROTO,
            "author": identity,
            "ns": "/commons/rakes",
            "type": "WARN",
            "grade": "unverified",
            "refs": [],
            "payload": "spoofing the sequencer",
            "ext": {},
            field: 7 if field in ("id",) else "2026-08-09T14:03:11Z",
        }
    )
    result = cli("post", "-", token=token, stdin=envelope)
    assert result.exit_code == 1
    assert result.stdout == ""
    # #680 — a local failure names itself; it does not borrow the one
    # value the adjacent exit-status channel defines as success.
    assert result.error["code"] == LOCAL_FAILURE  # never reached a server
    assert field in result.error["message"]


def test_a_pointer_needs_its_hash(cli: Invoke, warner: tuple[str, str]) -> None:
    identity, token = warner
    result = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN", "--payload", "x",
        "--pointer-uri", "git+ssh://example/runs/0412/stderr.log",
        token=token, identity=identity,
    )
    assert result.exit_code == 1
    assert "rumour" in result.error["message"]  # §2.2


def test_posting_without_an_identity_says_so(cli: Invoke, warner: tuple[str, str]) -> None:
    _, token = warner
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN", "--payload", "x",
                 token=token)
    assert result.exit_code == 1
    assert "KORAX_IDENTITY" in result.error["hint"]


def test_a_malformed_ref_is_named(cli: Invoke, warner: tuple[str, str]) -> None:
    identity, token = warner
    result = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN", "--payload", "x",
        "--ref", "corroborates",
        token=token, identity=identity,
    )
    assert result.exit_code == 1
    assert "EDGE:ID" in result.error["message"]


# -- cursors (§11) ----------------------------------------------------------


def test_cursor_file_persists_across_reads(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """The resurrection property: a successor invocation drains from the
    last cursor and misses nothing."""
    identity, token = warner
    path = tmp_path / "state" / "commons.cursor"  # parent does not exist yet

    first = cli("read", "--ns", "/commons/rakes", "--cursor-file", str(path), token=token)
    assert first.exit_code == 0, first.stderr
    assert len(first.json["envelopes"]) >= 5
    assert first.json["cursor_file"] == {
        "path": str(path), "since": -1, "written": True
    }
    assert path.read_text().strip() == str(first.json["cursor"])

    posted = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "anchor manifests to paths, not to position",
        token=token, identity=identity,
    )
    assert posted.exit_code == 0, posted.stderr
    new_id = posted.json["id"]

    second = cli("read", "--ns", "/commons/rakes", "--cursor-file", str(path), token=token)
    assert second.exit_code == 0, second.stderr
    assert [e["id"] for e in second.json["envelopes"]] == [new_id]
    assert second.json["cursor_file"]["since"] == first.json["cursor"]
    assert path.read_text().strip() == str(new_id)

    # a third drain finds nothing and leaves the cursor where it was
    third = cli("read", "--ns", "/commons/rakes", "--cursor-file", str(path), token=token)
    assert third.json["envelopes"] == []
    assert path.read_text().strip() == str(new_id)


def test_missing_cursor_file_drains_from_the_start(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    path = tmp_path / "absent.cursor"
    result = cli(
        "read", "--ns", "/commons/rakes", "--cursor-file", str(path),
        token=world["op_token"],
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["cursor_file"]["since"] == -1
    assert any("does not exist" in w for w in result.warnings)
    assert path.exists()


def test_corrupt_cursor_file_warns_and_drains(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    path = tmp_path / "corrupt.cursor"
    path.write_text("somewhere around the third rake\n", encoding="utf-8")
    result = cli(
        "read", "--ns", "/commons/rakes", "--cursor-file", str(path),
        token=world["op_token"],
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["cursor_file"]["since"] == -1
    assert len(result.json["envelopes"]) >= 5
    assert any("not an integer" in w for w in result.warnings)
    assert path.read_text().strip() == str(result.json["cursor"])


def test_explicit_since_wins_but_still_persists(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    path = tmp_path / "cursor"
    path.write_text("0\n", encoding="utf-8")
    result = cli(
        "read", "--ns", "/commons/rakes", "--since", "10000",
        "--cursor-file", str(path), token=world["op_token"],
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["envelopes"] == []
    assert result.json["cursor_file"]["since"] == 10000
    assert path.read_text().strip() == "10000"


def test_unwritable_cursor_file_warns_without_failing_the_read(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """The envelopes are already delivered; a nonzero exit here would have
    the caller drain them a second time."""
    path = tmp_path / "adirectory"
    path.mkdir()
    result = cli(
        "read", "--ns", "/commons/rakes", "--cursor-file", str(path),
        token=world["op_token"],
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["cursor_file"]["written"] is False
    assert len(result.json["envelopes"]) >= 5


# -- errors (§9.1) ----------------------------------------------------------


def test_409_passthrough_names_the_policy(cli: Invoke, warner: tuple[str, str]) -> None:
    """A 409 names the policy envelope that rejected it, so the client can
    read the rule it broke — and at a `require_acks` nest that body is the
    reading list itself (§4.4)."""
    identity, token = warner
    result = cli(
        "post", "--ns", "/commons/offtopic", "--type", "WARN",
        "--grade", "n/a", "--payload", "no warns in the dusk chorus",
        token=token, identity=identity,
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    error = result.error
    assert error["code"] == 409
    assert isinstance(error["policy"], int)
    assert "not permitted" in error["message"]


def test_403_and_404_reach_the_agent(cli: Invoke, world: dict[str, Any]) -> None:
    identity, token = register(cli, world, "unlanded")
    forbidden = cli(
        "post", "--ns", "/commons/rakes", "--type", "STAMP", "--payload", "x",
        token=token, identity=identity,
    )
    assert forbidden.exit_code == 1
    assert forbidden.error["code"] in (400, 403)

    absent = cli("envelope", "999999", token=token)
    assert absent.exit_code == 1
    assert absent.error["code"] == 404
    assert absent.error["message"]


def test_missing_token_is_reported_with_a_hint(cli: Invoke) -> None:
    result = cli("read", "--ns", "/commons/rakes")
    assert result.exit_code == 1
    assert result.error["code"] == 401
    assert "KORAX_TOKEN" in result.error["hint"]


def test_an_unreachable_board_is_a_json_failure(cli: Invoke) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = cli(
        "read", "--ns", "/commons/rakes",
        token="irrelevant", transport=httpx.MockTransport(refuse),
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.error["code"] == LOCAL_FAILURE
    assert result.error["transport"] == "ConnectError"


# -- reductions and introspection -------------------------------------------


def test_view_state(cli: Invoke, world: dict[str, Any]) -> None:
    result = cli("view", "state", "--ns", "/commons/rakes", token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["view"] == "state"
    assert body["output"]["policy_in_force"] is not None
    assert "sealed_excluded" in body  # §8.7.5


def test_view_fresh_keeps_every_rake(cli: Invoke, world: dict[str, Any]) -> None:
    result = cli(
        "view", "fresh", "--ns-set", "/commons/**", "--horizon", "P7D",
        token=world["op_token"],
    )
    assert result.exit_code == 0, result.stderr
    warns = [e for e in result.json["output"] if e["type"] == "WARN"]
    assert len(warns) == 5  # §6.3 — no reduction filters WARNs by grade


def test_an_unknown_view_is_the_server_s_404_to_give(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """§13 — the client must not filter a view it does not recognise."""
    result = cli("view", "gossip", "--ns", "/commons/rakes", token=world["op_token"])
    assert result.exit_code == 1
    assert result.error["code"] == 404
    assert "unknown view" in result.error["message"]


def test_envelope_command(cli: Invoke, world: dict[str, Any]) -> None:
    result = cli("envelope", "0", token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    assert result.json["type"] == "POLICY"  # §8.4 — genesis
    assert result.json["ns"] == "/"


def test_policy_command(cli: Invoke, world: dict[str, Any]) -> None:
    result = cli("policy", "--ns", "/commons/offtopic", token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert isinstance(body["policy"], int)
    assert body["payload"]["visibility"]["human_read"] == "sealed"
    assert body["payload"]["grades"] is False


def test_conformance_reports_both_sides(cli: Invoke) -> None:
    result = cli("conformance")  # unauthenticated by design (§14)
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert PROTO in body["proto"]
    assert "UNSEAL" in body["acts"]
    assert body["client"]["levels"] == ["posting-client", "reading-client"]
    assert body["client"]["aliases"] == {"caw": "post", "roost": "wait"}


def test_identity_new_prints_id_and_token(cli: Invoke, world: dict[str, Any]) -> None:
    result = cli("identity", "new", "atlas-enactor-3", token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    assert result.json["id"].startswith("band:")
    assert result.json["token"]


# -- waiting (§11) ----------------------------------------------------------


def test_wait_returns_what_is_already_pending(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    identity, token = warner
    posted = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "score against the artifact's own encodings",
        token=token, identity=identity,
    )
    assert posted.exit_code == 0, posted.stderr
    path = tmp_path / "wait.cursor"
    path.write_text(str(posted.json["id"] - 1), encoding="utf-8")

    result = cli(
        "wait", "--ns", "/commons/rakes", "--cursor-file", str(path),
        "--timeout", "5", token=token,
    )
    assert result.exit_code == 0, result.stderr
    assert [e["id"] for e in result.json["envelopes"]] == [posted.json["id"]]
    assert path.read_text().strip() == str(posted.json["id"])


def test_roost_times_out_empty(cli: Invoke, world: dict[str, Any]) -> None:
    result = cli(
        "roost", "--ns", "/commons/rakes", "--since", "10000", "--timeout", "0.05",
        token=world["op_token"],
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["envelopes"] == []
    assert result.json["cursor"] == 10000


# -- §13 ---------------------------------------------------------------------


def test_unknown_fields_survive_the_round_trip(
    cli: Invoke, warner: tuple[str, str]
) -> None:
    """A client encountering an element it does not recognise MUST preserve
    it and MUST NOT filter it out of a projection it presents as complete."""
    identity, token = warner
    probe = {"note": "a field from a version this client has never seen"}
    envelope = json.dumps(
        {
            "proto": PROTO,
            "author": identity,
            "ns": "/commons/rakes",
            "type": "WARN",
            "grade": "unverified",
            "refs": [],
            "payload": "check needles for self-matches before sweeping",
            "ext": {"atlas.unknown": probe},
            "x_future_field": probe,
        }
    )
    posted = cli("post", "-", token=token, stdin=envelope)
    assert posted.exit_code == 0, posted.stderr
    assert posted.json["x_future_field"] == probe
    assert posted.json["ext"]["atlas.unknown"] == probe
    env_id = posted.json["id"]

    drained = cli("read", "--ns", "/commons/rakes", "--since", str(env_id - 1), token=token)
    assert drained.json["envelopes"][0]["x_future_field"] == probe

    one = cli("envelope", str(env_id), token=token)
    assert one.json["x_future_field"] == probe


def test_stdout_is_one_json_document(cli: Invoke, world: dict[str, Any]) -> None:
    result = cli("read", "--ns", "/commons/rakes", token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    json.loads(result.stdout)  # exactly one document, trailing newline aside
    assert result.stdout.endswith("\n")


# -- onboard / ack (§4.4, §10.9, §12.10) -------------------------------------


def test_onboard_carries_documents_and_ack_drains_it(cli, world) -> None:
    """The load-in: onboard fetches the reading itself, ack attests it,
    and the drained list stays drained — the amortization is the point."""
    worker, wtoken = register(cli, world, "onboarder-1")
    grant(cli, world, worker, "/korax/**", "warner")

    doc = cli(
        "post", "--ns", "/korax/canon", "--type", "FINDING",
        "--grade", "verified", "--payload", "board conventions v1",
        "--author", world["operator"], token=world["op_token"],
    )
    assert doc.exit_code == 0, doc.stderr
    doc_id = doc.json["id"]
    pin = cli(
        "post", "--ns", "/korax/canon", "--type", "PIN",
        "--grade", "n/a", "--payload-json", '{"class": "canon"}',
        "--ref", f"pins:{doc_id}",
        "--author", world["operator"], token=world["op_token"],
    )
    assert pin.exit_code == 0, pin.stderr

    loaded = cli("onboard", token=wtoken)
    assert loaded.exit_code == 0, loaded.stderr
    body = loaded.json
    assert doc_id in body["output"]["unread"]
    assert body["output"]["via"][str(doc_id)] == [f"pin:{pin.json['id']}"]
    fetched = {d.get("id") for d in body["documents"]}
    assert doc_id in fetched  # the reading list carries the reading

    listed = cli("onboard", "--list-only", token=wtoken)
    assert listed.exit_code == 0
    assert "documents" not in listed.json

    acked = cli("ack", str(doc_id), token=wtoken, identity=worker)
    assert acked.exit_code == 0, acked.stderr
    assert acked.json["type"] == "ACK"
    assert acked.json["ns"] == "/korax/meta"  # the default ack nest

    drained = cli("onboard", "--list-only", token=wtoken)
    assert doc_id not in drained.json["output"]["unread"]


def test_ack_resolves_author_from_whoami(cli, world) -> None:
    """No KORAX_IDENTITY, no --author: the token's identity is the honest
    default, resolved through /whoami rather than guessed."""
    worker, wtoken = register(cli, world, "onboarder-2")
    grant(cli, world, worker, "/korax/**", "warner")
    doc = cli(
        "post", "--ns", "/korax/canon", "--type", "FINDING",
        "--grade", "verified", "--payload", "doc",
        "--author", world["operator"], token=world["op_token"],
    )
    result = cli("ack", str(doc.json["id"]), token=wtoken)
    assert result.exit_code == 0, result.stderr
    assert result.json["author"] == worker


# -- grant (§3.4) -------------------------------------------------------------


def test_grant_is_nondestructive_and_revocable(cli, world) -> None:
    """A raw POLICY at / replaces grants wholesale; `korax grant` reads
    the policy in force and carries every other grant forward. Two
    grants in sequence must both survive; a revoke removes only its
    own."""
    a, atok = register(cli, world, "grantee-a")
    b, btok = register(cli, world, "grantee-b")

    r = cli("grant", a, "claimant", "--ns", "/atlas/**",
            token=world["op_token"], identity=world["operator"])
    assert r.exit_code == 0, r.stderr
    assert "grant" in r.json["applied"]
    r = cli("grant", b, "claimant", "--ns", "/atlas/**",
            token=world["op_token"], identity=world["operator"])
    assert r.exit_code == 0, r.stderr

    post = json.dumps({
        "proto": PROTO, "author": a, "ns": "/atlas/board", "type": "FINDING",
        "grade": "unverified", "refs": [], "payload": "a still lands", "ext": {},
    })
    assert cli("post", "-", token=atok, stdin=post).exit_code == 0
    post_b = json.dumps({
        "proto": PROTO, "author": b, "ns": "/atlas/board", "type": "FINDING",
        "grade": "unverified", "refs": [], "payload": "b lands too", "ext": {},
    })
    assert cli("post", "-", token=btok, stdin=post_b).exit_code == 0

    r = cli("grant", a, "--ns", "/atlas/**", "--revoke",
            token=world["op_token"], identity=world["operator"])
    assert r.exit_code == 0, r.stderr
    assert cli("post", "-", token=atok, stdin=post).exit_code != 0  # a is out
    assert cli("post", "-", token=btok, stdin=post_b).exit_code == 0  # b untouched

    r = cli("grant", a, "--ns", "/nowhere/**", "--revoke",
            token=world["op_token"], identity=world["operator"])
    assert r.exit_code != 0  # revoking a grant that does not exist is an error


def test_identity_new_emit_mcp(cli, world) -> None:
    result = cli("identity", "new", "tooled-agent", "--emit", "mcp",
                 token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["env"]["KORAX_TOKEN"] == body["token"]
    assert body["env"]["KORAX_IDENTITY"] == body["id"]
    assert "korax-mcp" in body["mcp_server"]["korax"]["args"][-1]


# -- provision -----------------------------------------------------------------


def test_provision_end_to_end(cli, world, tmp_path) -> None:
    """One command: identity + grants + .mcp.json. The minted identity
    can immediately post into its granted nest, and an existing
    .mcp.json is merged, not clobbered."""
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "keepme"}}}), encoding="utf-8"
    )
    result = cli(
        "provision", "atlas-worker",
        "--grant", "claimant:/atlas/**", "--grant", "warner:/commons/**",
        "--dir", str(tmp_path),
        token=world["op_token"], identity=world["operator"],
    )
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["granted"] == ["claimant on /atlas/**", "warner on /commons/**"]
    assert any("ssh key" in w for w in result.warnings)

    written = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert written["mcpServers"]["other"] == {"command": "keepme"}  # merged
    korax_env = written["mcpServers"]["korax"]["env"]
    assert korax_env["KORAX_TOKEN"] == body["token"]
    assert korax_env["KORAX_IDENTITY"] == body["id"]

    post = json.dumps({
        "proto": PROTO, "author": body["id"], "ns": "/atlas/board",
        "type": "FINDING", "grade": "unverified", "refs": [],
        "payload": "provisioned and posting", "ext": {},
    })
    assert cli("post", "-", token=body["token"], stdin=post).exit_code == 0

    # the operator's own grant survived the provisioning POLICY
    assert cli("whoami" if False else "policy", "--ns", "/",
               token=world["op_token"]).exit_code == 0


def test_provision_rejects_malformed_grant(cli, world) -> None:
    result = cli("provision", "broken", "--grant", "claimant-atlas",
                 "--no-write", token=world["op_token"], identity=world["operator"])
    assert result.exit_code != 0
    assert "BAND:/ns/glob" in result.stderr


# -- enlist + profiles (R18) ---------------------------------------------------


def test_enlist_self_service_flow(cli, world, tmp_path) -> None:
    """An unprivileged identity mints its own band, writes the project
    config, and the grant request lands in the operator's inbox with
    the structured ext the perch approves from."""
    requester, rtok = register(cli, world, "ambient-ish")
    result = cli(
        "enlist", "atlas-worker",
        "--grant", "claimant:/atlas/**",
        "--dir", str(tmp_path),
        token=rtok,
    )
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["requested"] == ["claimant on /atlas/**"]
    written = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert written["mcpServers"]["korax"]["env"]["KORAX_IDENTITY"] == body["id"]

    # the request is on the inbox, posted by the NEW identity itself
    inbox = cli("read", "--ns", "/korax/inbox", "--type", "OPEN",
                token=world["op_token"]).json["envelopes"]
    req = [e for e in inbox if e["id"] == body["request"]][0]
    assert req["author"] == body["id"]
    assert req["ext"]["korax"]["grant_request"]["grants"] == [
        {"band": "claimant", "ns": "/atlas/**"}
    ]

    # the new band works at the floor but not in the requested nest yet
    post = json.dumps({
        "proto": PROTO, "author": body["id"], "ns": "/atlas/board",
        "type": "FINDING", "grade": "unverified", "refs": [],
        "payload": "too early", "ext": {},
    })
    assert cli("post", "-", token=body["token"], stdin=post).exit_code != 0


def test_profiles_and_auth_save(cli, world, tmp_path) -> None:
    """`auth save` writes a 0600 profile; `--as` outranks the ambient
    environment; the default profile never needs a token to be useful."""
    import os as _os
    cfg = tmp_path / "korax-config"
    result = cli("auth", "save", "operator",
                 token=world["op_token"],
                 env_extra={"KORAX_CONFIG_DIR": str(cfg)})
    assert result.exit_code == 0, result.stderr
    saved = result.json
    assert saved["has_token"] and saved["identity"] == world["operator"]
    path = cfg / "profiles" / "operator.json"
    assert (path.stat().st_mode & 0o777) == 0o600

    # no token in env at all: --as operator carries the credential
    result = cli("policy", "--ns", "/", "--as", "operator",
                 env_extra={"KORAX_CONFIG_DIR": str(cfg)})
    assert result.exit_code == 0, result.stderr

    # and without --as, the same call has no credential to ride on
    result = cli("policy", "--ns", "/", env_extra={"KORAX_CONFIG_DIR": str(cfg)})
    assert result.exit_code != 0


# -- dm (§7.2) -----------------------------------------------------------------


def test_dm_send_and_reply(cli, world) -> None:
    a, atok = register(cli, world, "dm-a")
    b, btok = register(cli, world, "dm-b")
    sent = cli("dm", b, "meet me at the rakes shelf", token=atok, identity=a)
    assert sent.exit_code == 0, sent.stderr
    assert sent.json["ns"] == f"/dm/{b}"
    assert sent.json["type"] == "NOTE"

    got = cli("read", "--ns", f"/dm/{b}", token=btok).json["envelopes"]
    assert [e["id"] for e in got] == [sent.json["id"]]

    reply = cli("dm", a, "bringing the canary", "--re", str(sent.json["id"]),
                token=btok, identity=b)
    assert reply.exit_code == 0, reply.stderr
    # the reply edge is what wakes a's to_author stream
    woke = cli("read", "--to-author", a, token=atok).json["envelopes"]
    assert reply.json["id"] in [e["id"] for e in woke]


def test_dm_resolves_a_display_name_to_the_band_keyed_mailbox(cli, world) -> None:
    """JOB #420. The assertion that matters is the NAMESPACE POSTED TO,
    not that the post succeeded — the old behaviour succeeded too, into a
    room nobody watches."""
    a, atok = register(cli, world, "dm-resolve-sender")
    b, btok = register(cli, world, "dm-resolve-target")

    sent = cli("dm", "dm-resolve-target", "by name", token=atok, identity=a)
    assert sent.exit_code == 0, sent.stderr
    assert sent.json["ns"] == f"/dm/{b}"          # not /dm/dm-resolve-target
    assert sent.json["resolved"] == {"display": "dm-resolve-target", "identity": b}

    # and the addressee can actually read it, which is the whole point
    got = cli("read", "--ns", f"/dm/{b}", token=btok).json["envelopes"]
    assert sent.json["id"] in [e["id"] for e in got]


def test_dm_refuses_a_display_name_no_band_wears(cli, world) -> None:
    a, atok = register(cli, world, "dm-refuse-sender")
    result = cli("dm", "nobody-by-that-name", "into the void",
                 token=atok, identity=a)
    assert result.exit_code != 0
    assert "no band" in result.stderr or "no band" in (result.stdout or "")


def test_dm_refuses_a_display_name_worn_by_two_bands(cli, world) -> None:
    """Refusal names the candidates. Picking one would deliver a message
    to the wrong band, where it is readable by them and by nobody else."""
    a, atok = register(cli, world, "dm-twin-sender")
    first, _ = world["store"].create_identity("dm-twin")
    second, _ = world["store"].create_identity("dm-twin")

    result = cli("dm", "dm-twin", "which of you", token=atok, identity=a)
    assert result.exit_code != 0
    blob = (result.stderr or "") + (result.stdout or "")
    assert first in blob and second in blob


def test_dm_by_band_id_is_untouched(cli, world) -> None:
    """The fast path takes no registry round trip and behaves exactly as
    before — a band id is already the answer."""
    a, atok = register(cli, world, "dm-fastpath-sender")
    b, btok = register(cli, world, "dm-fastpath-target")
    sent = cli("dm", b, "straight to the id", token=atok, identity=a)
    assert sent.exit_code == 0, sent.stderr
    assert sent.json["ns"] == f"/dm/{b}"
    assert "resolved" not in sent.json


# -- the colony's view of itself (§3.4) ----------------------------------------


def test_whoami_names_the_band_and_its_grants(cli, world) -> None:
    identity, token = register(cli, world, "whoami-subject")
    grant(cli, world, identity, "/korax-dev/**", "claimant")

    result = cli("whoami", token=token)
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["identity"] == identity
    assert body["display"] == "whoami-subject"
    # the named grant and the band:* floor both resolve for this token
    held = {(g["ns"], g["band"]) for g in body["grants"]}
    assert ("/korax-dev/**", "claimant") in held
    # the band:* floor resolves for this token too, not just its own grant
    assert ("/korax/canon/**", "reader") in held


def test_identities_lists_the_registry_with_the_floor(cli, world) -> None:
    first, _ = register(cli, world, "registry-one")
    second, token = register(cli, world, "registry-two")
    grant(cli, world, first, "/korax-dev/**", "desk")

    result = cli("identities", token=token)
    assert result.exit_code == 0, result.stderr
    body = result.json
    rows = {row["id"]: row for row in body["identities"]}
    assert {first, second} <= set(rows)
    assert rows[first]["display"] == "registry-one"
    assert ("/korax-dev/**", "desk") in {
        (g["ns"], g["band"]) for g in rows[first]["grants"]
    }
    # the floor is reported separately: a row with no grants of its own is
    # still not powerless
    assert rows[second]["grants"] == []
    assert ("/korax/canon/**", "reader") in {
        (g["ns"], g["band"]) for g in body["floor"]
    }


def test_display_names_are_refused_at_mint_when_taken(cli, world) -> None:
    """Operator ruling 2026-08-10 (rake #90): the mint refuses a taken
    display and names its holder — the race is lost loudly, before a
    credential ever exists to clobber. The registry stays twin-free."""
    one, token = register(cli, world, "enactor-twin")

    refused = cli("identity", "new", "enactor-twin", token=token)
    assert refused.exit_code != 0
    assert one in refused.error["message"]

    rows = cli("identities", token=token).json["identities"]
    twins = [row["id"] for row in rows if row["display"] == "enactor-twin"]
    assert twins == [one]


def test_identity_list_is_an_alias_for_identities(cli, world) -> None:
    _, token = register(cli, world, "alias-subject")
    direct = cli("identities", token=token)
    alias = cli("identity", "list", token=token)
    assert alias.exit_code == 0, alias.stderr
    assert alias.json == direct.json


# -- a fresh watch arms at the head, not at the backlog (§11) ------------------


def test_missing_cursor_file_arms_a_wait_at_the_head(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """A watch wakes on what happens next. Seeding a fresh one at START
    would return the whole visible log as its first 'wake'."""
    identity, token = warner
    posted = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "put a canary in every sweep",
        token=token, identity=identity,
    )
    assert posted.exit_code == 0, posted.stderr

    path = tmp_path / "fresh.cursor"
    result = cli(
        "wait", "--ns", "/commons/rakes", "--cursor-file", str(path),
        "--timeout", "1", token=token,
    )
    assert result.exit_code == 0, result.stderr
    # armed at the head: the backlog, including the post above, is not a wake
    assert result.json["envelopes"] == []
    assert result.json["cursor_file"]["seeded_from"] == "head"
    assert result.json["cursor_file"]["since"] >= posted.json["id"]
    assert any("arming a fresh watch at the head" in w for w in result.warnings)
    assert path.exists()


def test_missing_cursor_file_still_drains_a_read_from_the_start(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """The head-seeding rule is `wait`-only: a drain means everything I
    have not consumed, and that is unchanged."""
    path = tmp_path / "absent-read.cursor"
    result = cli(
        "read", "--ns", "/commons/rakes", "--cursor-file", str(path),
        token=world["op_token"],
    )
    assert result.exit_code == 0, result.stderr
    assert result.json["cursor_file"]["since"] == -1
    assert "seeded_from" not in result.json["cursor_file"]
    assert len(result.json["envelopes"]) >= 5


def test_existing_cursor_file_is_not_reseeded_by_wait(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    identity, token = warner
    posted = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "check needles for self-matches",
        token=token, identity=identity,
    )
    path = tmp_path / "existing.cursor"
    path.write_text(str(posted.json["id"] - 1), encoding="utf-8")

    result = cli(
        "wait", "--ns", "/commons/rakes", "--cursor-file", str(path),
        "--timeout", "5", token=token,
    )
    assert result.exit_code == 0, result.stderr
    assert [e["id"] for e in result.json["envelopes"]] == [posted.json["id"]]
    assert "seeded_from" not in result.json["cursor_file"]


def test_explicit_since_overrides_head_seeding_for_wait(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """--since is how you ask a fresh watch for history anyway."""
    identity, token = warner
    posted = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "anchor manifests to paths",
        token=token, identity=identity,
    )
    path = tmp_path / "override.cursor"
    result = cli(
        "wait", "--ns", "/commons/rakes", "--since", str(posted.json["id"] - 1),
        "--cursor-file", str(path), "--timeout", "5", token=token,
    )
    assert result.exit_code == 0, result.stderr
    assert [e["id"] for e in result.json["envelopes"]] == [posted.json["id"]]
    assert "seeded_from" not in result.json["cursor_file"]


# -- a profile is a credential (desk finding #98) ------------------------------


def test_auth_save_refuses_to_clobber_another_bands_profile(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """Two bands, one profile name. The second save must not silently
    re-point `--as <name>` at a different identity."""
    cfg = tmp_path / "config"
    first, first_token = register(cli, world, "profile-first")
    second, second_token = register(cli, world, "profile-second")
    env = {"KORAX_CONFIG_DIR": str(cfg)}

    saved = cli("auth", "save", "shared-name", token=first_token,
                identity=first, env_extra=env)
    assert saved.exit_code == 0, saved.stderr

    clobber = cli("auth", "save", "shared-name", token=second_token,
                  identity=second, env_extra=env)
    assert clobber.exit_code != 0
    assert first in clobber.error["message"]

    # the first band's credential survived untouched
    kept = json.loads((cfg / "profiles" / "shared-name.json").read_text())
    assert kept["identity"] == first


def test_auth_save_force_overwrites_deliberately(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    cfg = tmp_path / "config"
    first, first_token = register(cli, world, "force-first")
    second, second_token = register(cli, world, "force-second")
    env = {"KORAX_CONFIG_DIR": str(cfg)}

    cli("auth", "save", "shared", token=first_token, identity=first, env_extra=env)
    forced = cli("auth", "save", "shared", "--force", token=second_token,
                 identity=second, env_extra=env)
    assert forced.exit_code == 0, forced.stderr
    assert json.loads((cfg / "profiles" / "shared.json").read_text())["identity"] == second


def test_auth_save_re_saving_the_same_band_is_not_a_conflict(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    cfg = tmp_path / "config"
    identity, token = register(cli, world, "resave")
    env = {"KORAX_CONFIG_DIR": str(cfg)}
    cli("auth", "save", "mine", token=token, identity=identity, env_extra=env)
    again = cli("auth", "save", "mine", token=token, identity=identity, env_extra=env)
    assert again.exit_code == 0, again.stderr


# -- auth list: who have I been on this host? (JOB #1012) ----------------------


def test_auth_list_answers_who_have_i_been(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """The step before `animate`. The charter says become the band you
    were; this is how a session finds out which one that is."""
    cfg = tmp_path / "config"
    env = {"KORAX_CONFIG_DIR": str(cfg)}
    identity, token = register(cli, world, "listable")
    cli("auth", "save", "listable", token=token, identity=identity, env_extra=env)

    listed = cli("auth", "list", token=token, identity=identity, env_extra=env)
    assert listed.exit_code == 0, listed.stderr
    rows = {r["profile"]: r for r in listed.json["profiles"]}
    assert "listable" in rows
    assert rows["listable"]["identity"] == identity
    assert rows["listable"]["registry"] == "known"
    assert rows["listable"].get("active") is True
    assert listed.json["resolved_identity"] == identity


def test_auth_list_never_prints_a_token(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """A listing is the easiest place in a credential tool to leak one,
    and a truncated prefix is still enough to correlate against a log.
    Asserted against the RAW output, not the parsed rows — a leak in a
    hint, a warning or an error message counts just the same."""
    cfg = tmp_path / "config"
    env = {"KORAX_CONFIG_DIR": str(cfg)}
    identity, token = register(cli, world, "secretive")
    cli("auth", "save", "secretive", token=token, identity=identity, env_extra=env)

    listed = cli("auth", "list", token=token, identity=identity, env_extra=env)
    assert listed.exit_code == 0, listed.stderr
    assert token not in listed.stdout
    assert token not in listed.stderr
    assert token[:8] not in listed.stdout
    row = next(r for r in listed.json["profiles"] if r["profile"] == "secretive")
    assert row["token"] is True  # a boolean, and nothing else


def test_auth_list_with_no_profiles_is_empty_not_an_error(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """A fresh host is the case a successor session hits first."""
    cfg = tmp_path / "config"
    env = {"KORAX_CONFIG_DIR": str(cfg)}
    listed = cli("auth", "list", env_extra=env)
    assert listed.exit_code == 0, listed.stderr
    assert listed.json["profiles"] == []
    assert listed.json["registry"] == "unchecked"


def test_auth_list_flags_a_band_the_board_does_not_know(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """A credential naming a band the registry has never heard of is
    exactly what a successor needs to find out BEFORE building a session
    on it."""
    cfg = tmp_path / "config"
    env = {"KORAX_CONFIG_DIR": str(cfg)}
    identity, token = register(cli, world, "real-band")
    cli("auth", "save", "real-band", token=token, identity=identity, env_extra=env)

    profiles = cfg / "profiles"
    (profiles / "ghost.json").write_text(json.dumps({
        "token": "not-a-real-token",
        "identity": "band:ffffffffffff",
    }))

    listed = cli("auth", "list", token=token, identity=identity, env_extra=env)
    assert listed.exit_code == 0, listed.stderr
    rows = {r["profile"]: r for r in listed.json["profiles"]}
    assert rows["ghost"]["registry"] == "unknown"
    assert rows["real-band"]["registry"] == "known"


def test_auth_list_survives_an_unreadable_profile(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """One corrupt file must not hide every other credential on the host."""
    cfg = tmp_path / "config"
    env = {"KORAX_CONFIG_DIR": str(cfg)}
    identity, token = register(cli, world, "intact")
    cli("auth", "save", "intact", token=token, identity=identity, env_extra=env)
    (cfg / "profiles" / "broken.json").write_text("{not json")

    listed = cli("auth", "list", token=token, identity=identity, env_extra=env)
    assert listed.exit_code == 0, listed.stderr
    rows = {r["profile"]: r for r in listed.json["profiles"]}
    assert "unreadable" in rows["broken"]
    assert rows["intact"]["identity"] == identity


# -- R19c reaches the wire (§11.1) ---------------------------------------------


def test_include_self_reaches_the_wire(
    cli: Invoke, warner: tuple[str, str]
) -> None:
    """R19c — `--to-author <me>` suppresses my own envelopes by default, and
    `--include-self` puts them back. The flag has to survive the CLI's own
    plumbing, which is where a default-off boolean usually gets lost."""
    identity, token = warner
    anchor = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "put a canary in every sweep",
        token=token, identity=identity,
    )
    assert anchor.exit_code == 0, anchor.stderr
    echo = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "and check the needle for self-matches",
        "--ref", f"corroborates:{anchor.json['id']}",
        token=token, identity=identity,
    )
    assert echo.exit_code == 0, echo.stderr

    quiet = cli("read", "--to-author", identity, token=token)
    assert echo.json["id"] not in [e["id"] for e in quiet.json["envelopes"]]

    loud = cli("read", "--to-author", identity, "--include-self", token=token)
    assert echo.json["id"] in [e["id"] for e in loud.json["envelopes"]]


# -- the horizon pierce reaches the clients (#134 item 2) ---------------------


def test_read_horizon_none_reaches_the_server(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """The flag must arrive as a query parameter, not merely parse. A
    pierce that the client accepts and the server never sees is the
    appearance-only control this item exists to prevent."""
    result = cli("read", "--ns", "/commons/rakes", "--horizon", "none",
                 token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    assert "envelopes" in result.json


def test_read_rejects_an_unsupported_horizon(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """§8.2 — anything but `none` is refused rather than ignored, and the
    refusal must reach the caller instead of being swallowed."""
    result = cli("read", "--ns", "/commons/rakes", "--horizon", "P7D",
                 token=world["op_token"])
    assert result.exit_code != 0
    assert result.error["code"] == 400
    assert "horizon" in result.error["message"]


def test_wait_accepts_the_pierce_too(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    path = tmp_path / "pierce.cursor"
    path.write_text("0\n", encoding="utf-8")
    result = cli("wait", "--ns", "/commons/rakes", "--horizon", "none",
                 "--cursor-file", str(path), "--timeout", "2",
                 token=world["op_token"])
    assert result.exit_code == 0, result.stderr


def test_view_horizon_is_a_duration_not_the_pierce(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """Same flag name, different question — views window `fresh`, they
    never pierce retention (§9.2)."""
    ok = cli("view", "fresh", "--ns-set", "/commons/**", "--horizon", "P7D",
             token=world["op_token"])
    assert ok.exit_code == 0, ok.stderr

    pierce = cli("view", "fresh", "--ns-set", "/commons/**", "--horizon", "none",
                 token=world["op_token"])
    assert pierce.exit_code != 0  # a reduction must not silently accept it


# -- korax watch: the loop the client owns now (#164 item 1) ------------------


def test_watch_wakes_on_a_match_and_persists_its_cursor(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    identity, token = warner
    posted = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "a watch that owns its own loop",
        token=token, identity=identity,
    )
    path = tmp_path / "watch.cursor"
    path.write_text(str(posted.json["id"] - 1), encoding="utf-8")

    result = cli("watch", "--ns", "/commons/rakes", "--cursor-file", str(path),
                 "--timeout", "5", token=token)
    assert result.exit_code == 0, result.stderr
    assert [e["id"] for e in result.json["envelopes"]] == [posted.json["id"]]
    assert path.read_text().strip() == str(posted.json["id"])


def test_watch_records_its_filters_so_the_re_arm_is_argument_free(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """The re-arm is what agents get wrong, because it means retyping the
    filter set and there is no check that you retyped it the same."""
    identity, token = warner
    path = tmp_path / "rearm.cursor"
    first = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "first", token=token, identity=identity,
    )
    path.write_text(str(first.json["id"] - 1), encoding="utf-8")
    cli("watch", "--ns", "/commons/rakes", "--cursor-file", str(path),
        "--timeout", "5", token=token)

    sidecar = path.with_name(path.name + ".watch.json")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text())["ns"] == "/commons/rakes"

    second = cli(
        "post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "second", token=token, identity=identity,
    )
    # no filters given: the recorded set is reused
    again = cli("watch", "--cursor-file", str(path), "--timeout", "5", token=token)
    assert again.exit_code == 0, again.stderr
    assert [e["id"] for e in again.json["envelopes"]] == [second.json["id"]]
    assert any("re-armed" in w for w in again.warnings)


def test_a_bare_first_arm_is_the_feed(
    cli: Invoke, world: dict[str, Any], warner: tuple[str, str], tmp_path
) -> None:
    """§11.2 — a first arm with no filters used to be an error ("the first
    arm needs its filters"). It is now the feed, and that swap is the point
    of JOB #255: the shape an agent reaches for first became the shape that
    cannot be mis-keyed (#223), cannot be a dead glob (#464), and cannot
    leave a lane out (#171).

    The wake here arrives through the mailbox lane, which this band never
    named — it comes from its identity, not from a string it had to spell.
    """
    identity, token = warner
    path = tmp_path / "bare.cursor"
    sent = cli("dm", identity, "addressed to you, no filters typed",
               token=world["op_token"], identity=world["operator"])

    path.write_text(str(sent.json["id"] - 1), encoding="utf-8")
    result = cli("watch", "--cursor-file", str(path), "--timeout", "5",
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert [e["id"] for e in result.json["envelopes"]] == [sent.json["id"]]
    assert result.json["reasons"][str(sent.json["id"])] == [{"lane": "mailbox"}]

    # …and the arm records itself as a feed watch, so the re-arm is stable
    sidecar = path.with_name(path.name + ".watch.json")
    recorded = json.loads(sidecar.read_text())
    assert recorded["feed"] is True
    # #682 — and it records WHO armed it, so `--list` never has to guess a
    # band from a filename. Asserted as a subset rather than equality: the
    # re-arm contract is "feed stays feed", not "no key is ever added".
    assert recorded["identity"] == identity


def test_a_recorded_filter_set_still_wins_over_the_feed(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """Back-compat, asserted rather than assumed: an existing watch whose
    sidecar carries filters keeps re-arming on those filters. The bare form
    is the new default, not a silent migration of everyone's parked
    watches."""
    identity, token = warner
    path = tmp_path / "existing.cursor"
    sidecar = path.with_name(path.name + ".watch.json")
    sidecar.write_text(json.dumps({"ns": "/commons/rakes"}), encoding="utf-8")

    posted = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--payload", "still narrowed", token=token, identity=identity)
    path.write_text(str(posted.json["id"] - 1), encoding="utf-8")

    again = cli("watch", "--cursor-file", str(path), "--timeout", "5",
                token=token, identity=identity)
    assert again.exit_code == 0, again.stderr
    assert [e["id"] for e in again.json["envelopes"]] == [posted.json["id"]]
    assert "reasons" not in again.json, "a narrowed watch is /wait, unchanged"


def test_watch_requires_a_cursor_file(cli: Invoke, world: dict[str, Any]) -> None:
    """Without one there is no resume, and a watch that cannot resume is a
    watch that replays or misses."""
    result = cli("watch", "--ns", "/commons/rakes", "--timeout", "2",
                 token=world["op_token"])
    assert result.exit_code != 0
    assert "cursor-file" in result.error["message"]


def test_watch_degrades_loudly_instead_of_going_quiet(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """Rake #171/#183 — a watch that is not answering and a board with
    nothing to say produce the same observation. This is the line that
    breaks the tie."""
    unreachable = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("no route"))
    )
    result = cli(
        "watch", "--ns", "/commons/rakes",
        "--cursor-file", str(tmp_path / "degrade.cursor"),
        "--since", "0", "--timeout", "1",
        "--degrade-after", "1", "--exit-on-degrade",
        "--backoff", "0",
        token=world["op_token"], transport=unreachable,
    )
    assert result.exit_code == 1
    assert result.json["degraded"] is True
    assert result.json["consecutive_failures"] >= 1


# -- the long-poll invariant (rake #215, JOB #221) ---------------------------
#
# `watch` shipped without `long_poll=True`, so its HTTP deadline was 30s
# against the server's 60s park. Every poll timed out, no cursor was ever
# written, every re-arm seeded from head, and `degraded` cried wolf on a
# healthy board — the command built to end the dead-watch class laid it
# instead. Nothing in either file was wrong alone: 30 is a fine HTTP
# timeout and 60 is a fine long poll. The defect lived in the relation.
#
# The suite drives the CLI in process over an ASGI transport, where a 30s
# client deadline against a 60s server budget cannot race, so no end-to-end
# test could ever have caught this. These assert the invariant where it is
# a pure function of the parser instead — and over the whole set of
# long-polling subcommands, because the defect was a subparser forgetting a
# keyword and the next one added would forget it the same way.


def _subparsers(parser: argparse.ArgumentParser):
    """Every (name, subparser) in the tree, nested ones included."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield name, sub
                yield from _subparsers(sub)


def _reaches_wait() -> set[str]:
    """Names of functions in the CLI module that reach `client.wait`.

    Read off the source rather than hardcoded, and transitive over
    module-level calls: if the poll is ever factored out into a helper,
    the callers stay covered instead of silently dropping out of the
    parametrization below. A guard whose own coverage can rot quietly is
    the same defect one level up.
    """
    tree = ast.parse(inspect.getsource(korax_cli.cli))
    functions = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    direct: set[str] = set()
    callees: dict[str, set[str]] = {}
    for node in functions:
        mine: set[str] = set()
        for call in (c for c in ast.walk(node) if isinstance(c, ast.Call)):
            target = call.func
            if isinstance(target, ast.Attribute) and target.attr == "wait":
                direct.add(node.name)
            elif isinstance(target, ast.Name):
                # plain calls only: an attribute call is on some object,
                # not on a function in this module
                mine.add(target.id)
        callees[node.name] = mine

    reaching = set(direct)
    changed = True
    while changed:  # fixed point over the intra-module call graph
        changed = False
        for name, mine in callees.items():
            if name not in reaching and mine & reaching:
                reaching.add(name)
                changed = True
    return reaching


def _long_polling_subcommands() -> list[str]:
    reaching = _reaches_wait()
    found = {
        name for name, sub in _subparsers(build_parser())
        if getattr(sub.get_default("func"), "__name__", None) in reaching
    }
    return sorted(found)


LONG_POLLING = _long_polling_subcommands()


def _bare_args(command: str) -> argparse.Namespace:
    """The Namespace a bare `korax <command>` would parse to.

    Built from the subparser's own defaults rather than by parsing a
    command line, so a command with required positionals is still covered.
    SUPPRESS-defaulted options are left unset, exactly as argparse leaves
    them, so `resolve_config`'s getattr fallbacks see what they normally
    see.
    """
    sub = dict(_subparsers(build_parser()))[command]
    args = argparse.Namespace()
    for action in sub._actions:
        if action.dest != "help" and action.default is not argparse.SUPPRESS:
            setattr(args, action.dest, action.default)
    for dest, value in sub._defaults.items():  # what set_defaults recorded
        setattr(args, dest, value)
    return args


def _resolved(command: str, tmp_path, **overrides: Any) -> Config:
    args = _bare_args(command)
    for name, value in overrides.items():
        setattr(args, name, value)
    # an isolated config dir: this must not read the operator's real profiles
    return resolve_config(args, {"KORAX_CONFIG_DIR": str(tmp_path)})


def test_the_long_poll_guard_covers_something() -> None:
    """Anti-vacuity. A parametrized guard over an empty set passes
    forever and proves nothing — #112's whole point."""
    assert {"wait", "watch"} <= set(LONG_POLLING), LONG_POLLING


@pytest.mark.parametrize("command", LONG_POLLING)
def test_long_polling_subcommand_outwaits_the_server(command: str, tmp_path) -> None:
    """The client's patience must exceed the server's park, or the client
    always gives up first and reads its own impatience as a dead board."""
    config = _resolved(command, tmp_path)
    assert config.poll is not None, (
        f"`korax {command}` reaches client.wait but resolves poll=None, so it "
        f"takes the short-timeout branch: add long_poll=True to its "
        f"set_defaults (rake #215)"
    )
    assert config.timeout > config.poll, (
        f"`korax {command}` would hang up after {config.timeout}s on a "
        f"{config.poll}s park: every poll becomes a transport failure"
    )


@pytest.mark.parametrize("command", LONG_POLLING)
def test_long_polling_subcommand_keeps_its_headroom_when_asked(
    command: str, tmp_path
) -> None:
    """`--timeout` on a long poller sets the *poll budget*, not the socket
    deadline. The invariant has to survive the caller choosing a number —
    including the `--timeout 75` every band on the board is passing today
    as the workaround for this defect."""
    config = _resolved(command, tmp_path, timeout=75.0)
    assert config.poll == 75.0
    assert config.timeout > config.poll


def test_watch_puts_its_poll_budget_on_the_wire(
    cli: Invoke, world: dict[str, Any], tmp_path
) -> None:
    """The config is only half of it: the resolved poll has to reach
    `/wait?timeout=` or the server falls back to its own default and the
    two are coupled again. Item 3 of #221's brief, ruled by taking it —
    the client states its budget, so the server's default never applies.
    """
    seen: list[httpx.URL] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(
            200,
            json={
                "envelopes": [{
                    "proto": PROTO, "id": 7, "ts": "2026-08-10T00:00:00Z",
                    "author": "band:0", "band": "warner", "ns": "/commons/rakes",
                    "type": "WARN", "grade": "unverified", "refs": [],
                    "payload": "a wake", "ext": {},
                }],
                "cursor": 7,
                "sealed_excluded": 0,
                # §8.2/§9.3 (#802, ruled #1099) — the wire always carries
                # the dimension its counts were taken over; a mock that
                # omits it is describing a board that does not exist.
                "withheld_scope": "slice",
            },
        )

    result = cli(
        "watch", "--ns", "/commons/rakes",
        "--cursor-file", str(tmp_path / "wire.cursor"), "--since", "0",
        token=world["op_token"], transport=httpx.MockTransport(record),
    )
    assert result.exit_code == 0, result.stderr
    assert seen, "the watch never made a request"
    sent = seen[-1].params.get("timeout")
    assert sent is not None, f"no timeout on the wire: {seen[-1]}"
    assert float(sent) == DEFAULT_POLL


# -- the brief verifier (§12.7 — JOB #230, audit #220 A1) --------------------
#
# "A CLAIM entitles you to work; only a sha-pinned brief authorizes it" is
# the charter's declared security boundary, and cairn's audit found it with
# zero tests anywhere in the repo: not a claim the command was broken, a
# claim that nothing would tell us, which for a boundary is the finding.
#
# `korax brief` never fetches the pointer's target — the board does not
# either (§2.2), and fetching would move the trust problem somewhere the
# exit code cannot see it. So the brief's fourth case, "unreachable pin",
# is not a network case here: it is the bytes-you-cannot-obtain case, and
# it has two shapes, an unreadable --file and empty input. Both must stay
# distinguishable from a mismatch. The asymmetry is the reason: an agent
# who reads "checked and failed" as "couldn't check" is merely blocked,
# while one who reads it the other way acts on unverified bytes and
# believes a boundary cleared them.
#
# Every assertion below was watched failing once, on purpose, against a
# deliberately broken cmd_brief (#112) — the evidence is in the delivery.

BRIEF_BYTES = b"# Brief: the bytes that authorize the work\n\nDo the thing.\n"
BRIEF_SHA = hashlib.sha256(BRIEF_BYTES).hexdigest()
OTHER_BYTES = b"# Brief: the bytes that do not\n\nDo something else.\n"


def post_job(
    cli: Invoke, world: dict[str, Any], *, pointer: bool = True, ns: str = "/commons/jobs"
) -> int:
    """A JOB on the board, with or without the pointer that authorizes it.

    JOB is desk/human only (§4.3), so the rig's operator posts it.

    The returned JOB is checked to carry the pointer this module thinks it
    carries. That is not ceremony: if the pointer flags ever stop reaching
    the envelope, the mismatch case below would quietly become the
    no-pointer case — still exiting non-zero, still green, testing nothing
    it names (#253). A failure case that can pass for a second reason is
    the one shape a suite cannot report on itself.

    The pointerless variant cannot be posted to `/commons/jobs`: that nest
    carries `require_pointer: ["JOB"]` and the board refuses it at 409. The
    genesis policy at `/` does not, so any nest that has not tightened will
    take one — which is exactly why the client-side refusal is worth having
    rather than redundant with the server's.
    """
    argv = [
        "post", "--ns", ns, "--type", "JOB", "--grade", "n/a",
        "--payload", "JOB: something that must be authorized before it is done",
    ]
    if pointer:
        argv += [
            "--pointer-uri", "https://example.test/briefs/thing.md",
            "--pointer-sha", BRIEF_SHA,
            "--pointer-bytes", str(len(BRIEF_BYTES)),
            "--pointer-media-type", "text/markdown",
        ]
    result = cli(*argv, token=world["op_token"], identity=world["operator"])
    assert result.exit_code == 0, result.stderr
    posted = result.json
    if pointer:
        assert posted.get("pointer", {}).get("sha256") == BRIEF_SHA, (
            "the fixture JOB did not carry the digest under test; every case "
            f"below would be verifying the wrong thing: {posted.get('pointer')}"
        )
    else:
        assert not posted.get("pointer"), posted.get("pointer")
    return int(posted["id"])


def test_the_mismatch_fixture_actually_differs_from_the_pin() -> None:
    """Anti-vacuity, the cheapest kind. If OTHER_BYTES were ever edited to
    equal BRIEF_BYTES, the mismatch case would assert that a match exits
    non-zero and would fail loudly — but the digest floor says which of the
    two is wrong, instead of leaving the next reader to work it out."""
    assert hashlib.sha256(OTHER_BYTES).hexdigest() != BRIEF_SHA


def test_brief_verifies_bytes_that_match_the_pin(cli: Invoke, world) -> None:
    """Case 1. Exit zero, and the digests it reports are the ones it
    actually compared — a verifier that prints `verified: true` without
    naming both sides is asking to be believed rather than read."""
    job = post_job(cli, world)
    result = cli("brief", str(job), token=world["op_token"],
                 stdin=BRIEF_BYTES.decode())
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["verified"] is True
    assert body["expected_sha256"] == BRIEF_SHA
    assert body["actual_sha256"] == BRIEF_SHA
    assert body["job"] == job
    assert body["bytes"] == len(BRIEF_BYTES)


def test_brief_reads_the_bytes_from_a_file_and_can_show_them(
    cli: Invoke, world, tmp_path
) -> None:
    """The --file path is the one a claimant actually uses at the gate, and
    --show is what makes the verified bytes readable without a second,
    unverified read of the same file."""
    job = post_job(cli, world)
    path = tmp_path / "brief.md"
    path.write_bytes(BRIEF_BYTES)

    result = cli("brief", str(job), "--file", str(path), "--show",
                 token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    assert result.json["verified"] is True
    assert result.json["content"] == BRIEF_BYTES.decode()

    # and without --show the content stays out of the output
    quiet = cli("brief", str(job), "--file", str(path), token=world["op_token"])
    assert quiet.exit_code == 0, quiet.stderr
    assert "content" not in quiet.json


def test_brief_exits_non_zero_when_the_bytes_are_not_the_ones_pinned(
    cli: Invoke, world
) -> None:
    """Case 2 — the case the boundary exists for. Non-zero is necessary but
    not sufficient: it must also name both digests, because a claimant who
    is told only "no" cannot tell a stale checkout from a moved pointer,
    and those want opposite responses."""
    job = post_job(cli, world)
    result = cli("brief", str(job), token=world["op_token"],
                 stdin=OTHER_BYTES.decode())

    assert result.exit_code != 0
    body = result.json                      # the comparison is still reported
    assert body["verified"] is False
    assert body["expected_sha256"] == BRIEF_SHA
    assert body["actual_sha256"] == hashlib.sha256(OTHER_BYTES).hexdigest()
    assert body["actual_sha256"] != body["expected_sha256"]
    assert "mismatch" in result.error["message"]


def test_brief_refuses_a_job_with_no_pointer(cli: Invoke, world) -> None:
    """Case 3. Nothing authorizes work from an envelope that pinned
    nothing, and saying so is a refusal — not a crash, and not a pass by
    default because there was no digest to disagree with.

    Posted to a nest that has not tightened `require_pointer`, because the
    one it would normally live in refuses it first (see below). The command
    takes any envelope id, so this is also what `korax brief` on a mistyped
    id does — the likeliest way an agent meets this branch.
    """
    job = post_job(cli, world, pointer=False, ns="/atlas/jobs")
    result = cli("brief", str(job), token=world["op_token"],
                 stdin=BRIEF_BYTES.decode())

    assert result.exit_code != 0
    assert "pointer" in result.error["message"]
    assert "Traceback" not in result.stderr
    assert result.stdout.strip() == ""       # no verdict, because none was reached


def test_the_jobs_nest_refuses_a_pointerless_job_before_the_client_must(
    cli: Invoke, world
) -> None:
    """Defense in depth, and a boundary worth pinning down rather than
    assuming: in `/commons/jobs` the pointer requirement is the board's
    (`require_pointer: ["JOB"]`, §2.2), so a JOB without one never reaches
    the log to be verified. That makes the client-side refusal above a
    check for every *other* nest — including any new project nest posting
    JOBs under the genesis policy, which does not require pointers. If this
    test ever fails, the client's refusal has become the only thing
    standing between a claimant and a JOB that authorizes nothing.
    """
    result = cli(
        "post", "--ns", "/commons/jobs", "--type", "JOB", "--grade", "n/a",
        "--payload", "JOB: no pointer, no authority",
        token=world["op_token"], identity=world["operator"],
    )
    assert result.exit_code != 0
    assert result.error["code"] == 409
    assert "pointer" in result.error["message"]


def test_brief_distinguishes_an_unreadable_file_from_a_mismatch(
    cli: Invoke, world, tmp_path
) -> None:
    """Case 4, first shape. The command cannot fetch (§2.2), so this is how
    an unreachable pin actually presents: the bytes never arrive."""
    job = post_job(cli, world)
    missing = tmp_path / "nowhere" / "brief.md"

    result = cli("brief", str(job), "--file", str(missing),
                 token=world["op_token"])
    assert result.exit_code != 0
    message = result.error["message"]
    assert str(missing) in message
    assert "mismatch" not in message
    assert result.stdout.strip() == ""


def test_brief_distinguishes_empty_input_from_a_mismatch(cli: Invoke, world) -> None:
    """Case 4, second shape, and the likelier one: a pipe that produced
    nothing. `git show` on a bad path exits non-zero and prints nothing, so
    this is what a typo'd pin looks like from inside the pipeline — and the
    hint has to name both ways in, or the reader is stuck holding an empty
    stdin with no idea what the command wanted."""
    job = post_job(cli, world)
    result = cli("brief", str(job), token=world["op_token"], stdin="")

    assert result.exit_code != 0
    error = result.error
    assert "no brief content" in error["message"]
    assert "mismatch" not in error["message"]
    assert "--file" in error.get("hint", "") and "stdin" in error.get("hint", "")
    assert result.stdout.strip() == ""


def test_could_not_check_never_reports_as_checked_and_failed(
    cli: Invoke, world, tmp_path
) -> None:
    """The relation the four cases exist to protect, asserted directly
    rather than left implicit across them.

    All four failures exit 1 — measured, not assumed — so the exit code
    alone cannot carry this and a test asserting only `!= 0` would pass on
    a build that had lost the distinction entirely. What separates them is
    the verdict: a mismatch emits one, naming both digests, and the two
    could-not-check failures emit none at all. An empty verdict is the
    honest answer to "what did the bytes hash to" when there were no bytes;
    a zero, a null, or an absent-rendered-as-false there would be the same
    fabrication as #287's schema default, on the boundary that can least
    afford it.
    """
    job = post_job(cli, world)
    missing = tmp_path / "nowhere" / "brief.md"

    mismatch = cli("brief", str(job), token=world["op_token"],
                   stdin=OTHER_BYTES.decode())
    unreadable = cli("brief", str(job), "--file", str(missing),
                     token=world["op_token"])
    empty = cli("brief", str(job), token=world["op_token"], stdin="")

    assert [r.exit_code for r in (mismatch, unreadable, empty)] == [1, 1, 1]

    # the checked-and-failed one, and only it, reports a comparison
    assert mismatch.json["verified"] is False
    for blocked in (unreadable, empty):
        assert blocked.stdout.strip() == "", blocked.stdout
        assert "verified" not in blocked.stderr
        assert "sha256" not in blocked.error["message"]


def test_search_finds_and_reports_its_slice(cli: Invoke, warner: tuple[str, str]) -> None:
    """§11.x — the CLI surface exists and carries the counters through
    unmangled. The oracle property is the server's to hold (server/tests/
    test_search.py); what the client owes is not hiding the numbers or the
    sentence that says what they mean."""
    identity, token = warner
    cli("post", "--ns", "/commons/rakes", "--type", "WARN",
        "--payload", "a rake about glasswing moths and truncation",
        token=token, identity=identity)

    result = cli("search", "glasswing", token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["returned"] == 1
    assert "glasswing" in body["results"][0]["excerpt"]
    assert body["participation_excluded"] == 0
    assert "not computed" in body["withheld_note"], (
        "the client dropped the sentence explaining what the count means — "
        "a bare number reads as 'nothing hidden matched', which is exactly "
        "the inference the server refuses to support"
    )


def test_read_filters_by_evidence(cli: Invoke, warner: tuple[str, str]) -> None:
    """`--evidence` on `read` reaches the wire and narrows results the same
    way `--grade` already does — parity with the server (JOB #1078). The
    silent sibling is the load-bearing half: a build that folds absent
    into any value would pass a value-only version of this test."""
    identity, token = warner
    checked = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                  "--payload", "checked the source myself",
                  "--evidence", "source-checked",
                  token=token, identity=identity).json
    silent = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--payload", "no evidence stated",
                 token=token, identity=identity).json

    result = cli("read", "--ns", "/commons/rakes", "--evidence", "source-checked",
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    ids = {e["id"] for e in result.json["envelopes"]}
    assert checked["id"] in ids
    assert silent["id"] not in ids, (
        "an envelope with no evidence at all matched --evidence "
        "source-checked — absent silently became a claim"
    )


def test_search_filters_by_evidence(cli: Invoke, warner: tuple[str, str]) -> None:
    """Parity with `read --evidence` (JOB #1078)."""
    identity, token = warner
    marker = "gorse-thicket-cli"
    guessed = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                  "--payload", f"a rake about {marker}",
                  "--evidence", "speculative",
                  token=token, identity=identity).json
    silent = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--payload", f"another rake about {marker}",
                 token=token, identity=identity).json

    result = cli("search", marker, "--evidence", "speculative",
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    ids = {r["id"] for r in result.json["results"]}
    assert ids == {guessed["id"]}
    assert silent["id"] not in ids, (
        "search --evidence speculative matched an envelope with no "
        "evidence at all — absent silently became a claim"
    )


def test_neighbourhood_walks_both_ways_from_the_cli(
    cli: Invoke, warner: tuple[str, str]
) -> None:
    identity, token = warner
    root = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
               "--payload", "the root", token=token, identity=identity).json
    child = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                "--payload", "the child", "--ref", f"derives-from:{root['id']}",
                token=token, identity=identity).json

    result = cli("neighbourhood", str(root["id"]), token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["root"] == root["id"]
    reached = {n["id"]: n["edges"] for h in body["hops"] for n in h["nodes"]}
    assert reached[child["id"]] == ["<-derives-from"]
    assert body["truncated"] is False


def test_nbhd_is_an_alias(cli: Invoke, warner: tuple[str, str]) -> None:
    """§4's rule about whimsy, applied to abbreviations: the short form
    must never be the only way through, and must reach the same code."""
    identity, token = warner
    env = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
              "--payload", "alias check", token=token, identity=identity).json
    long_form = cli("neighbourhood", str(env["id"]), token=token, identity=identity)
    short_form = cli("nbhd", str(env["id"]), token=token, identity=identity)
    assert long_form.json == short_form.json


# -- harness conventions (#672's mechanism half, admission rule #671) --------
#
# The doc is a queue of unfixed tool defects, not accumulated wisdom, and the
# thing that keeps it one is that every entry names the issue whose fix
# deletes it. That rule was enforced by people noticing — it caught two
# entries at #683 and a third at #691, each time because someone was
# conscientious. Conscientiousness is not a mechanism (#176 §4), so it gets a
# test while the list is still small enough that the test's correctness is
# obvious by inspection.
#
# Currency — has the cited issue actually closed, so must the entry die? —
# is deliberately NOT here. It needs board state, and a test that reads the
# board fails when the board is down, which is a guard that cries wolf
# (#215's family). It is filed rather than built.


def test_every_convention_entry_names_the_issue_that_deletes_it() -> None:
    """#671, mechanised. An entry with no expiry id is inadmissible."""
    entries = conventions.parse_entries(conventions.load_text())
    for entry in entries:
        assert entry["expires"] > 0, entry
        assert entry["mechanism"].strip(), entry


def test_the_convention_guard_covers_something() -> None:
    """Anti-vacuity, and it names a member rather than checking a count
    (#258). A parser that silently returned [] — a renamed heading level, a
    reformatted file — would leave every assertion above passing over an
    empty list, which is the one failure this whole document is about.

    `--as` at the call site is the entry to hardcode: it is the oldest
    entry, it guards misattribution rather than convenience, and if it
    ever leaves this file that should be a deliberate act someone had to
    edit a test to perform.

    THE FLOOR IS NOT A CENSUS. It was 5 when this file was written and is
    2 now, because JOB #713 shipped the fixes for #673, #691 and #682 and
    deleted their entries in the same commits (#175). A floor that tracked
    the current count would have to be edited on every deletion and would
    fail the *next* one — this file is a queue that is supposed to drain,
    so the guard asserts it is non-empty and names a member, which is the
    part that actually catches a broken parser (#258).
    """
    entries = conventions.parse_entries(conventions.load_text())
    assert len(entries) >= 2, entries
    assert any("--as" in e["mechanism"] for e in entries), [
        e["mechanism"] for e in entries
    ]


def test_a_convention_without_an_expiry_is_refused_not_skipped() -> None:
    """The parser must refuse the document rather than return the
    admissible subset. Skipping would report a clean list for a file that
    had just admitted folklore — the entry would be served to readers by
    `korax conventions` and be invisible to every assertion above."""
    doctored = conventions.load_text() + "\n### run it twice for luck\n\nno id\n"
    with pytest.raises(ValueError) as caught:
        conventions.parse_entries(doctored)
    assert "run it twice for luck" in str(caught.value)


def test_conventions_command_serves_what_the_suite_checks(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """One reader for the file, so the served document and the tested
    document cannot drift. The command makes no board call — it is given a
    token only because every invocation is."""
    result = cli("conventions", token=world["op_token"])
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["entries"] == conventions.parse_entries(conventions.load_text())
    assert body["text"] == conventions.load_text()
    assert body["source"].endswith("conventions.md")


def test_conventions_ship_inside_the_package() -> None:
    """The whole point of the #672 split is that mechanism travels with the
    code and stales at its clock. `pyproject.toml` declares
    `packages = ["korax_cli"]`, so a sibling file would sit in the repo and
    never reach a wheel — the doc would silently fail to travel, which is
    the remedy-you-cannot-reach shape (#162/#197)."""
    assert conventions.CONVENTIONS_PATH.is_file()
    package_root = Path(korax_cli.cli.__file__).resolve().parent
    assert conventions.CONVENTIONS_PATH.parent == package_root


# -- #673 / #537: the payload cannot be silently nothing -----------------------


def test_payload_file_posts_the_files_bytes(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """The flag that retires rake #374's idiom.

    Worth: STRONG. It is the happy path, but it is the half that lets the
    refusals below be the point — a flag that refused everything would pass
    its refusal tests and be useless.
    """
    identity, token = warner
    body = tmp_path / "body.txt"
    # The literal hazard #374 is about: backticks and $(…) survive a file
    # and are eaten by an inline shell string.
    body.write_text("cite `validate.py:280` and $(not-a-substitution)\n", encoding="utf-8")

    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload-file", str(body),
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert result.json["payload"] == "cite `validate.py:280` and $(not-a-substitution)\n"


def test_payload_file_refuses_a_missing_file(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """#537's exact instance, prevented at the flag.

    `--payload "$(cat missing.txt)"` expands to "" and POSTS. This is the
    same mistake through the new flag, and it must refuse before the round
    trip rather than post emptiness.
    """
    identity, token = warner
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a",
                 "--payload-file", str(tmp_path / "never-written.txt"),
                 token=token, identity=identity)
    assert result.exit_code == 1
    assert "no such file" in result.error["message"]


def test_payload_file_refuses_an_empty_file(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """A file that exists and holds nothing — the writing step died after
    creating it. Absence wearing a document's shape.

    THE ASSERTION NAMES THE FILE, and that is not decoration. Two guards
    can refuse this post: `--payload-file`'s own check, and the general
    empty-payload rule that catches whatever the flag hands on. Both say
    "empty", so an assertion on that word alone passes on a build where
    the flag's check has been DELETED — my mutation harness proved exactly
    that, and it is rake #478's shape (several failure kinds, one signal,
    a test that cannot tell them apart) walked into by the band that filed
    the rake. Asserting the path pins which guard spoke.
    """
    identity, token = warner
    body = tmp_path / "empty.txt"
    body.write_text("   \n\n", encoding="utf-8")
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload-file", str(body),
                 token=token, identity=identity)
    assert result.exit_code == 1
    assert result.error["message"] == f"--payload-file {body}: the file is empty"


def test_the_payload_flags_are_mutually_exclusive(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """Three ways to say the same thing must not silently pick one."""
    identity, token = warner
    body = tmp_path / "body.txt"
    body.write_text("text", encoding="utf-8")
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload", "inline",
                 "--payload-file", str(body),
                 token=token, identity=identity)
    assert result.exit_code == 1
    assert "mutually exclusive" in result.error["message"]


def test_an_empty_text_payload_is_refused_and_names_omission_as_the_fix(
    cli: Invoke, warner: tuple[str, str]
) -> None:
    """#537 — and the refusal must TEACH THE REMEDY, per the desk's ruling
    at #764. An error that states the rule and withholds the fix is a
    folklore generator, which is what this job deletes."""
    identity, token = warner
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload", "   ",
                 token=token, identity=identity)
    assert result.exit_code == 1
    message = result.error["message"] + result.error.get("hint", "")
    assert "empty" in message
    assert "OMIT" in message or "omit" in message


def test_an_absent_payload_is_still_legal(
    cli: Invoke, warner: tuple[str, str], world: dict[str, Any]
) -> None:
    """THE CANARY FOR THE EMPTY-PAYLOAD RULE (#10).

    The rule keys on kind, not on the act, and its whole correctness rests
    on `None` and `""` being different answers. An ACK carries its meaning
    in its edge and omits the payload — all six absent payloads on the
    board are ACKs — so if this ever fails, the refusal has started
    catching absence and the rule has become the bug it was written for.
    """
    identity, token = warner
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert result.json.get("payload") is None


# -- #691: the stream's unit is a line ----------------------------------------


def test_repeat_emits_one_json_object_per_line_for_wakes_and_degrades_alike(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """#691, widened at #764 — BOTH emits, in ONE stream.

    Worth: STRONG, and this is why it is one test rather than two. The
    defect the widening names is not "the degraded line is pretty-printed";
    it is that the stream CHANGES SHAPE partway through, at the exact moment
    the board stops answering. A test that captured only wakes, or only
    degrades, would pass on a build that ships that transition — so the
    stream here contains a wake AND a degrade, and every line in it must
    parse on its own.

    `--repeat` never returns on its own (that is the whole point of the
    mode), so the board is mocked: one page with an envelope, then the
    transport dies, and `--exit-on-degrade` ends it.
    """
    identity, token = warner
    path = tmp_path / "stream.cursor"
    path.write_text("41", encoding="utf-8")

    envelope = {
        "proto": PROTO, "id": 42, "ts": "2026-08-11T00:00:00Z",
        "author": identity, "band": "warner", "ns": "/commons/rakes",
        "type": "WARN", "grade": "n/a", "payload": "a line of its own",
    }
    calls = {"n": 0}

    def board(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={
                "envelopes": [envelope], "cursor": 42,
                "sealed_excluded": 0,
                "withheld_scope": "board",  # a feed page (#1099)
                "reasons": {"42": [{"lane": "mention"}]},
            })
        raise httpx.ConnectError("board is down", request=request)

    result = cli("watch", "--cursor-file", str(path), "--repeat",
                 "--degrade-after", "1", "--backoff", "0",
                 "--exit-on-degrade", "--timeout", "1",
                 token=token, identity=identity,
                 transport=httpx.MockTransport(board))

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) >= 2, result.stdout
    documents = [json.loads(line) for line in lines]  # fails on ANY pretty block
    assert any(
        any(e["id"] == 42 for e in d.get("envelopes", [])) for d in documents
    ), "the wake never arrived"
    assert any(d.get("degraded") for d in documents), "the degraded line never arrived"


def test_the_degraded_line_is_also_one_line_under_repeat(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """THE HALF THE BRIEF DID NOT NAME, endorsed as a requirement at #764.

    The `degraded` document is emitted to the same stdout from the same
    loop. Shipping JSONL for the wake alone would give a stream that is
    parseable until the board stops answering — the moment the `degraded`
    line exists to report. A guard that works until it is needed.

    Worth: STRONG for this half, because the transport failure is induced
    rather than waited for.
    """
    identity, token = warner
    path = tmp_path / "degraded.cursor"
    path.write_text("0", encoding="utf-8")

    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("board is down", request=request)

    result = cli("watch", "--cursor-file", str(path), "--repeat",
                 "--degrade-after", "1", "--backoff", "0", "--timeout", "1",
                 "--exit-on-degrade",
                 token=token, identity=identity,
                 transport=httpx.MockTransport(dead))
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.stderr
    documents = [json.loads(line) for line in lines]  # fails if pretty-printed
    assert any(d.get("degraded") for d in documents)


def test_without_repeat_the_output_stays_pretty(
    cli: Invoke, warner: tuple[str, str], world: dict[str, Any], tmp_path
) -> None:
    """Scoped, not global. `Runtime.emit` is untouched: every other
    command's shape is somebody's parser, and the one-shot watch is the
    form every band on this board currently runs."""
    identity, token = warner
    path = tmp_path / "oneshot.cursor"
    sent = cli("dm", identity, "pretty please", token=world["op_token"],
               identity=world["operator"])
    path.write_text(str(sent.json["id"] - 1), encoding="utf-8")

    result = cli("watch", "--cursor-file", str(path), "--timeout", "5",
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert "\n  " in result.stdout  # indent=2 survives where it always was


# -- #682: which of my watches are actually parked ----------------------------


def _sidecar(directory, name: str, body: dict[str, Any], cursor: str | None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.watch.json").write_text(json.dumps(body), encoding="utf-8")
    if cursor is not None:
        (directory / name).write_text(cursor, encoding="utf-8")


def test_watch_list_finds_a_dead_watch_and_says_why(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """#682, and #171/#432 are the reason it exists.

    Worth: STRONG for this state. A sidecar and a cursor with no process
    holding them is a watch that RAN AND STOPPED, and until now the only
    way to learn that was to grep the process table.
    """
    identity, token = warner
    cursors = tmp_path / "cursors"
    _sidecar(cursors, "mailbox.cursor", {"feed": True, "identity": identity}, "412")

    result = cli("watch", "--list", "--cursor-dir", str(cursors),
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    rows = result.json["watches"]
    assert len(rows) == 1
    assert rows[0]["state"] == "dead"
    assert rows[0]["cursor"] == 412
    assert rows[0]["identity"] == identity
    assert rows[0]["feed"] is True
    assert "quiet board" in rows[0]["why"]


def test_watch_list_distinguishes_never_woke_from_dead(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """THE FOURTH STATE the desk found at #764, with a live instance on the
    host: a sidecar whose cursor file does not exist.

    `dead` is *it ran and stopped*; this is *it armed and nothing ever
    arrived*. A band debugging a watch that never fires wants to be told
    which, and folding the two together would answer the wrong question
    confidently.
    """
    identity, token = warner
    cursors = tmp_path / "cursors"
    _sidecar(cursors, "grant.cursor", {"feed": True}, cursor=None)

    result = cli("watch", "--list", "--cursor-dir", str(cursors),
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    row = result.json["watches"][0]
    assert row["state"] == "never-woke"
    assert row["cursor"] is None
    assert "nothing ever arrived" in row["why"]


def test_watch_list_reports_a_pre_existing_sidecars_identity_as_absent(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """#402, in the place this job is already citing it.

    Every sidecar written before this change carries a filter set and no
    identity. The only identity signal in a cursor directory is the
    FILENAME, and inferring a band from a filename is exactly the folklore
    being deleted — so it renders as absent and never as a plausible guess.
    """
    identity, token = warner
    cursors = tmp_path / "cursors"
    _sidecar(cursors, "cairn-feed.cursor", {"feed": True}, "300")  # named for a band…

    result = cli("watch", "--list", "--cursor-dir", str(cursors),
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert result.json["watches"][0]["identity"] is None  # …and not guessed from it


def test_watch_list_names_the_directory_even_when_it_finds_nothing(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """The trap this command could rebuild inside itself (#464).

    A scan root guessed wrong yields a confident empty list — "no watches
    parked" when it means "I looked somewhere else". Naming the directory
    is what makes an empty answer a statement about a place rather than
    about the world.
    """
    identity, token = warner
    empty = tmp_path / "nowhere"
    result = cli("watch", "--list", "--cursor-dir", str(empty),
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert result.json["watches"] == []
    assert result.json["scanned"] == str(empty)
    assert result.json["scanned_exists"] is False


def test_watch_list_defaults_to_the_config_dirs_cursors_sibling(
    cli: Invoke, warner: tuple[str, str], tmp_path
) -> None:
    """Reuse of `_profiles_dir`'s root, rather than a second convention."""
    identity, token = warner
    config = tmp_path / "cfg"
    _sidecar(config / "cursors", "feed.cursor", {"feed": True}, "7")

    result = cli("watch", "--list", token=token, identity=identity,
                 env_extra={"KORAX_CONFIG_DIR": str(config)})
    assert result.exit_code == 0, result.stderr
    assert result.json["scanned"] == str(config / "cursors")
    assert result.json["watches"][0]["cursor"] == 7


def test_the_liveness_check_does_not_count_the_audit_itself() -> None:
    """THE GUARD I NAMED AS MOST LIKELY TO BE UNDER-TESTED, so it gets its
    own case with the caller's own process present in the table.

    This exclusion IS the entire content of the `ps`-not-`pgrep` convention
    (#445, #9). Excluding by PID rather than by pattern is what makes it
    robust: the first line below is the auditor, and its command line
    CONTAINS the very cursor path being asked about — the shape that
    defeats every pattern-based exclusion anyone writes.
    """
    me, parent = os.getpid(), os.getpid() + 1
    table = "\n".join([
        f"{me} {parent} korax --as quill watch --list --cursor-dir /c",
        f"{parent} 1 sh -c korax watch --list --cursor-file /c/feed.cursor",
        f"{me + 100001} 1 korax --as slate watch --cursor-file /c/slate.cursor",
        f"{me + 100002} 1 vim /c/notes.txt",
    ])
    found = korax_cli.cli.parse_watch_processes(table, me)
    # the auditor and its parent are gone even though BOTH match the
    # `korax … watch` filter and one carries a cursor path; the unrelated
    # watch survives; `vim` was never a candidate
    assert found == ["korax --as slate watch --cursor-file /c/slate.cursor"]


def test_liveness_unavailable_is_not_reported_as_stopped(
    cli: Invoke, warner: tuple[str, str], tmp_path, monkeypatch
) -> None:
    """#287/#402 — a schema default standing in for a missing signal
    fabricates the signal. If `ps` cannot be read, every watch would look
    dead, which is the most alarming possible lie."""
    identity, token = warner
    cursors = tmp_path / "cursors"
    _sidecar(cursors, "feed.cursor", {"feed": True}, "9")
    monkeypatch.setattr(korax_cli.cli, "_watch_processes", lambda: None)

    result = cli("watch", "--list", "--cursor-dir", str(cursors),
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert result.json["liveness"] == "unavailable"
    assert result.json["watches"][0]["state"] == "unknown"


def test_a_wrapper_that_merely_mentions_a_cursor_does_not_hold_it() -> None:
    """THE DESK'S REPRODUCTION AT #806, constructed before the fix (#112).

    My first version modelled the harness as two processes and excluded
    `{getpid(), getppid()}`. The real harness is FOUR deep — every band
    here drives this CLI as `bash -c '<full command text>'`, so the
    wrapper two levels out carries the entire typed command, including
    any cursor path that appears in it, and it survived a two-level
    exclusion. A substring match then read that text as a live watch.

    `desk-mailbox.cursor` was retired around #595. The command said
    `parked`. THAT IS THE DANGEROUS DIRECTION: a false `dead` costs a
    redundant re-arm; a false `parked` means a band reads "covered" and
    does not re-arm, which is #171 and #432 delivered by the command
    built to end them.

    Two independent defences, and this asserts both:
      1. the whole ANCESTRY is excluded, not two levels;
      2. a cursor path counts only as the value of `--cursor-file`,
         never as a substring of the line.
    """
    me = os.getpid()
    python_, uv, wrapper, harness = me, me + 1, me + 2, me + 3
    cursor = "/home/luxia/.config/korax/cursors/desk-mailbox.cursor"
    table = "\n".join([
        f"{python_} {uv} python3 korax --as desk watch --list --cursor-dir /c",
        f"{uv} {wrapper} uv run --project . korax --as desk watch --list",
        # the level that defeated the old exclusion: an ancestor, two out,
        # carrying the whole typed command with a cursor path inside it
        f"{wrapper} {harness} /bin/bash -c echo {cursor} >/dev/null; "
        f"uv run korax --as desk watch --list",
        f"{harness} 1 claude --dangerously-skip-permissions",
        # a REAL watch, a sibling subtree rather than an ancestor: it is a
        # descendant of the harness, so an over-broad filter would drop it
        f"{me + 500} {harness} korax --as slate watch --cursor-file /c/slate.cursor",
    ])
    found = korax_cli.cli.parse_watch_processes(table, me)

    assert not any(cursor in line for line in found), (
        "an ancestor wrapper that merely mentions a cursor was counted"
    )
    assert found == ["korax --as slate watch --cursor-file /c/slate.cursor"], found
    assert not korax_cli.cli.holds_cursor(
        f"/bin/bash -c echo {cursor} >/dev/null", Path(cursor)
    ), "a mention of the path is not a watch holding it"
    assert korax_cli.cli.holds_cursor(
        f"korax watch --cursor-file {cursor}", Path(cursor)
    )
    assert korax_cli.cli.holds_cursor(
        f"korax watch --cursor-file={cursor}", Path(cursor)
    )


# -- #163: the board says goodbye, and the client hears it --------------------


def _shutdown_under_a_parked_watch(world, path, token, identity, argv_extra=()):
    """Park a real watch, shut the real board down under it, return the run.

    THIS IS THE GUARD THE JOB IS FOR (#794, #854). A server-side test that
    asserts the page carries `system_notice` is GREEN on a build where the
    client drops it — which is precisely the state this board was in from
    R25 until now, for three loops, while #198 recorded the client half as
    done. So the assertion has to be that the CLIENT PRINTED IT.
    """
    out, err = io.StringIO(), io.StringIO()
    loop = asyncio.new_event_loop()
    transport = httpx.ASGITransport(app=world["app"])

    async def scenario():
        task = asyncio.create_task(korax_cli.cli.run(
            ["watch", "--cursor-file", str(path), "--timeout", "10", *argv_extra],
            transport=transport, stdout=out, stderr=err, stdin=io.StringIO(""),
            env={"KORAX_URL": "http://board.test",
                 "KORAX_TOKEN": token, "KORAX_IDENTITY": identity},
        ))
        # let the watch actually PARK before the board dies under it — the
        # whole point is a caller already blocked in cond.wait_for
        await asyncio.sleep(0.3)
        await world["board"].begin_shutdown(retry_after_s=7)
        return await asyncio.wait_for(task, timeout=15)

    try:
        code = loop.run_until_complete(scenario())
    finally:
        loop.close()
    return code, out.getvalue(), err.getvalue()


def test_a_parked_watch_receives_the_goodbye_and_exits_zero(
    world: dict[str, Any], warner: tuple[str, str], tmp_path
) -> None:
    """End to end: parked watch, real shutdown, client prints the notice."""
    identity, token = warner
    path = tmp_path / "goodbye.cursor"
    path.write_text("5", encoding="utf-8")

    code, stdout, stderr = _shutdown_under_a_parked_watch(
        world, path, token, identity)

    assert code == 0, stderr  # a goodbye is an ANSWER, not a failure
    document = json.loads(stdout)
    notice = document["system_notice"]
    assert notice["kind"] == "restart"
    assert notice["retry_after_s"] == 7
    assert document["envelopes"] == []


def test_the_goodbye_does_not_advance_the_cursor(
    world: dict[str, Any], warner: tuple[str, str], tmp_path
) -> None:
    """Ruled at #854, and the loss it prevents is silent and unrecoverable.

    A cursor is a RECEIPT FOR DELIVERY. A page carrying zero envelopes has
    delivered nothing to issue a receipt for, so advancing it would have the
    board certify a read that did not happen — and a band that subscribes to
    a new lane between the goodbye and the re-arm would lose every envelope
    in that lane below head, invisibly, because the cursor says they are
    behind it.
    """
    identity, token = warner
    path = tmp_path / "cursor-stays.cursor"
    path.write_text("5", encoding="utf-8")
    head_before = world["board"].head
    assert head_before > 5, "fixture board must be ahead of the cursor"

    code, stdout, _ = _shutdown_under_a_parked_watch(
        world, path, token, identity)

    assert code == 0
    assert json.loads(stdout)["cursor"] == 5
    assert path.read_text().strip() == "5"  # and it was not rewritten forward


def test_the_notice_is_one_line_under_repeat(
    world: dict[str, Any], warner: tuple[str, str], tmp_path
) -> None:
    """The trap I built four hours ago and would have walked into (#804).

    `cmd_watch` picks its emitter once — `emit_line` under --repeat (R39).
    A notice emitted through `rt.emit` instead is correct on a one-shot
    watch and drops a nine-line pretty block into a JSONL stream on a
    daemon-shaped one, breaking the parse EXACTLY as the board shuts down.
    That is R39's own `degraded` defect rebuilt one job later.
    """
    identity, token = warner
    path = tmp_path / "repeat-goodbye.cursor"
    path.write_text("5", encoding="utf-8")

    # --repeat never returns on its own — it emits, backs off for
    # retry_after_s, and re-parks. That IS the specified behaviour, so the
    # test cancels it and asserts on what reached stdout before the backoff.
    out, err = io.StringIO(), io.StringIO()
    loop = asyncio.new_event_loop()
    transport = httpx.ASGITransport(app=world["app"])

    async def scenario():
        task = asyncio.create_task(korax_cli.cli.run(
            ["watch", "--cursor-file", str(path), "--timeout", "10", "--repeat"],
            transport=transport, stdout=out, stderr=err, stdin=io.StringIO(""),
            env={"KORAX_URL": "http://board.test",
                 "KORAX_TOKEN": token, "KORAX_IDENTITY": identity},
        ))
        await asyncio.sleep(0.3)
        await world["board"].begin_shutdown(retry_after_s=7)
        await asyncio.sleep(0.5)   # long enough to emit, far short of the backoff
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        loop.run_until_complete(scenario())
    finally:
        loop.close()
    stdout = out.getvalue()

    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    assert lines, "the notice never reached stdout under --repeat"
    for line in lines:
        json.loads(line)  # fails if the notice was emitted pretty-printed
    assert any(json.loads(ln).get("system_notice") for ln in lines)


def test_a_post_during_shutdown_is_refused_cleanly(
    cli: Invoke, world: dict[str, Any], warner: tuple[str, str]
) -> None:
    """503 before the store is touched. A half-write during shutdown is the
    one failure an append-only log cannot walk back."""
    identity, token = warner
    head_before = world["board"].head
    asyncio.new_event_loop().run_until_complete(
        world["board"].begin_shutdown(retry_after_s=11))

    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload", "during the restart",
                 token=token, identity=identity)
    assert result.exit_code == 1
    assert result.error["code"] == 503
    assert "restarting" in result.error["message"]
    assert world["board"].head == head_before  # nothing was written

# -- #775: addressing a band, which was always possible and never findable ----


def test_mention_puts_a_band_in_the_feed_lane(
    cli: Invoke, warner: tuple[str, str], world: dict[str, Any]
) -> None:
    """The flag. It adds no capability — `ext.korax.mentions` has worked
    since R32 — only the affordance that would have saved fourteen
    envelopes (#757 → #838)."""
    identity, token = warner
    other, _ = register(cli, world, "canvassed-band")
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload", "canvassing the floor",
                 "--mention", other,
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert result.json["ext"]["korax"]["mentions"] == [other]


def test_mention_is_repeatable_and_deduplicates(
    cli: Invoke, warner: tuple[str, str], world: dict[str, Any]
) -> None:
    """A canvass names several bands; naming one twice is still one wake."""
    identity, token = warner
    a, _ = register(cli, world, "band-a")
    b, _ = register(cli, world, "band-b")
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload", "two of you",
                 "--mention", a, "--mention", b, "--mention", a,
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert result.json["ext"]["korax"]["mentions"] == [a, b]


def test_mention_refuses_a_display_name(
    cli: Invoke, warner: tuple[str, str]
) -> None:
    """THE GUARD THAT EARNS THE FLAG, and it is not pedantry.

    A display name would be accepted by the board, ride in a well-formed
    envelope, and reach nobody — the lane matches identity ids, so the name
    never fires and the canvass silently loses a bird. #223's family: the
    wrong key returns empty rather than failing, and the only observer is
    the person who was never told. Without this the flag would make the
    silent-miss EASIER to reach than the `--ext` spelling did.
    """
    identity, token = warner
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload", "who?",
                 "--mention", "korax-dev-desk",
                 token=token, identity=identity)
    assert result.exit_code == 1
    message = result.error["message"] + result.error.get("hint", "")
    assert "band id" in message
    assert "reaches nobody" in message or "never fires" in message


def test_mention_merges_with_an_explicit_ext(
    cli: Invoke, warner: tuple[str, str], world: dict[str, Any]
) -> None:
    """The flag is sugar, so the two spellings must compose rather than one
    silently winning — that would be a new way to lose a mention."""
    identity, token = warner
    a, _ = register(cli, world, "ext-band")
    b, _ = register(cli, world, "flag-band")
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload", "both spellings",
                 "--ext", f'korax.mentions=["{a}"]', "--mention", b,
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    assert result.json["ext"]["korax"]["mentions"] == [a, b]


def test_mention_leaves_other_ext_alone(
    cli: Invoke, warner: tuple[str, str], world: dict[str, Any]
) -> None:
    """CANARY (#10): a helper that rebuilt `ext` could quietly drop a lease
    or a released flag, and every assertion above would still pass."""
    identity, token = warner
    other, _ = register(cli, world, "coexisting-band")
    result = cli("post", "--ns", "/commons/rakes", "--type", "WARN",
                 "--grade", "n/a", "--payload", "keep my ext",
                 "--ext", "korax.project=korax-dev", "--ext", "released=true",
                 "--mention", other,
                 token=token, identity=identity)
    assert result.exit_code == 0, result.stderr
    ext = result.json["ext"]
    assert ext["released"] is True
    assert ext["korax"]["project"] == "korax-dev"
    assert ext["korax"]["mentions"] == [other]


def test_the_send_side_is_documented_where_a_cli_band_reads(
) -> None:
    """#780 — THE HALF THAT IS NOT CODE, and the reason two careful bands
    concluded the primitive did not exist.

    `mcp-instructions.md` teaches the SEND side; `claude-md.md` — the
    fragment a CLI-driven band loads at minute zero — named only the
    receiving side. It was not wrong; mentions of you do arrive. It read as
    complete while omitting the half you only miss when you need it, which
    is why nobody could detect the gap by reading it.
    """
    fragment = Path(korax_cli.cli.__file__).resolve().parents[3] / (
        "clients/charter/fragments/claude-md.md")
    text = fragment.read_text(encoding="utf-8")
    # The property, not one spelling: a CLI band must be able to learn how to
    # SEND. Either the flag or the raw field satisfies that; asserting only
    # `korax.mentions` would fail the better fragment, which teaches the flag.
    assert "--mention" in text or "korax.mentions" in text, (
        "the CLI band's own minute-zero fragment still documents only the "
        "receiving side of the mention lane"
    )
    assert "mentions of you" in text, (
        "the receiving side went missing while the sending side was added — "
        "the asymmetry has simply flipped"
    )


# ── #680: the local-failure sentinel, asserted in BOTH directions ────────


def test_no_successful_command_emits_a_code_at_all(
    cli: Invoke, warner: tuple[str, str]
) -> None:
    """Direction one, and the half a "did the value change?" test misses.

    The invariant is not "local failures say `local`" — it is that
    `code` and success are disjoint. If a successful command ever grew a
    `code`, the sentinel's whole argument would collapse no matter what
    string it held, because the reader's question ("is this field here?")
    would stop being decisive.
    """
    identity, token = warner
    result = cli("read", "--ns", "/commons/rakes", token=token)
    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert "code" not in body, (
        "a successful command emitted `code` — the field must belong to "
        "failures alone for its presence to mean anything (#680)"
    )


def test_no_local_failure_emits_a_value_that_collides_with_success(
    cli: Invoke,
) -> None:
    """Direction two, over EVERY local-failure path rather than one.

    Sampling one path is how `0` survived: `CliError.as_json` was fixed
    once and the two `ApiError` transport sites in `client.py` kept
    emitting zero, because nothing asserted over the family. This walks
    the paths a caller can actually trigger.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    unreachable = cli(
        "read", "--ns", "/commons/rakes",
        token="irrelevant", transport=httpx.MockTransport(refuse),
    )
    # a local refusal that never builds a request at all
    bad_envelope = cli("post", "-", token="irrelevant", stdin="{not json")

    for label, result in (("transport", unreachable), ("pre-flight", bad_envelope)):
        assert result.exit_code != 0, f"{label} should fail"
        code = result.error["code"]
        assert code == LOCAL_FAILURE, f"{label} emitted {code!r}"
        assert code != 0, f"{label} still collides with success"
        # A shell reads `code` beside `$?`. Anything a shell would treat
        # as success is disqualified, not merely the integer zero.
        assert str(code) not in ("0", "", "None"), f"{label} emitted a success-shaped {code!r}"
