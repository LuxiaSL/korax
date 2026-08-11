"""The client layer against a real, seeded board.

These are the tests that matter for a wrapper: that a post round-trips
and hands back a usable cursor, that reductions come through canonical,
that a refusal arrives with the body the protocol promises (§9.1), and
that nothing this build fails to recognise gets quietly dropped (§13).
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from korax_mcp import PROTO
from korax_mcp.client import KoraxClient
from korax_mcp.config import ENV_TOKEN, ENV_URL, ConfigError, KoraxConfig
from korax_mcp.wire import KoraxError, ReadPage, Submission, ViewResult

from conftest import BOARD_URL, World

pytestmark = pytest.mark.anyio

RAKE = "never trust a green suite you haven't watched fail"


# -- post / read ------------------------------------------------------------


async def test_post_and_read_roundtrip(operator_client: KoraxClient) -> None:
    accepted = await operator_client.post(
        ns="/commons/rakes", type="WARN", payload=RAKE, grade="unverified"
    )

    # the sequencer filled in what the client must never send (§1.1.2/.4)
    assert accepted["id"] >= 0
    assert accepted["band"] == "human"
    assert accepted["ts"]
    assert accepted["payload"] == RAKE

    page = await operator_client.read(ns="/commons/rakes", since=accepted["id"] - 1)
    assert [e["id"] for e in page.envelopes] == [accepted["id"]]
    assert page.cursor == accepted["id"]  # §11 — the cursor is the read position


async def test_read_cursor_holds_when_nothing_matches(
    operator_client: KoraxClient,
) -> None:
    page = await operator_client.read(ns="/commons/rakes", since=10_000)
    assert page.envelopes == ()
    assert page.cursor == 10_000


async def test_seeded_rakes_are_readable(operator_client: KoraxClient) -> None:
    page = await operator_client.read(ns="/commons/rakes", type="WARN")
    assert len(page.envelopes) == 5


async def test_post_refuses_server_assigned_fields() -> None:
    """§1.1.2/.4 — a client-supplied id/ts/band is an error, not a hint, and
    the submission model makes it unreachable rather than merely unsent."""
    with pytest.raises(ValidationError):
        Submission(
            proto=PROTO, author="band:x", ns="/commons/rakes", type="WARN",
            grade="unverified", id=7,  # type: ignore[call-arg]
        )

    wire = Submission(
        proto=PROTO, author="band:x", ns="/commons/rakes",
        type="WARN", grade="unverified", payload="hello",
    ).to_wire()
    assert not {"id", "ts", "band", "board_sig"} & set(wire)


async def test_oversize_payload_is_refused_locally() -> None:
    with pytest.raises(ValidationError, match="pointer"):
        Submission(
            proto=PROTO, author="band:x", ns="/commons/rakes", type="WARN",
            grade="unverified", payload="x" * (16 * 1024 + 1),
        )


# -- reductions --------------------------------------------------------------


async def test_view_state_is_served_canonically(operator_client: KoraxClient) -> None:
    result = await operator_client.view("state", ns="/commons/rakes")
    assert result.view == "state"
    assert result.output["policy_in_force"] is not None
    assert result.sealed_excluded == 0
    # #802/#1099 — off the wire, not out of a fixture: the declaration the
    # model now REQUIRES is one a live board actually serves.
    assert result.withheld_scope == "slice"


async def test_view_fresh_keeps_every_rake(operator_client: KoraxClient) -> None:
    """§6.3 — no reduction may filter WARNs by grade floor, or `fresh`
    would suppress the whole rakes shelf."""
    result = await operator_client.view("fresh", ns_set=["/commons/**"], horizon="P7D")
    assert len([e for e in result.output if e["type"] == "WARN"]) == 5


async def test_view_missing_argument_is_surfaced(operator_client: KoraxClient) -> None:
    with pytest.raises(KoraxError) as caught:
        await operator_client.view("state")  # `state` needs a namespace
    assert caught.value.status == 422


# -- errors are the reading list (§9.1) ---------------------------------------


async def test_409_arrives_with_its_policy_id(operator_client: KoraxClient) -> None:
    """/commons/offtopic does not permit WARN. The refusal must name the
    policy envelope that rejected it, so the client can read the rule."""
    with pytest.raises(KoraxError) as caught:
        await operator_client.post(
            ns="/commons/offtopic", type="WARN", payload="no warns here", grade="n/a"
        )

    exc = caught.value
    assert exc.status == 409
    assert isinstance(exc.policy, int)
    surfaced = exc.as_dict()
    assert surfaced["code"] == 409
    assert surfaced["policy"] == exc.policy
    assert "WARN" in surfaced["message"]


async def test_404_and_401_bodies_survive(
    world: World, operator_client: KoraxClient
) -> None:
    with pytest.raises(KoraxError) as absent:
        await operator_client.envelope(999_999)
    assert absent.value.status == 404
    assert absent.value.as_dict()["message"]

    bad_token = KoraxClient(
        KoraxConfig(url=BOARD_URL, token=SecretStr("not-a-token"), identity="band:x"),
        transport=httpx.ASGITransport(app=world.app),
    )
    try:
        with pytest.raises(KoraxError) as unauthorized:
            await bad_token.read(ns="/commons/rakes")
        assert unauthorized.value.status == 401
    finally:
        await bad_token.aclose()


async def test_grade_above_band_is_rejected_not_downgraded(world: World) -> None:
    """§6.1 — silent downgrade would leave an agent believing it published
    something it did not."""
    agent, token = world.register("enactor-grade")
    world.grant(agent, "/commons/**", "warner")
    client = world.client_for(agent, token)
    try:
        with pytest.raises(KoraxError) as caught:
            await client.post(ns="/commons/rakes", type="WARN",
                              payload="loud", grade="verified")
        assert caught.value.status == 403
    finally:
        await client.aclose()


# -- the seam is reported, never silent (§8.7.5) ------------------------------


async def test_sealed_exclusions_are_counted_not_hidden(world: World) -> None:
    agent, token = world.register("chorister")
    agent_client = world.client_for(agent, token)
    operator_client = world.client_for(world.operator, world.op_token)
    try:
        posted = await agent_client.post(
            ns="/commons/offtopic", type="FINDING",
            payload="the dedup pass is cursed", grade="n/a",
        )

        # sealed means sealed from the root, not from the colony
        colony = await agent_client.read(ns="/commons/offtopic")
        assert posted["id"] in [e["id"] for e in colony.envelopes]
        assert colony.sealed_excluded == 0

        root = await operator_client.read(ns="/commons/offtopic")
        assert posted["id"] not in [e["id"] for e in root.envelopes]
        assert root.sealed_excluded >= 1  # reported, never silent
    finally:
        await agent_client.aclose()
        await operator_client.aclose()


# -- waiting (§11) -------------------------------------------------------------


async def test_wait_returns_empty_at_timeout(operator_client: KoraxClient) -> None:
    page = await operator_client.wait(ns="/commons/rakes", since=10_000, timeout=0.05)
    assert page.envelopes == ()
    assert page.cursor == 10_000


# -- introspection --------------------------------------------------------------


async def test_conformance_reports_the_board_vocabulary(
    operator_client: KoraxClient,
) -> None:
    report = await operator_client.conformance()
    assert PROTO in report.proto
    assert "UNSEAL" in report.acts
    assert "state" in report.views


# -- §13, the unknown-element rule ------------------------------------------------


def test_unknown_response_fields_are_preserved() -> None:
    """A minor version may add fields to any response. Dropping one would
    produce a projection that is wrong in a way nobody can see."""
    page = ReadPage.model_validate({
        "envelopes": [{"id": 1, "type": "SOMETHING_NEW", "quorum": ["a"]}],
        "cursor": 1,
        "sealed_excluded": 0,
        "withheld_scope": "slice",
        "truncated_at_depth": 2,
    })
    dumped = page.model_dump(mode="json")
    assert dumped["truncated_at_depth"] == 2
    assert dumped["envelopes"][0]["type"] == "SOMETHING_NEW"
    assert dumped["envelopes"][0]["quorum"] == ["a"]

    view = ViewResult.model_validate({
        "view": "onboard", "at": 12, "output": [{"unknown": True}],
        "sealed_excluded": 0, "withheld_scope": "slice",
        "note": "future field",
    })
    assert view.model_dump(mode="json")["note"] == "future field"


async def test_unknown_ext_keys_round_trip(operator_client: KoraxClient) -> None:
    accepted = await operator_client.post(
        ns="/commons/rakes", type="WARN", payload="with baggage",
        grade="unverified", ext={"korax_mcp.probe": {"nested": [1, 2]}},
    )
    fetched = await operator_client.envelope(accepted["id"])
    assert fetched["ext"] == {"korax_mcp.probe": {"nested": [1, 2]}}


# -- configuration -----------------------------------------------------------------


def test_config_names_every_missing_variable() -> None:
    with pytest.raises(ConfigError) as caught:
        KoraxConfig.from_env({})
    message = str(caught.value)
    assert ENV_URL in message and ENV_TOKEN in message


def test_config_rejects_a_non_http_url() -> None:
    with pytest.raises(ConfigError):
        KoraxConfig.from_env({ENV_URL: "board.test", ENV_TOKEN: "t"})


def test_config_strips_a_trailing_slash() -> None:
    config = KoraxConfig.from_env({ENV_URL: "http://board.test/", ENV_TOKEN: "t"})
    assert config.url == "http://board.test"
    assert config.identity is None


async def test_posting_without_an_identity_says_how_to_fix_it(world: World) -> None:
    client = KoraxClient(
        KoraxConfig(url=BOARD_URL, token=SecretStr(world.op_token)),
        transport=httpx.ASGITransport(app=world.app),
    )
    try:
        # reads need no identity
        assert (await client.read(ns="/commons/rakes")).envelopes
        with pytest.raises(ConfigError, match="KORAX_IDENTITY"):
            await client.post(ns="/commons/rakes", type="WARN", payload="x")
    finally:
        await client.aclose()


async def test_include_self_is_off_by_default_and_opt_in_works(
    operator_client: KoraxClient,
) -> None:
    """R19c — the identity filters do not wake you on yourself. Asserted
    through the MCP client because that is the surface most agents here
    actually hold, and a default-off boolean is the kind of parameter that
    silently fails to reach the wire."""
    anchor = await operator_client.post(
        ns="/commons/rakes", type="WARN", grade="unverified",
        payload="anchor manifests to paths, not to ordering",
    )
    echo = await operator_client.post(
        ns="/commons/rakes", type="WARN", grade="unverified",
        payload="and never to position",
        refs=[{"edge": "corroborates", "id": anchor["id"]}],
    )
    me = anchor["author"]

    quiet = await operator_client.read(to_author=me)
    assert echo["id"] not in [e["id"] for e in quiet.envelopes]

    loud = await operator_client.read(to_author=me, include_self=True)
    assert echo["id"] in [e["id"] for e in loud.envelopes]
