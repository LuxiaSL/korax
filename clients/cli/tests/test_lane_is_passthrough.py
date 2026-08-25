"""`<lane>_is` strings survive the CLI layer byte-for-byte — JOB #3774.

The MCP half of this lives in `clients/mcp/tests/test_lane_is_passthrough`;
the argument for both is there. What is specific to this client: `cmd_view`
shape-checks the response through `ViewResult`, which declares
`extra="allow"` and leaves `output` untyped ON PURPOSE (§13 — a client
that narrowed a reduction would be filtering a projection it presents as
complete). These strings are exactly the kind of additive field that
promise exists to protect, so this test is that promise's first
beneficiary and its check.

Both emission shapes are asserted — a twin inside a dict `output`, and
`output_is` beside a bare-list `output` — because they travel different
paths and only one of them is inside the field `ViewResult` leaves alone.
"""

from __future__ import annotations

from typing import Any

from korax.reductions import (
    DOCKET_ESCALATED_IS,
    DOCKET_UNGATED_IS,
    OF_RECORD_IS,
)

from conftest import Invoke


def test_dict_view_lane_strings_reach_stdout_unmodified(
    cli: Invoke, world: dict[str, Any]
) -> None:
    result = cli("view", "docket", "--ns", "/korax-dev", token=world["op_token"])
    assert result.exit_code == 0, result.stderr

    output = result.json["output"]
    assert output["escalated_is"] == DOCKET_ESCALATED_IS
    assert output["ungated_is"] == DOCKET_UNGATED_IS
    assert len(output["ungated_is"]) == len(DOCKET_UNGATED_IS)


def test_list_view_output_is_survives_the_shape_check(
    cli: Invoke, world: dict[str, Any]
) -> None:
    """`of-record`'s string rides on the response envelope, which is the
    half `ViewResult` actually models — so this is the assertion that the
    model's `extra="allow"` is doing what its docstring says."""
    result = cli("view", "of-record", "--project", "/korax-dev",
                 token=world["op_token"])
    assert result.exit_code == 0, result.stderr

    assert "output_is" in result.json, (
        "`of-record` returns a bare list; its lane string rides beside "
        "`output` and the CLI dropped it"
    )
    assert result.json["output_is"] == OF_RECORD_IS

    # And no shape warning was emitted — an additive field must not read
    # as a protocol violation to the reader, which is how a client teaches
    # its user to ignore the warnings that matter (#662's family).
    assert not result.warnings, result.warnings
