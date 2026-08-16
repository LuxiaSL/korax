"""Echo-waste canaries — JOB #2702.

The brief requires the matcher be red-checked both directions before the
corpus numbers are believed: a fixture where the echo is KNOWN must count
it, a fixture with NO echo must count zero, and breaking the matcher must
redden the fixture. Every test here is written so it can fail.

The seam tests in `test_transcript_census.py` stay green unmodified; the
new text-touching path (`_echo_of`, which reads both input and result) gets
its own planted-canary test in the same shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "transcript_census.py"

ECHO_CANARY = "ECHOED-PAYLOAD-BODY-DO-NOT-EMIT-4b7e21"
USAGE = {"input_tokens": 10, "output_tokens": 5,
         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}

# Long enough to clear ECHO_MIN_CHARS (200) — short strings are not judged.
LONG = "the quick brown fox jumps over the lazy dog. " * 12


def _assistant(rid: str, blocks: list[dict]) -> str:
    return json.dumps({"type": "assistant", "requestId": rid, "sessionId": "s1",
                       "message": {"role": "assistant", "usage": USAGE,
                                   "content": blocks}})


def _result(tool_use_id: str, text: str) -> str:
    return json.dumps({"type": "user", "sessionId": "s1",
                       "message": {"role": "user",
                                   "content": [{"type": "tool_result",
                                                "tool_use_id": tool_use_id,
                                                "content": text}]}})


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), "--root", str(root), *extra],
                          capture_output=True, text=True, check=False)


def _echo(root: Path) -> dict:
    proc = _run(root, "--json")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["echo"]


def _write(tmp_path: Path, payload: str, result_obj: dict, name: str = "s1") -> None:
    lines = [
        _assistant("r1", [{"type": "tool_use", "id": "tu-1",
                           "name": "mcp__korax__korax_post",
                           "input": {"ns": "/x", "type": "NOTE", "payload": payload}}]),
        _result("tu-1", json.dumps(result_obj, ensure_ascii=False)),
    ]
    (tmp_path / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── positive: a known echo is counted ────────────────────────────────────


def test_a_known_echo_is_counted(tmp_path: Path) -> None:
    _write(tmp_path, LONG, {"id": 1, "ts": "t", "author": "band:a", "payload": LONG})
    v = _echo(tmp_path)["by_verb"]["mcp__korax__korax_post"]
    assert v["judged"] == 1
    assert v["structural_hits"] == 1
    assert v["echoed_chars"] == len(LONG)


def test_no_echo_counts_zero(tmp_path: Path) -> None:
    """The other direction. A result that does NOT contain the input must
    report zero — a matcher that only ever finds echo is not a matcher."""
    _write(tmp_path, LONG, {"id": 1, "ts": "t", "author": "band:a"})
    v = _echo(tmp_path)["by_verb"]["mcp__korax__korax_post"]
    assert v["judged"] == 1
    assert v["structural_hits"] == 0
    assert v["echoed_chars"] == 0


def test_the_matcher_survives_non_ascii(tmp_path: Path) -> None:
    """THE bug that made the first measurement read 1.2% instead of ~89%.

    The result serialises non-ASCII literally while `json.dumps` escapes it
    to `\\uXXXX`, so a string-based matcher misses an echo that is actually
    verbatim. Structural comparison has no escaping question — this fixture
    is full of the em-dashes and box-drawing this corpus actually contains.
    """
    payload = ("── a heading ──\n" + "text — with em-dashes and ═ boxes …\n") * 8
    assert len(payload) >= 200
    _write(tmp_path, payload, {"id": 1, "ts": "t", "payload": payload})
    v = _echo(tmp_path)["by_verb"]["mcp__korax__korax_post"]
    assert v["structural_hits"] == 1, "non-ASCII echo went unseen — the 1.2% bug"
    assert v["echoed_chars"] == len(payload)


def test_a_short_input_is_unjudged_not_counted_as_no_echo(tmp_path: Path) -> None:
    """Short strings collide by chance, so they are excluded — but excluded
    LOUDLY: they must not silently land in the denominator as 'no echo'."""
    _write(tmp_path, "tiny", {"id": 1, "payload": "tiny"})
    by_verb = _echo(tmp_path)["by_verb"]
    assert "mcp__korax__korax_post" not in by_verb or \
        by_verb["mcp__korax__korax_post"]["judged"] == 0


def test_the_threshold_and_method_are_reported_with_the_numbers(
    tmp_path: Path,
) -> None:
    """#2710, applied to myself: a rate without its threshold beside it is
    the defect. Both must be in the machine-readable output."""
    _write(tmp_path, LONG, {"id": 1, "payload": LONG})
    e = _echo(tmp_path)
    assert e["near_match_threshold"] == 0.80
    assert e["echo_min_chars"] == 200
    assert "compared by value" in e["method"]
    human = _run(tmp_path)
    assert "0.8" in human.stdout and "200" in human.stdout


# ── self-read attribution ────────────────────────────────────────────────


def _session_with_band(tmp_path: Path, name: str, band: str,
                       drained: list[tuple[str, str]]) -> None:
    """A session that identifies itself via whoami, then drains envelopes."""
    lines = [
        _assistant("r1", [{"type": "tool_use", "id": "w",
                           "name": "mcp__korax__korax_whoami", "input": {}}]),
        _result("w", json.dumps({"identity": band})),
        _assistant("r2", [{"type": "tool_use", "id": "d",
                           "name": "mcp__korax__korax_read", "input": {"since": 1}}]),
        _result("d", json.dumps({"envelopes": [
            {"id": i, "author": a, "payload": p}
            for i, (a, p) in enumerate(drained, start=100)]})),
    ]
    (tmp_path / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_self_reads_are_split_by_the_sessions_own_band(tmp_path: Path) -> None:
    _session_with_band(tmp_path, "s", "band:me",
                       [("band:me", "x" * 100), ("band:you", "y" * 300)])
    proc = _run(tmp_path, "--json")
    sr = json.loads(proc.stdout)["self_reads"]
    assert sr["sessions_attributed"] == 1
    assert sr["self_envelopes"] == 1 and sr["self_chars"] == 100
    assert sr["other_envelopes"] == 1 and sr["other_chars"] == 300


def test_the_band_is_per_session_not_global(tmp_path: Path) -> None:
    """A first probe hard-coded ONE band across every transcript, which
    measures 'how widely that band is read', not self-read. Two sessions
    with different bands reading each other must be all-other, zero-self."""
    _session_with_band(tmp_path, "a", "band:aaa", [("band:bbb", "x" * 100)])
    _session_with_band(tmp_path, "b", "band:bbb", [("band:aaa", "y" * 100)])
    sr = json.loads(_run(tmp_path, "--json").stdout)["self_reads"]
    assert sr["sessions_attributed"] == 2
    assert sr["self_envelopes"] == 0, "cross-reads counted as self-reads"
    assert sr["other_envelopes"] == 2


def test_an_unattributable_session_is_excluded_not_folded_into_other(
    tmp_path: Path,
) -> None:
    """Folding it into 'other' would understate self-read by exactly the
    traffic we failed to attribute, and the percentage would still look
    like a measurement."""
    lines = [
        _assistant("r1", [{"type": "tool_use", "id": "d",
                           "name": "mcp__korax__korax_read", "input": {"since": 1}}]),
        _result("d", json.dumps({"envelopes": [
            {"id": 1, "author": "band:someone", "payload": "z" * 500}]})),
    ]
    (tmp_path / "anon.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sr = json.loads(_run(tmp_path, "--json").stdout)["self_reads"]
    assert sr["sessions_unattributable"] == 1
    assert sr["sessions_attributed"] == 0
    assert sr["other_envelopes"] == 0, "unattributable traffic leaked into 'other'"
    assert sr["self_envelopes"] == 0


# ── the seam, for the new text-touching path ─────────────────────────────


def test_echo_measurement_emits_no_payload_body(tmp_path: Path) -> None:
    """`_echo_of` reads both the input and the result. A canary planted in
    BOTH must appear in neither the report nor --json."""
    payload = ECHO_CANARY + " " + LONG
    _write(tmp_path, payload, {"id": 1, "ts": "t", "payload": payload})
    human = _run(tmp_path)
    raw = _run(tmp_path, "--json")
    assert human.returncode == 0 and raw.returncode == 0
    assert ECHO_CANARY not in human.stdout, "echo path leaked payload into report"
    assert ECHO_CANARY not in human.stderr
    assert ECHO_CANARY not in raw.stdout, "echo path leaked payload into --json"


def test_the_echo_canary_is_present_in_the_fixture_and_measured(
    tmp_path: Path,
) -> None:
    """Control for the test above: the canary must actually be in the input
    AND the echo must actually have been detected, or the seam test is
    passing because nothing happened (#2518)."""
    payload = ECHO_CANARY + " " + LONG
    _write(tmp_path, payload, {"id": 1, "ts": "t", "payload": payload})
    f = tmp_path / "s1.jsonl"
    assert ECHO_CANARY in f.read_text(encoding="utf-8")
    v = _echo(tmp_path)["by_verb"]["mcp__korax__korax_post"]
    assert v["structural_hits"] == 1, "seam test proved nothing — no echo was measured"


@pytest.mark.parametrize("verb", ["mcp__korax__korax_dm", "mcp__korax__korax_ack"])
def test_other_echoing_verbs_are_measured_not_just_post(
    tmp_path: Path, verb: str
) -> None:
    """The brief names candidates to CHECK, not assume. dm and ack both
    echo in the corpus; this asserts the tool is verb-agnostic."""
    lines = [
        _assistant("r1", [{"type": "tool_use", "id": "t", "name": verb,
                           "input": {"message": LONG}}]),
        _result("t", json.dumps({"id": 1, "payload": LONG}, ensure_ascii=False)),
    ]
    (tmp_path / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert _echo(tmp_path)["by_verb"][verb]["structural_hits"] == 1
