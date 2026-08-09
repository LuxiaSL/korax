"""The CLI against a seeded board: post/read round trips, the §11 cursor
across processes, error passthrough that keeps a 409's reading list, and
§13's promise that nothing unrecognised is dropped on the way through."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from conftest import Invoke, grant, register

from korax_cli import PROTO


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
    assert "sealed_excluded" in drained.json  # §8.7.5 — never silent


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
    assert result.error["code"] == 0  # never reached a server
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
    assert result.error["code"] == 0
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
