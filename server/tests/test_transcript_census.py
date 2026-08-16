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
        _user_result("tu-1", json.dumps({"envelopes": [{"id": 11, "ts": "t", "proto": "korax/0.1"}, {"id": 12, "ts": "t", "proto": "korax/0.1"}]})),
        _assistant("req-2", USAGE, [
            {"type": "tool_use", "id": "tu-2", "name": "mcp__korax__korax_read",
             "input": {"since": 5}},
        ]),
        _user_result("tu-2", json.dumps({"envelopes": [{"id": 11, "ts": "t", "proto": "korax/0.1"}]})),
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
    the human report nor the JSON. This is the §8.7 seam as a test.

    **The fixture MUST route the canary through the drain path.** The first
    version of this test used `korax dm`, which never reaches
    `_envelope_ids` — so deliberately breaking the seam left this test
    GREEN while unrelated tests failed on corrupted output. A canary wired
    to a code path the fixture cannot reach is the #2666 defect wearing the
    costume of the test written to prevent it. Caught by red-checking
    rather than by review; both verbs are covered now.
    """
    lines = [
        # the drain path — this is what `_envelope_ids` actually inspects
        _assistant("r1", USAGE, [
            {"type": "tool_use", "id": "tu-1", "name": "mcp__korax__korax_read",
             "input": {"since": 1}},
        ]),
        _user_result("tu-1", json.dumps({"envelopes": [
            {"id": 7, "payload": SEAM_CANARY, "ns": "/dm/band:x"}]})),
        # and the non-drain path, via a command line carrying the canary
        _assistant("r2", USAGE, [
            {"type": "tool_use", "id": "tu-2", "name": "Bash",
             "input": {"command": f"korax dm band:x '{SEAM_CANARY}'",
                       "description": SEAM_CANARY}},
        ]),
        _user_result("tu-2", json.dumps({"ok": True, "echo": SEAM_CANARY})),
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
                {"envelopes": [{"id": i, "ts": "t", "proto": "korax/0.1"} for i in ids]})),
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
        _user_result("t1", json.dumps({"envelopes": [{"id": 11, "ts": "t", "proto": "korax/0.1"}]})),
        _assistant("r2", USAGE, [
            {"type": "tool_use", "id": "t2", "name": "mcp__korax__korax_read",
             "input": {"since": 1}}]),
        _user_result("t2", json.dumps({"envelopes": [{"id": 11, "ts": "t", "proto": "korax/0.1"}]})),
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


def test_per_tool_out_chars_is_not_structurally_zero(corpus: Path) -> None:
    """The first full run printed `out chars` = 0 for EVERY tool, because
    results were attributed only to the korax tables and never back to the
    per-tool one. A column that can only ever report zero is not a
    measurement — this is the guard against it coming back."""
    by_tool = _json_run(corpus)["estimated_chars_by_tool"]
    assert by_tool, "no tools recorded at all"
    assert any(v["out_chars"] > 0 for v in by_tool.values()), (
        f"every tool reports out_chars=0: {by_tool}"
    )
    assert by_tool["mcp__korax__korax_read"]["out_chars"] > 0


@pytest.mark.parametrize(
    ("command", "leak"),
    [
        # `--as` takes a value; the first full run reported the PROFILE as a verb
        ("korax --as korax-dev-enactor-quill read --since 1", "korax-dev-enactor-quill"),
        # `--limit` takes a value; the second run reported `45` as a verb, 80 uses
        ("korax read --limit 45", "45"),
        # a flag the census has never heard of must not leak its value either
        ("korax read --some-future-flag whatever-value", "whatever-value"),
    ],
)
def test_a_flag_argument_is_never_mistaken_for_a_subcommand(
    tmp_path: Path, command: str, leak: str
) -> None:
    """Every one of these is a READ. Enumerating value-taking flags is
    unbounded and was wrong twice; the subcommand set is bounded."""
    lines = [_assistant("r1", USAGE, [
        {"type": "tool_use", "id": "t", "name": "Bash",
         "input": {"command": command, "description": "d"}}])]
    (tmp_path / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cli = _json_run(tmp_path)["korax_cli"]
    assert "read" in cli, f"verbs seen: {list(cli)}"
    assert leak not in cli, f"{leak!r} leaked in as a subcommand"


def test_the_subcommand_set_matches_the_cli_source(tmp_path: Path) -> None:
    """The recogniser is a copy of the CLI's own declarations, so it can
    drift. This re-derives the set from `cli.py` and fails when it does —
    a constant nothing checks is a constant that goes stale."""
    import re

    sys.path.insert(0, str(TOOL.parent))
    from transcript_census import _KORAX_SUBCOMMANDS  # type: ignore[import-not-found]

    cli_src = (TOOL.parents[1] / "clients/cli/korax_cli/cli.py").read_text(
        encoding="utf-8"
    )
    declared = set(re.findall(r'sub\.add_parser\(\s*"([a-z0-9_-]+)"', cli_src))
    assert declared, "found no subcommand declarations — the regex went stale"
    assert declared == set(_KORAX_SUBCOMMANDS), (
        f"census missing {declared - set(_KORAX_SUBCOMMANDS)}, "
        f"stale {set(_KORAX_SUBCOMMANDS) - declared}"
    )


def test_an_unrecognised_korax_subcommand_says_so(tmp_path: Path) -> None:
    """The control for the recogniser: something that is genuinely not a
    subcommand must report as unrecognised, not vanish and not guess."""
    lines = [_assistant("r1", USAGE, [
        {"type": "tool_use", "id": "t", "name": "Bash",
         "input": {"command": "korax definitely-not-a-subcommand", "description": "d"}}])]
    (tmp_path / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert "<unrecognised>" in _json_run(tmp_path)["korax_cli"]


def test_a_cd_prefix_does_not_hide_the_real_command(tmp_path: Path) -> None:
    """`cd /path && korax read` is a korax read, not a `cd`. In the first
    full run 4,937 of 13,445 Bash uses reported as `cd`."""
    lines = [_assistant("r1", USAGE, [
        {"type": "tool_use", "id": "t", "name": "Bash",
         "input": {"command": "cd /tmp/x && korax read --since 1",
                   "description": "d"}}])]
    (tmp_path / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = _json_run(tmp_path)
    assert "read" in out["korax_cli"], f"verbs seen: {list(out['korax_cli'])}"


def test_a_missing_root_is_refused_not_reported_as_empty(tmp_path: Path) -> None:
    """An empty census over a nonexistent dir would render as 'nothing to
    see', which is the failure this whole loop kept finding."""
    proc = _run(tmp_path / "does-not-exist")
    assert proc.returncode == 2
    assert "not a directory" in proc.stderr


