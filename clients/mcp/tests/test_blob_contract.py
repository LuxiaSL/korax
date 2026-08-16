"""`attach`/`fetch` are ONE contract with two implementations — JOB
#2325, B2. Sibling of `clients/cli/tests/test_blob_contract.py`, per
the R127 precedent (`test_why_contract.py`) `test_backoff_contract.py`
and `test_counter_contract.py` set before it: `clients/mcp` and
`clients/cli` share no runtime code by design, so each client's wire
vocabulary is pinned as LITERALS in its own test file, not imported
from the module under test. A test that read its expectations out of
the code it guards would pass through any change to that code.

If a client ever renames `caption` to `note`, or drops `media_type`
from the query string, this reddens against a constant the sibling
client still meets — that is the whole point of duplicating it.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from korax_mcp.client import KoraxClient
from korax_mcp.config import KoraxConfig

pytestmark = pytest.mark.anyio

#: POST /blob's query parameters, exactly. `caption` is required by both
#: clients' own argument parsing; `media_type` is optional and omitted
#: from the query string entirely when not given (not sent as `null`).
BLOB_UPLOAD_QUERY_PARAMS = {"caption", "media_type"}

#: What a successful POST /blob response must carry — the shape both
#: clients build a typed/structured result from.
BLOB_UPLOAD_RESPONSE_FIELDS = {"sha256", "bytes", "anchor"}

#: The upload endpoint, exactly.
UPLOAD_PATH = "/blob"


def _fetch_path(sha256: str) -> str:
    return f"/blob/{sha256}"


def _client(transport: httpx.MockTransport) -> KoraxClient:
    return KoraxClient(
        KoraxConfig(url="http://board.test", token=SecretStr("tok")),
        transport=transport,
    )


async def test_attach_blob_sends_exactly_the_contracted_query_params() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"sha256": "a" * 64, "bytes": 3, "anchor": 1})

    client = _client(httpx.MockTransport(handler))
    await client.attach_blob(b"abc", caption="hi", media_type="text/plain")

    request = captured["request"]
    assert request.method == "POST"
    assert request.url.path == UPLOAD_PATH
    params = dict(httpx.QueryParams(request.url.query))
    assert set(params) == BLOB_UPLOAD_QUERY_PARAMS
    assert params["caption"] == "hi"
    assert params["media_type"] == "text/plain"
    assert request.content == b"abc", "the body must be the raw bytes, never JSON"


async def test_attach_blob_omits_media_type_entirely_when_not_given() -> None:
    """CONTROL: `media_type=None` must not become the literal string
    `"None"` or an empty-but-present param — either would tell the
    server something the caller never said."""
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"sha256": "a" * 64, "bytes": 3, "anchor": 1})

    client = _client(httpx.MockTransport(handler))
    await client.attach_blob(b"abc", caption="hi")

    params = dict(httpx.QueryParams(captured["request"].url.query))
    assert set(params) == {"caption"}


async def test_attach_blob_response_carries_the_contracted_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sha256": "a" * 64, "bytes": 3, "anchor": 7})

    client = _client(httpx.MockTransport(handler))
    body = await client.attach_blob(b"abc", caption="hi")
    assert BLOB_UPLOAD_RESPONSE_FIELDS <= set(body)


async def test_fetch_blob_hits_the_contracted_path_with_no_query_at_all() -> None:
    """The whole of #1948's query-token amendment: the client sends
    NOTHING beside the path. Adding a `token` (or any) query param here
    would be the regression this contract exists to catch."""
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, content=b"bytes", headers={"content-type": "text/plain"})

    client = _client(httpx.MockTransport(handler))
    content, media_type = await client.fetch_blob("a" * 64)

    request = captured["request"]
    assert request.method == "GET"
    assert request.url.path == _fetch_path("a" * 64)
    assert request.url.query == b""
    assert content == b"bytes"
    assert media_type == "text/plain"
