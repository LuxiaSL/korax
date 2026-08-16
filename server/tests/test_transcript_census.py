"""The census's canaries — JOB #2679.

Every test here is built so it can FAIL. That is the point: four detectors
this loop reported clean about questions they could not have answered
(#2666), and a census is exactly the shape of instrument that goes quiet in
the flattering direction. So each property below has a matching negative —
a fixture that must move the number — and the seam has a canary string that
must never appear in any output.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "transcript_census.py"

# A string that exists ONLY inside a payload body. If it ever reaches the
# report, the seam leaked. It is deliberately unmistakable.
SEAM_CANARY = "SEALED-MAILBOX-BODY-DO-NOT-EMIT-9f3a1c"


def _assistant(rid: str, usage: dict[str, int], blocks: list[dict]) -> str:
    return json.dumps({
        "type": "assistant",
        "requestId": rid,
        "sessionId": "s1",
        "message": {"role": "assistant", "usage": usage, "content": blocks},
    })


def _user_result(tool_use_id: str, text: str) -> str:
    return json.dumps({
        "type": "user",
        "sessionId": "s1",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id,
                         "content": text}],
        },
    })


USAGE = {"input_tokens": 100, "output_tokens": 50,
         "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 10}


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root), *extra],
        capture_output=True, text=True, check=False,
    )


def _json_run(root: Path) -> dict:
    proc = _run(root, "--json")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """One session: 3 assistant records over 2 distinct requests, one of
    which is split across two records carrying IDENTICAL usage — the real
    transcript's shape, and the double-count trap."""
    lines = [
        _assistant("req-1", USAGE, [{"type": "thinking", "thinking": "t"}]),
        # same request, second record, SAME usage repeated verbatim
        _assistant("req-1", USAGE, [
            {"type": "tool_use", "id": "tu-1", "name": "Bash",
             "input": {"command": "korax read --since 5", "description": "d"}},
        ]),
        _user_result("tu-1", json.dumps({"envelopes": [{"id": 11}, {"id": 12}]})),
        _assistant("req-2", USAGE, [
            {"type": "tool_use", "id": "tu-2", "name": "mcp__korax__korax_read",
             "input": {"since": 5}},
        ]),
        _user_result("tu-2", json.dumps({"envelopes": [{"id": 11}]})),
    ]
    (tmp_path / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


# ── the positive: known counts in, exactly those counts out ──────────────


def test_known_counts_come_out_exactly(corpus: Path) -> None:
    out = _json_run(corpus)
    d = out["denominators"]
    assert d["files_found"] == 1
    assert d["files_parsed"] == 1
    assert d["lines_read"] == 5
    assert d["lines_unparseable"] == 0
    assert d["assistant_records"] == 3
    assert d["distinct_requests"] == 2, "three records, two requests"
    assert d["tool_uses"] == 2
    assert d["tool_results"] == 2


def test_exact_tokens_dedupe_by_request_not_by_record(corpus: Path) -> None:
    """THE correctness property. Two of three records share req-1, so exact
    totals must count that request's usage ONCE."""
    e = _json_run(corpus)["exact_tokens"]
    assert e["output_tokens"] == 2 * USAGE["output_tokens"], "2 requests, not 3 records"
    assert e["input_tokens"] == 2 * USAGE["input_tokens"]
    assert e["naive_output_tokens"] == 3 * USAGE["output_tokens"], (
        "the naive control must show the inflated figure, or it is not a control"
    )


def test_the_dedup_can_actually_fail(tmp_path: Path) -> None:
    """NEGATIVE CONTROL for the test above. If every record carried a
    DISTINCT requestId, deduped and naive must agree — proving the previous
    test's pass came from dedup and not from the fixture happening to be
    small."""
    lines = [_assistant(f"req-{i}", USAGE, [{"type": "text", "text": "x"}])
             for i in range(3)]
    (tmp_path / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    e = _json_run(tmp_path)["exact_tokens"]
    assert e["output_tokens"] == e["naive_output_tokens"] == 3 * USAGE["output_tokens"]


# ── the negative the brief names: a malformed line must be COUNTED ───────


def test_a_malformed_line_lands_in_the_skipped_count(tmp_path: Path) -> None:
    good = _assistant("r1", USAGE, [{"type": "text", "text": "x"}])
    (tmp_path / "s.jsonl").write_text(
        good + "\n" + "{not json at all" + "\n" + "[]\n" + "\n" + good + "\n",
        encoding="utf-8",
    )
    d = _json_run(tmp_path)["denominators"]
    assert d["lines_read"] == 5
    assert d["lines_blank"] == 1
    assert d["lines_unparseable"] == 2, "bad JSON and a non-object both count"
    assert d["assistant_records"] == 2, "the good lines still parsed"


def test_the_skipped_counter_stays_zero_on_a_clean_file(tmp_path: Path) -> None:
    """The other half — a counter that only ever goes up is not a counter."""
    (tmp_path / "s.jsonl").write_text(
        _assistant("r1", USAGE, [{"type": "text", "text": "x"}]) + "\n",
        encoding="utf-8",
    )
    assert _json_run(tmp_path)["denominators"]["lines_unparseable"] == 0


# ── the seam, tested structurally rather than trusted ────────────────────


def test_no_payload_body_reaches_the_report(tmp_path: Path) -> None:
    """A canary string living only inside payloads must appear in NEITHER
    the human report nor the JSON. This is the §8.7 seam as a test."""
    lines = [
        _assistant("r1", USAGE, [
            {"type": "tool_use", "id": "tu-1", "name": "Bash",
             "input": {"command": f"korax dm band:x '{SEAM_CANARY}'",
                       "description": SEAM_CANARY}},
        ]),
        _user_result("tu-1", json.dumps({"envelopes": [
            {"id": 7, "payload": SEAM_CANARY, "ns": "/dm/band:x"}]})),
    ]
    (tmp_path / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    human = _run(tmp_path)
    raw = _run(tmp_path, "--json")
    assert human.returncode == 0 and raw.returncode == 0
    assert SEAM_CANARY not in human.stdout, "payload body leaked into the report"
    assert SEAM_CANARY not in human.stderr
    assert SEAM_CANARY not in raw.stdout, "payload body leaked into --json"


def test_the_seam_canary_is_actually_present_in_the_fixture(tmp_path: Path) -> None:
    """A canary that is not in the input proves nothing about the output.
    This is the control for the test above (#2518)."""
    lines = [_assistant("r1", USAGE, [
        {"type": "tool_use", "id": "tu-1", "name": "Bash",
         "input": {"command": f"korax dm band:x '{SEAM_CANARY}'", "description": "d"}}])]
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert SEAM_CANARY in f.read_text(encoding="utf-8")


def test_a_command_that_is_not_an_identifier_is_labelled_not_quoted(
    tmp_path: Path,
) -> None:
    """A leading token carrying a path or a secret must not round-trip."""
    lines = [_assistant("r1", USAGE, [
        {"type": "tool_use", "id": "t", "name": "Bash",
         "input": {"command": f"/home/luxia/{SEAM_CANARY}/run.sh", "description": "d"}}])]
    (tmp_path / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = _json_run(tmp_path)
    assert SEAM_CANARY not in json.dumps(out)


# ── the axes the brief asks for ──────────────────────────────────────────


def test_korax_cli_and_mcp_are_separated_by_verb(corpus: Path) -> None:
    out = _json_run(corpus)
    assert "read" in out["korax_cli"], f"CLI verbs: {list(out['korax_cli'])}"
    assert "korax_read" in out["korax_mcp"], f"MCP verbs: {list(out['korax_mcp'])}"


def test_duplicate_envelope_delivery_is_counted_across_sessions(
    tmp_path: Path,
) -> None:
    """Envelope 11 drained by two DIFFERENT sessions is one redundant
    delivery; envelope 12 drained once is not."""
    def session(name: str, ids: list[int]) -> None:
        lines = [
            _assistant("r-" + name, USAGE, [
                {"type": "tool_use", "id": "tu", "name": "mcp__korax__korax_read",
                 "input": {"since": 1}}]),
            _user_result("tu", json.dumps(
                {"envelopes": [{"id": i} for i in ids]})),
        ]
        (tmp_path / f"{name}.jsonl").write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")

    session("sa", [11, 12])
    session("sb", [11])
    ch = _json_run(tmp_path)["channel"]
    assert ch["distinct_envelope_ids"] == 2
    assert ch["ids_drained_by_multiple_sessions"] == 1, "only id 11"
    assert ch["redundant_deliveries"] == 1


def test_a_single_session_draining_twice_is_not_counted_as_duplicate(
    tmp_path: Path,
) -> None:
    """The negative for the above: duplication is across SESSIONS. One
    session re-reading its own page is not N-times billing."""
    lines = [
        _assistant("r1", USAGE, [
            {"type": "tool_use", "id": "t1", "name": "mcp__korax__korax_read",
             "input": {"since": 1}}]),
        _user_result("t1", json.dumps({"envelopes": [{"id": 11}]})),
        _assistant("r2", USAGE, [
            {"type": "tool_use", "id": "t2", "name": "mcp__korax__korax_read",
             "input": {"since": 1}}]),
        _user_result("t2", json.dumps({"envelopes": [{"id": 11}]})),
    ]
    (tmp_path / "solo.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ch = _json_run(tmp_path)["channel"]
    assert ch["ids_drained_by_multiple_sessions"] == 0
    assert ch["redundant_deliveries"] == 0


def test_subagent_transcripts_are_counted_and_labelled(tmp_path: Path) -> None:
    """The corpus discrepancy the brief's cut did not resolve: 43 top-level
    files, 55 with subagents. Both are reported rather than one chosen."""
    (tmp_path / "top.jsonl").write_text(
        _assistant("r1", USAGE, [{"type": "text", "text": "x"}]) + "\n",
        encoding="utf-8")
    sub = tmp_path / "top" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-a.jsonl").write_text(
        _assistant("r2", USAGE, [{"type": "text", "text": "x"}]) + "\n",
        encoding="utf-8")
    d = _json_run(tmp_path)["denominators"]
    assert d["files_found"] == 2
    assert d["files_toplevel"] == 1
    assert d["files_subagent"] == 1


def test_a_missing_root_is_refused_not_reported_as_empty(tmp_path: Path) -> None:
    """An empty census over a nonexistent dir would render as 'nothing to
    see', which is the failure this whole loop kept finding."""
    proc = _run(tmp_path / "does-not-exist")
    assert proc.returncode == 2
    assert "not a directory" in proc.stderr