# ── ISSUE #2751: the byte-weighted duplicate figure ──────────────────────
#
# The caveat is the spine of this measurement and #2752 made it binding, so
# it gets a canary rather than a comment: the same envelope delivered as a
# summary and as a full body must NOT weigh the same. A `size_of(envelope)
# x (N-1)` implementation passes every other test in this file and fails
# `test_a_summary_delivery_weighs_less_than_a_full_one`.


def _census_module():
    """Import the tool by PATH, as a module.

    Registered in `sys.modules` BEFORE `exec_module`: the tool defines
    dataclasses, and `@dataclass` resolves its own module during class
    creation — without the registration that lookup returns None and the
    import dies inside `dataclasses.py` with an error naming neither the
    tool nor the cause.
    """
    import importlib.util  # noqa: PLC0415
    import sys  # noqa: PLC0415

    name = "_census_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_envelope_records_are_found_by_shape_not_by_key_name() -> None:
    """A reader keyed on `envelopes` goes quiet when a surface nests them
    differently — reductions do, and a bare `korax envelope` returns one
    loose."""
    c = _census_module()
    env = {"id": 7, "ts": "t", "proto": "korax/0.1", "payload": "x"}
    for shape in (
        {"envelopes": [env]},
        {"output": {"view": "docket", "rows": [{"inner": [env]}]}},
        env,
        [env],
    ):
        found = list(c._envelope_records(shape))
        assert [e["id"] for e in found] == [7], shape


