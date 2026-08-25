"""`korax why` end-to-end — the command reaches the reduction and renders
it. JOB #3765.

**This file used to hold ~20 tests of route LOGIC** against
`korax_cli/why.py`, which computed the answer client-side. That module is
deleted and the logic now lives in `server/korax/why.py`; the semantics
those tests pinned moved to `server/tests/test_why.py` rather than being
dropped — a test that pins behaviour belongs to the verb, not to the file
that used to host it.

What is left here is the part only a client test can assert: the command
is wired, authenticated, reaches `/view/why`, and renders what it gets
without reshaping it.

**The command emits the WHOLE view envelope**, not `output` unwrapped.
Two reasons and both are load-bearing: the §9.3 counters live at the
envelope level, so unwrapping would drop what the answer could not see;
and acceptance 5 requires the two clients to be byte-identical, which is
true by construction when both render the same body and false the moment
either starts unwrapping on its own schedule.
"""

from __future__ import annotations

from typing import Any

from conftest import Invoke, grant, register

ROUTES = ("inbound-edges", "closes-on-target", "attested-on-target", "sha-in-prose")
STATUSES = {"searched", "not-applicable", "bounded"}


def test_why_is_reachable_and_shaped_end_to_end(cli: Invoke, world: dict[str, Any]) -> None:
    """Wired, authenticated, and emitting the documented shape against a
    real board."""
    identity, token = register(cli, world, "why-e2e")
    grant(cli, world, identity, "/korax-dev/**", "claimant")

    job = cli("post", "--ns", "/korax-dev/jobs", "--type", "JOB",
              "--payload", "JOB — a thing to do", "--grade", "n/a",
              token=world["op_token"], identity=world["operator"])
    assert job.exit_code == 0, job.stderr
    job_id = job.json["id"]

    delivery = cli("post", "--ns", "/korax-dev/jobs", "--type", "FINDING",
                   "--payload", "DELIVERED", "--ref", f"closes:{job_id}",
                   token=token, identity=identity)
    assert delivery.exit_code == 0, delivery.stderr
    delivery_id = delivery.json["id"]

    result = cli("why", str(delivery_id), token=token)
    assert result.exit_code == 0, result.stderr

    body = result.json
    assert body["view"] == "why", "the command must render the view it asked for"
    out = body["output"]
    assert out["why"] == delivery_id
    assert out["subject"]["type"] == "FINDING"
    assert [r["route"] for r in out["routes"]] == list(ROUTES)
    for report in out["routes"]:
        assert report["basis"], f"{report['route']} emitted no basis"
    assert out["bounds"]["sources"], "each route must account for what it could not see"
    # The counters stay where a reader looks for them on every other view.
    assert "sealed_excluded" in body


def test_why_on_an_envelope_nobody_touched_says_so_without_lying(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """A lone envelope: every route present, every route empty, every
    emptiness explained. This is the shape a reader must be able to
    trust, because it is the one that looks like nothing happened."""
    identity, token = register(cli, world, "why-lonely")
    grant(cli, world, identity, "/korax-dev/**", "claimant")

    posted = cli("post", "--ns", "/korax-dev/board", "--type", "NOTE",
                 "--payload", "a note nobody answered", "--grade", "n/a",
                 token=token, identity=identity)
    assert posted.exit_code == 0, posted.stderr

    result = cli("why", str(posted.json["id"]), token=token)
    assert result.exit_code == 0, result.stderr
    out = result.json["output"]

    # A NOTE is not a delivery: `gated` is a category error on it, not
    # a search that came back empty (property 4).
    assert out["answers"]["gated"]["answer"] == "not-applicable"
    assert out["answers"]["cited"]["ids"] == []
    for report in out["routes"]:
        assert report["count"] == 0
        assert report["status"] in STATUSES
        assert report["basis"]


def test_why_refuses_an_envelope_that_does_not_exist(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """A missing envelope must fail, not return an empty answer about
    nothing — the whole family this verb is built against."""
    _identity, token = register(cli, world, "why-missing")
    result = cli("why", "999999", token=token)
    assert result.exit_code != 0
    assert result.error


def test_why_is_reproducible_at_an_offset(cli: Invoke, world: dict[str, Any]) -> None:
    """`--at` is what the move to a reduction buys: the client-side
    composition could not offer it, because it stitched several reads
    each taken at its own moment."""
    identity, token = register(cli, world, "why-at")
    grant(cli, world, identity, "/korax-dev/**", "claimant")
    posted = cli("post", "--ns", "/korax-dev/board", "--type", "NOTE",
                 "--payload", "pinned", "--grade", "n/a",
                 token=token, identity=identity)
    at = posted.json["id"]

    first = cli("why", str(at), "--at", str(at), token=token)
    assert first.exit_code == 0, first.stderr
    cli("post", "--ns", "/korax-dev/board", "--type", "NOTE", "--payload",
        "later", "--grade", "n/a", token=token, identity=identity)
    second = cli("why", str(at), "--at", str(at), token=token)
    assert second.json == first.json, "same offset, two answers — §10 is broken"
