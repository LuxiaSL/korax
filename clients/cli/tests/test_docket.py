"""`korax docket` — the session-opening query, client half (§10.12).

JOB #714. The reduction is tested server-side; what these assert is the
part a client can get wrong: that the command reaches the right view,
shape-checks the response like every other structured read, and does not
quietly drop the fields a reader needs to know the answer is partial.

The last one is #662's family — `cmd_search` and `cmd_neighbourhood`
shipped without `_check_shape`, so a server that stopped sending the
§9.3 counters would have printed a partial slice and exited zero. A new
read command that skips the check re-files that bug on the newest
surface, which is where it always lands.
"""

from __future__ import annotations

import json
from typing import Any

from korax_cli import PROTO

from conftest import Invoke, register


def _grants(cli: Invoke, world: dict, *pairs: tuple[str, str, str]) -> None:
    """Several grants in ONE root POLICY.

    `conftest.grant` posts a root policy carrying the operator plus a
    single grantee, and a POLICY REPLACES its namespace's grants rather
    than adding to them (`policy.py`'s `grants_with` — "a graduation
    POLICY that strips a desk grant while adding the maintainer is legal
    precisely because the two never coexist"). So calling it twice grants
    the second band and silently revokes the first.
    """
    envelope = json.dumps({
        "proto": PROTO, "author": world["operator"], "ns": "/",
        "type": "POLICY", "grade": "n/a", "refs": [], "ext": {},
        "payload": {"grants": [
            {"identity": world["operator"], "ns": "/**", "band": "human"},
            {"identity": "band:*", "ns": "/**", "band": "reader"},
            *({"identity": i, "ns": ns, "band": b} for i, ns, b in pairs),
        ]},
    })
    result = cli("post", "-", token=world["op_token"], stdin=envelope)
    assert result.exit_code == 0, result.stderr


def _post(cli: Invoke, token: str, author: str, **body: Any) -> dict[str, Any]:
    envelope = json.dumps({
        "proto": PROTO, "author": author, "grade": "n/a", "refs": [],
        "ext": {}, **body,
    })
    result = cli("post", envelope, token=token)
    assert result.exit_code == 0, result.stderr
    return result.json


def test_docket_composes_the_three_sections(cli: Invoke, world: dict) -> None:
    desk, dtoken = register(cli, world, "cli-docket-desk")
    worker, wtoken = register(cli, world, "cli-docket-worker")
    _grants(cli, world, (desk, "/dproj/**", "desk"),
            (worker, "/dproj/**", "claimant"))

    _post(cli, dtoken, desk, ns="/dproj/jobs", type="POLICY", payload={
        "acts": ["JOB", "CLAIM", "FINDING"], "grades": True,
        "require_lease": True, "job_posters": "desk"})
    _post(cli, dtoken, desk, ns="/dproj/issues", type="POLICY", payload={
        "acts": ["OPEN", "FINDING", "NOTE"], "grades": True})

    job = _post(cli, dtoken, desk, ns="/dproj/jobs", type="JOB",
                payload="the work", pointer={
                    "uri": "https://example.invalid/b.md", "sha256": "0" * 64})
    _post(cli, wtoken, worker, ns="/dproj/issues", type="OPEN",
          payload="ISSUE: something is wrong\nand here is the detail")
    _post(cli, wtoken, worker, ns="/korax/inbox", type="OPEN",
          payload="grant request: worker seeks claimant on /dproj/**")

    result = cli("docket", "--ns", "/dproj", token=dtoken)
    assert result.exit_code == 0, result.stderr
    body = result.json
    assert body["view"] == "docket"

    out = body["output"]
    assert out["work"]["open"] == [job["id"]]
    assert [f["first_line"] for f in out["filed"]] == [
        "ISSUE: something is wrong"
    ]
    # the grant-request shape carries NO refs, so an edge-scoped
    # `escalated` would be blind to exactly this envelope (D1, #756)
    assert [e["author"] for e in out["escalated"]] == [worker]
    assert out["namespaces"] == ["/dproj", "/korax/inbox"]

    # §9.3 — the counters ride on every structured read, and the reader
    # is told which slice they describe
    for field in ("sealed_excluded", "rotated_excluded",
                  "participation_excluded"):
        assert field in body, f"{field} missing — a partial slice would read as whole"


def test_the_identity_filter_narrows_and_the_totals_do_not(
    cli: Invoke, world: dict
) -> None:
    desk, dtoken = register(cli, world, "cli-docket-desk2")
    worker, wtoken = register(cli, world, "cli-docket-worker2")
    _grants(cli, world, (desk, "/eproj/**", "desk"),
            (worker, "/eproj/**", "claimant"))
    _post(cli, dtoken, desk, ns="/eproj/issues", type="POLICY", payload={
        "acts": ["OPEN", "FINDING", "NOTE"], "grades": True})
    _post(cli, dtoken, desk, ns="/eproj/issues", type="OPEN",
          payload="the desk's issue")
    _post(cli, wtoken, worker, ns="/eproj/issues", type="OPEN",
          payload="the worker's issue")

    whole = cli("docket", "--ns", "/eproj", token=dtoken).json["output"]
    mine = cli("docket", "--ns", "/eproj", "--identity", worker,
               token=dtoken).json["output"]

    assert len(whole["filed"]) == 2
    assert [f["author"] for f in mine["filed"]] == [worker]
    assert mine["totals"] == whole["totals"], (
        "a band that cannot see what it was narrowed away from will "
        "mistake its slice for the program"
    )
    assert mine["totals"]["filed"] == 2


def test_docket_shape_checks_its_response(cli: Invoke, world: dict) -> None:
    """#662: `search` and `neighbourhood` are the two structured reads that
    never shape-checked, so a server dropping the §9.3 counters would have
    printed a partial slice and exited zero. A response missing `view`
    must fail loudly rather than render."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {"work": {}}, "at": 3})

    result = cli("docket", "--ns", "/dproj", token=world["op_token"],
                 transport=httpx.MockTransport(handler))
    assert result.exit_code != 0, "a malformed view response rendered as data"
    assert "view" in (result.stderr + result.stdout)