def test_a_summary_delivery_weighs_less_than_a_full_one() -> None:
    """THE CAVEAT, AS A CANARY. Same id, two deliveries, different shapes.

    A summary record carries `payload_bytes` and no body; the full one
    carries the body. Weighing the id by a single constant would inflate
    every summary duplicate into a full-body cost, which is the unit error
    #2751 exists to prevent.
    """
    c = _census_module()
    full = json.dumps({"envelopes": [
        {"id": 9, "ts": "t", "proto": "korax/0.1", "payload": "B" * 4000}]})
    summary = json.dumps({"envelopes": [
        {"id": 9, "ts": "t", "proto": "korax/0.1", "payload_bytes": 4000}]})

    census = c.Census()
    c._record_envelopes(census, summary, "session-a", len(summary))
    small = census.envelope_bytes[(9, "session-a")]
    census2 = c.Census()
    c._record_envelopes(census2, full, "session-b", len(full))
    big = census2.envelope_bytes[(9, "session-b")]

    assert small < big, (small, big)
    # And not merely different — different by roughly the body.
    assert big - small > 3000, (small, big)


def test_the_largest_delivery_wins_for_one_id_and_session() -> None:
    """A session that drained an id as a summary and later in full needed
    the full one; that is the delivery a de-duplicating design must keep."""
    c = _census_module()
    summary = json.dumps({"envelopes": [
        {"id": 3, "ts": "t", "proto": "korax/0.1", "payload_bytes": 900}]})
    full = json.dumps({"envelopes": [
        {"id": 3, "ts": "t", "proto": "korax/0.1", "payload": "C" * 900}]})
    census = c.Census()
    c._record_envelopes(census, summary, "s", len(summary))
    c._record_envelopes(census, full, "s", len(full))
    after_both = census.envelope_bytes[(3, "s")]
    census_full_only = c.Census()
    c._record_envelopes(census_full_only, full, "s", len(full))
    assert after_both == census_full_only.envelope_bytes[(3, "s")]


def test_an_unreadable_result_is_excluded_and_counted_never_estimated() -> None:
    """The negative that stops the exclusion being silent. An apportioned
    weight would be a second unit error wearing the first one's fix."""
    c = _census_module()
    census = c.Census()
    c._record_envelopes(census, "not json at all {{{", "s", 1234)
    assert census.weight_unreadable_results == 1
    assert census.weight_readable_results == 0
    assert census.weight_unreadable_chars == 1234
    assert not census.envelope_bytes  # nothing invented for it


def test_the_exclusion_bias_check_separates_the_two_populations() -> None:
    """Without this the exclusion is an unbounded bias: if the unreadable
    results were the big ones, the weighted figure would describe a
    different corpus and say so nowhere."""
    c = _census_module()
    census = c.Census()
    good = json.dumps({"envelopes": [
        {"id": 1, "ts": "t", "proto": "korax/0.1", "payload": "D" * 50}]})
    c._record_envelopes(census, good, "s", 10_000)
    c._record_envelopes(census, "<<<broken", "s", 100)
    assert census.weight_readable_chars == 10_000
    assert census.weight_unreadable_chars == 100


# ── ISSUE #3175: refs edge targets are not deliveries ────────────────────


def test_refs_edge_targets_are_not_counted_as_deliveries() -> None:
    """THE CANARY FOR #3175, and the whole reason this extraction changed.

    An envelope's `refs` entries serialise as `{"edge": …, "id": N}`. The
    retired regex matched `"id": N` anywhere in the result and so counted
    every CITATION as a DELIVERY of the cited envelope — measured at 232.6%
    inflation over a 57-file corpus, which moved the duplicate-delivery
    rate from a reported 27.7% to a true 59.1%.

    Reverting `_record_envelopes` to a regex makes this fixture report
    THREE deliveries instead of one; that red-check was run, not assumed.
    """
    c = _census_module()
    raw = json.dumps({"envelopes": [{
        "id": 500, "ts": "t", "proto": "korax/0.1",
        "refs": [{"edge": "closes", "id": 100}, {"edge": "replies", "id": 200}],
        "payload": "x",
    }]})
    census = c.Census()
    c._record_envelopes(census, raw, "s", len(raw))

    assert census.envelope_deliveries == 1, "the envelope, not its citations"
    assert set(census.envelope_sessions) == {500}, census.envelope_sessions
    assert 100 not in census.envelope_sessions
    assert 200 not in census.envelope_sessions


def test_a_payload_quoting_the_json_form_contributes_nothing() -> None:
    """Immune BY CONSTRUCTION rather than by escaping convention (#3181).

    A payload is a string VALUE, not a container, so a walk over parsed
    records never looks inside it. The retired regex survived this case
    only because `json.dumps` escapes the inner quotes — a surface that
    ever delivered text pre-unescaped would have injected phantoms with
    nothing to announce it.

    NOTE this canary is weaker than it looks and is kept for the
    construction rather than the coverage: it also passes against the
    retired regex, because of that escaping. It is `test_refs_…` above
    that fails red when the fix is reverted.
    """
    c = _census_module()
    raw = json.dumps({"envelopes": [{
        "id": 600, "ts": "t", "proto": "korax/0.1",
        "payload": 'quoting the form: {"edge": "replies", "id": 999}',
    }]})
    census = c.Census()
    c._record_envelopes(census, raw, "s", len(raw))
    assert census.envelope_deliveries == 1
    assert 999 not in census.envelope_sessions


def test_an_unparseable_result_contributes_no_deliveries_and_is_counted() -> None:
    """The behaviour the fix genuinely changes, and it moves a denominator.

    The retired regex scraped ids out of text it could not parse. The
    replacement cannot, so those results are EXCLUDED — and an exclusion
    without a count is an unbounded claim, which is why the count and its
    bias check are asserted here rather than trusted.
    """
    c = _census_module()
    census = c.Census()
    c._record_envelopes(census, "{not json at all", "s", 4321)
    assert census.envelope_deliveries == 0
    assert not census.envelope_sessions
    assert census.weight_unreadable_results == 1
    assert census.weight_unreadable_chars == 4321


def test_the_seam_holds_no_accumulator_stores_text() -> None:
    """R156's seam property, RE-DEMONSTRATED rather than inherited (#3176).

    The tool may be run over transcripts carrying sealed mailbox content,
    so it is built to be INCAPABLE of emitting a payload rather than
    careful not to. `_record_envelopes` now parses, which is the one place
    structure is held — so this asserts the property still holds after
    that change instead of assuming the byte path's precedent covers it.
    """
    c = _census_module()
    census = c.Census()
    raw = json.dumps({"envelopes": [{
        "id": 700, "ts": "t", "proto": "korax/0.1",
        "payload": SEAM_CANARY,
    }]})
    c._record_envelopes(census, raw, "s", len(raw))

    import dataclasses  # noqa: PLC0415

    def holds_text(value: object, depth: int = 0) -> bool:
        if depth > 6:
            return False
        if isinstance(value, str):
            return SEAM_CANARY in value
        if isinstance(value, dict):
            return any(holds_text(k, depth + 1) or holds_text(v, depth + 1)
                       for k, v in value.items())
        if isinstance(value, (list, tuple, set)):
            return any(holds_text(v, depth + 1) for v in value)
        return False

    for f in dataclasses.fields(census):
        assert not holds_text(getattr(census, f.name)), f.name
