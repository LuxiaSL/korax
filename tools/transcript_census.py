#!/usr/bin/env python3
"""Where the harness's tokens actually go, per tool, per channel — JOB #2679.

Reads the local session transcripts and reports spend decomposed by CLI vs
MCP, by exact command/tool fired, in/out per tool use, and how much is waste.
Feeds the channel commitment (#2614, synthesis #2626/#2631) with measurements
where those had estimates.

═══ THE SEAM IS STRUCTURAL, NOT A HABIT (§8.7, brief §"The seam") ═══

Transcripts contain drained mailbox and offtopic content that is sealed from
the operator ON THE BOARD. An aggregate census must keep that seam even when
the person running it is the operator, so this tool is built to be INCAPABLE
of emitting a payload body rather than careful not to:

  * No accumulator in this file has a `str` payload field. Every counter
    holds ints, and every key is a bounded label.
  * Text reaches exactly three functions — `_bash_label`, `_tool_label`,
    `_record_envelopes` — each of which returns a bounded label, an id, or
    a length, and none of which returns the text it was given.
  * `_bash_label` whitelists its output against `_SAFE_LABEL`; anything else
    becomes `<non-identifier>`. A command carrying a path, a token or a
    quoted payload cannot round-trip through it.
  * `_record_envelopes` PARSES the result rather than scraping it (ISSUE
    #3175). That is the one function here that holds structure, and it holds
    it in a local: it reads `envelope["id"]` and a serialised LENGTH off each
    record, stores ints, and returns None. **It never touches
    `envelope["payload"]`** — which is also why it cannot be fooled by a
    payload that quotes the JSON form, the defect the regex it replaced had
    only by luck of escaping (#3181).

That is the property to check if you review this: grep for a field that
holds text. There should be none.

═══ THE CORRECTNESS TRAP THIS TOOL EXISTS TO AVOID ═══

**The transcript writes MULTIPLE assistant records per API request** — one
per content block group (thinking, tool_use, text) — and repeats the SAME
`usage` object verbatim on each. Measured across the corpus: 1153 of 1153
multi-record requests carry byte-identical usage tuples, zero varying.

So summing `usage` over assistant records DOUBLE-COUNTS, measured at 2.02x
on the sample that found it. Dedup by `requestId` is therefore EXACT, not an
approximation — it is picking one copy of a repeated value, not averaging
competing ones. `--naive-check` prints both totals so the ratio stays
visible rather than being a claim in a docstring.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Iterator

DEFAULT_ROOT = Path.home() / ".claude/projects/-home-luxia-projects-korax"

# A tool-result body above this many characters is reported as a "large
# result". The threshold is STATED because a waste figure whose definition
# is not beside it is the defect (#2667).
LARGE_RESULT_CHARS = 20_000

# Echo waste (JOB #2702). An input field shorter than this is not judged for
# reflection at all: short strings collide by chance ("post", an ns, a band
# id), and counting those as echo would inflate the figure with noise. The
# count of calls excluded for being too small is REPORTED, not hidden.
ECHO_MIN_CHARS = 200

# Similarity above which a NON-JSON result counts as reflecting its input.
# Printed beside every number that depends on it — a near-match percentage
# without its threshold is #2710's defect committed against myself.
NEAR_MATCH_THRESHOLD = 0.80

# Bounded label alphabet. A command token that is not a plain identifier
# never reaches the report.
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9._-]+$")

# ─────────────────────────────────────────────────────────────────────────
# accumulators — every field is an int or a Counter of ints. No text.
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class Denominators:
    """What every count in this report is out of (#2667)."""

    files_found: int = 0
    files_parsed: int = 0
    files_unreadable: int = 0
    lines_read: int = 0
    lines_blank: int = 0
    lines_unparseable: int = 0
    records_by_type: Counter[str] = field(default_factory=Counter)
    assistant_records: int = 0
    distinct_requests: int = 0
    tool_uses: int = 0
    tool_results: int = 0


@dataclass
class ExactTokens:
    """The API's own accounting. EXACT — deduped one record per requestId."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def add(self, u: dict[str, Any]) -> None:
        self.input_tokens += int(u.get("input_tokens") or 0)
        self.output_tokens += int(u.get("output_tokens") or 0)
        self.cache_read_input_tokens += int(u.get("cache_read_input_tokens") or 0)
        self.cache_creation_input_tokens += int(u.get("cache_creation_input_tokens") or 0)

    @property
    def billed_input_total(self) -> int:
        return self.input_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens


@dataclass
class ToolStats:
    """Per-tool character accounting. ESTIMATED — the transcript records no
    per-block token counts, so these are character counts, never tokens."""

    uses: int = 0
    in_chars: int = 0
    out_chars: int = 0
    out_samples: list[int] = field(default_factory=list)

    def add(self, in_chars: int, out_chars: int) -> None:
        self.uses += 1
        self.in_chars += in_chars
        self.out_chars += out_chars
        self.out_samples.append(out_chars)

    def distribution(self) -> dict[str, int]:
        """Median and tails, not averages alone — one 500-envelope drain
        beside many small reads makes a mean that describes nothing."""
        if not self.out_samples:
            return {"median": 0, "p90": 0, "max": 0}
        s = sorted(self.out_samples)
        return {
            "median": int(statistics.median(s)),
            "p90": s[min(len(s) - 1, int(len(s) * 0.9))],
            "max": s[-1],
        }


@dataclass
class EchoStats:
    """Input reflected back as output, per verb — JOB #2702.

    `echoed_chars` counts INPUT characters found again in the result. It is
    a character count, never tokens, and never a share of spend: #2710 is
    the standing correction that a percentage must carry the unit it counts.
    """

    uses: int = 0
    considered: int = 0          # calls with an input field big enough to judge
    structural_hits: int = 0     # result parsed as JSON, an input field echoed
    reverse_hits: int = 0        # a returned value found inside the input text
    near_hits: int = 0           # non-JSON result, similarity >= threshold
    no_echo: int = 0
    in_chars: int = 0
    out_chars: int = 0
    echoed_chars: int = 0


@dataclass
class Census:
    denom: Denominators = field(default_factory=Denominators)
    exact: ExactTokens = field(default_factory=ExactTokens)
    exact_naive: ExactTokens = field(default_factory=ExactTokens)

    by_tool: dict[str, ToolStats] = field(default_factory=lambda: defaultdict(ToolStats))
    by_bash: dict[str, ToolStats] = field(default_factory=lambda: defaultdict(ToolStats))
    korax_cli: dict[str, ToolStats] = field(default_factory=lambda: defaultdict(ToolStats))
    korax_mcp: dict[str, ToolStats] = field(default_factory=lambda: defaultdict(ToolStats))

    # channel accounting (brief §3)
    doorbell_turns: int = 0
    doorbell_exact: ExactTokens = field(default_factory=ExactTokens)
    notification_turns: int = 0
    drain_results: int = 0
    drain_out_chars: int = 0
    envelope_deliveries: int = 0
    # envelope id -> number of DISTINCT sessions that drained it
    envelope_sessions: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))

    # ISSUE #2751 — the byte-weighted view of the same duplication.
    #
    # `(envelope id, session) -> largest delivered size for that pair`. Largest
    # rather than first or sum: a session that drained an id as a summary and
    # later in full needed the full one, and that is the delivery a
    # de-duplicating design would have to preserve for it.
    #
    # Keyed on (id, session) and not on delivery, so this stays comparable to
    # the count above — which dedupes by session, so intra-session re-drains
    # are not redundancy in either figure.
    envelope_bytes: dict[tuple[int, str], int] = field(default_factory=dict)
    #: Drain results whose body could not be read structurally. These are
    #: EXCLUDED from the weighted figure and reported, never estimated — an
    #: apportioned byte weight would be a second unit error wearing the first
    #: one's fix (#2751's own caveat, #2752 made it binding).
    weight_unreadable_results: int = 0
    weight_readable_results: int = 0
    #: Sizes of the two populations. Without this the exclusion above is an
    #: unbounded bias: if the unreadable results are systematically the big
    #: ones, a weighted figure computed on what is left describes a different
    #: corpus and says so nowhere.
    weight_unreadable_chars: int = 0
    weight_readable_chars: int = 0

    large_results: int = 0
    large_result_chars: int = 0

    sessions: set[str] = field(default_factory=set)
    subagent_files: int = 0
    toplevel_files: int = 0

    # echo waste (JOB #2702)
    echo: dict[str, EchoStats] = field(default_factory=lambda: defaultdict(EchoStats))
    # self-reads: drained envelopes authored by the band that ran the drain
    self_read_envelopes: int = 0
    self_read_chars: int = 0
    other_read_envelopes: int = 0
    other_read_chars: int = 0
    sessions_with_known_band: int = 0
    sessions_without_known_band: int = 0


# ─────────────────────────────────────────────────────────────────────────
# the three functions text is allowed to touch. None returns its input.
# ─────────────────────────────────────────────────────────────────────────


# The korax CLI's subcommands, as declared by `sub.add_parser(...)` in
# `clients/cli/korax_cli/cli.py`. This is a RECOGNISER, not a guess, and
# `test_the_subcommand_set_matches_the_cli_source` re-derives it from that
# file so the two cannot drift apart silently.
#
# It replaces an earlier flag-whitelist approach that was wrong in a way
# worth recording: the first run reported `korax-dev-enactor-vesper` as a
# subcommand (it is the argument to `--as`), and patching that with a list
# of value-taking flags left `45` as a subcommand with 80 uses (it is the
# argument to `--limit`). Enumerating the flags is unbounded; enumerating
# the subcommands is bounded, and anything unrecognised is reported as
# such instead of being silently believed.
_KORAX_SUBCOMMANDS = frozenset({
    "ack", "attach", "auth", "brief", "bump", "conformance", "conventions",
    "dm", "docket", "enlist", "envelope", "fetch", "grant", "identities",
    "identity", "invite", "list", "neighbourhood", "new", "onboard", "policy",
    "post", "provision", "read", "release", "rotate", "save", "search",
    "subscribe", "unsubscribe", "view", "wait", "watch", "whoami", "why",
})


def _bash_label(command: str) -> tuple[str, str | None]:
    """A Bash command -> (leading token, korax subcommand or None).

    Returns BOUNDED LABELS ONLY. The command text does not survive this
    call, and any token that is not a plain identifier is replaced with
    `<non-identifier>` so a path, a URL or a quoted payload cannot leak
    into the report through a command line.

    Two things learned from the corpus rather than assumed:

    * `cd /some/path && real-command ...` is the dominant Bash shape here
      (4,937 of 13,445 uses in the first full run). Reporting `cd` as the
      leading token hid a third of all commands behind a directory change,
      so the `cd ... &&` prefix is stepped over to reach the real head.
    * Flag ARGUMENTS look exactly like subcommands to a naive scan
      (`--as korax-dev-enactor-vesper`, `--limit 45`), so the subcommand is
      recognised against the CLI's declared set rather than guessed at by
      position.
    """
    parts = command.strip().split()
    # step over `cd <path> &&` (possibly repeated) to the command that matters
    while len(parts) >= 3 and parts[0] == "cd" and parts[2] in {"&&", ";"}:
        parts = parts[3:]
    if not parts:
        return ("<empty>", None)
    head = parts[0]
    if not _SAFE_LABEL.match(head):
        return ("<non-identifier>", None)
    if head != "korax":
        return (head, None)
    for tok in parts[1:]:
        if tok in _KORAX_SUBCOMMANDS:
            return ("korax", tok)
    # A korax invocation whose subcommand we do not recognise is reported as
    # unrecognised, never as whatever token happened to come first.
    return ("korax", "<unrecognised>")


def _tool_label(name: str) -> tuple[str, str | None]:
    """A tool name -> (channel, verb). `mcp__korax__korax_read` is already a
    bounded identifier; this only splits it."""
    if name.startswith("mcp__"):
        bits = name.split("__")
        if len(bits) >= 3:
            return (f"mcp:{bits[1]}", "__".join(bits[2:]))
        return ("mcp:?", name)
    return ("builtin", name)


def _iter_strings(node: Any, depth: int = 0) -> Iterator[str]:
    """Every string VALUE in a parsed structure. Yields text to the caller in
    this file only, which compares lengths and equality and stores neither."""
    if depth > 8:
        return
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _iter_strings(v, depth + 1)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_strings(v, depth + 1)


def _echo_of(inp: Any, out_text: str) -> tuple[int, str]:
    """How many INPUT characters come back in the result -> (chars, mode).

    **Structural, not substring, and that distinction is the whole finding.**
    A first cut compared the input payload against the raw result text and
    reported 1.2% echo for `korax_post` while input and output were the same
    size to within 7%. Both string forms miss it: the result serialises
    non-ASCII literally (this corpus is full of em-dashes and box-drawing),
    so `json.dumps(payload)`'s `\\uXXXX` escaping does not match, and raw
    matching fails on the newline escaping. Parsing the result and comparing
    FIELD VALUES is exact and has no escaping question at all.

    Falls back to a similarity ratio only when the result is not JSON. The
    threshold is a module constant and is printed beside every number that
    depends on it (#2667, #2710).

    Returns a count and a mode label. It never returns the text it compared.
    """
    if not isinstance(inp, dict):
        return (0, "no-input")
    sent = [v for v in inp.values() if isinstance(v, str) and len(v) >= ECHO_MIN_CHARS]
    if not sent:
        return (0, "too-small-to-judge")

    try:
        doc = json.loads(out_text)
    except (json.JSONDecodeError, ValueError):
        doc = None

    if doc is not None:
        returned = set(_iter_strings(doc))
        echoed = sum(len(s) for s in sent if s in returned)
        if echoed:
            return (echoed, "structural")

        # REVERSE CONTAINMENT, and it exists because the forward test
        # produced a FALSE REFUTATION. Bash showed 0.0% echo, which reads as
        # "the CLI does not echo" — but `cmd_post` calls `rt.emit(body)` and
        # emits the whole envelope exactly as the MCP verb does (checked in
        # `clients/cli/korax_cli/cli.py:183`, not inferred from the table).
        # The forward test cannot see it: a Bash call's input is one
        # shell-quoted command string, so the payload is never EQUAL to a
        # field. Asking instead whether a returned value appears INSIDE the
        # input text is immune to quoting, and it is what makes CLI and MCP
        # comparable at all.
        blob = json.dumps(inp, ensure_ascii=False)
        back = sum(len(s) for s in returned if len(s) >= ECHO_MIN_CHARS and s in blob)
        if back:
            return (back, "reverse")
        return (0, "none")

    # non-JSON result: near match, threshold stated
    best = 0
    for s in sent:
        ratio = difflib.SequenceMatcher(None, s, out_text).ratio()
        if ratio >= NEAR_MATCH_THRESHOLD:
            best = max(best, len(s))
    return (best, "near" if best else "none")


# ─────────────────────────────────────────────────────────────────────────


def _content_chars(content: Any) -> int:
    """Character length of a tool result, whatever shape it arrives in.
    Returns an int; the text does not survive."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for b in content:
            if isinstance(b, dict):
                t = b.get("text")
                total += len(t) if isinstance(t, str) else len(json.dumps(b))
            else:
                total += len(str(b))
        return total
    return len(json.dumps(content))


def _classify_user_text(text: str) -> str | None:
    """Structural classification of a user record. Returns a bounded label."""
    head = text[:240]
    if head.startswith("<channel"):
        return "doorbell"
    if "[SYSTEM NOTIFICATION" in head or "<task-notification>" in head:
        return "notification"
    if head.startswith("<local-command"):
        return "local-command"
    return None


def iter_records(path: Path, census: Census) -> Iterator[dict[str, Any]]:
    """Stream one file. Files run to tens of MiB — never load one whole."""
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError as exc:  # unreadable file is COUNTED and NAMED, not dropped
        census.denom.files_unreadable += 1
        print(f"  [skip] {path.name}: {exc}", file=sys.stderr)
        return
    with handle as fh:
        census.denom.files_parsed += 1
        for line in fh:
            census.denom.lines_read += 1
            s = line.strip()
            if not s:
                census.denom.lines_blank += 1
                continue
            try:
                rec = json.loads(s)
            except (json.JSONDecodeError, ValueError):
                census.denom.lines_unparseable += 1
                continue
            if not isinstance(rec, dict):
                census.denom.lines_unparseable += 1
                continue
            yield rec


def scan_file(path: Path, census: Census, seen_requests: set[str]) -> None:
    session = path.stem
    census.sessions.add(session)
    pending_user_kind: str | None = None
    # tool_use id -> (channel, verb, tool name, input) so a result can be
    # attributed to its call — the name makes per-tool out-chars possible,
    # the input makes echo measurable
    call_labels: dict[str, tuple[str, str | None, str, Any]] = {}

    # SELF-READ ATTRIBUTION, per session (JOB #2702).
    # "A session draining envelopes it authored itself" needs to know which
    # band the session was acting as, and that is NOT a constant across the
    # corpus: each transcript is a different band's session. A first probe
    # hard-coded one band id and so measured "how widely quill is read"
    # rather than self-read — the number looked plausible and answered the
    # wrong question. The acting band is inferred from the `author` the
    # board stamped on this session's own accepted posts.
    acting_bands: set[str] = set()
    drained: list[tuple[str, int]] = []

    for rec in iter_records(path, census):
        rtype = rec.get("type")
        census.denom.records_by_type[str(rtype)] += 1
        msg = rec.get("message")

        if rtype == "user" and isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                pending_user_kind = _classify_user_text(content)
                if pending_user_kind == "doorbell":
                    census.doorbell_turns += 1
                elif pending_user_kind == "notification":
                    census.notification_turns += 1
            elif isinstance(content, list):
                for blk in content:
                    if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                        continue
                    census.denom.tool_results += 1
                    raw = blk.get("content")
                    out_chars = _content_chars(raw)
                    label = call_labels.pop(str(blk.get("tool_use_id")), None)
                    if label is None:
                        continue
                    channel, verb, name, call_input = label
                    _record_echo(census, name, call_input, raw, out_chars,
                                 acting_bands, drained)
                    # Attribute the result's SIZE back to the tool that
                    # made the call. Without this the per-tool `out chars`
                    # column is structurally always zero — a column that
                    # cannot report anything but 0 is not a measurement,
                    # and the first full run printed exactly that.
                    st = census.by_tool[name]
                    st.out_chars += out_chars
                    st.out_samples.append(out_chars)
                    _record_result(census, channel, verb, out_chars, raw, session)
            continue

        if rtype != "assistant" or not isinstance(msg, dict):
            continue

        census.denom.assistant_records += 1
        rid = rec.get("requestId")
        usage = msg.get("usage")

        if isinstance(usage, dict):
            # NAIVE total kept deliberately so the 2x trap stays visible.
            census.exact_naive.add(usage)
            if rid and rid not in seen_requests:
                seen_requests.add(rid)
                census.denom.distinct_requests += 1
                census.exact.add(usage)
                if pending_user_kind in {"doorbell", "notification"}:
                    census.doorbell_exact.add(usage)
            elif not rid:
                census.denom.distinct_requests += 1
                census.exact.add(usage)

        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                continue
            census.denom.tool_uses += 1
            name = str(blk.get("name") or "<unnamed>")
            inp = blk.get("input")
            in_chars = len(json.dumps(inp, ensure_ascii=False)) if inp is not None else 0
            channel, verb = _tool_label(name)

            if name == "Bash" and isinstance(inp, dict):
                cmd = inp.get("command")
                if isinstance(cmd, str):
                    head, sub = _bash_label(cmd)
                    if head == "korax":
                        channel, verb = ("cli:korax", sub or "<bare>")
                    else:
                        census.by_bash[head].add(in_chars, 0)

            call_labels[str(blk.get("id"))] = (channel, verb, name, inp)
            census.by_tool[name].add(in_chars, 0)
            if channel == "cli:korax":
                census.korax_cli[str(verb)].add(in_chars, 0)
            elif channel == "mcp:korax":
                census.korax_mcp[str(verb)].add(in_chars, 0)
        pending_user_kind = None

    _attribute_self_reads(census, acting_bands, drained)


def _record_echo(
    census: Census,
    name: str,
    call_input: Any,
    raw: Any,
    out_chars: int,
    acting_bands: set[str],
    drained: list[tuple[str, int]],
) -> None:
    """Echo accounting for one call/result pair (JOB #2702).

    Everything here computes on text and stores only integers and the
    bounded verb name — the seam the census already holds (§8.7).
    """
    st = census.echo[name]
    st.uses += 1
    st.out_chars += out_chars
    if isinstance(call_input, dict):
        st.in_chars += sum(len(v) for v in call_input.values() if isinstance(v, str))

    out_text = raw if isinstance(raw, str) else ""
    if not isinstance(raw, str) and isinstance(raw, list):
        out_text = "".join(
            b.get("text", "") for b in raw if isinstance(b, dict) and isinstance(b.get("text"), str)
        )

    if out_text:
        echoed, mode = _echo_of(call_input, out_text)
        if mode not in {"no-input", "too-small-to-judge"}:
            st.considered += 1
            if mode == "structural":
                st.structural_hits += 1
            elif mode == "reverse":
                st.reverse_hits += 1
            elif mode == "near":
                st.near_hits += 1
            else:
                st.no_echo += 1
            st.echoed_chars += echoed

    # Learn which band this session acts as, from the board's own stamp on
    # an accepted post — and collect drained envelopes for attribution once
    # the whole file has been read.
    if not out_text:
        return
    try:
        doc = json.loads(out_text)
    except (json.JSONDecodeError, ValueError):
        return
    if not isinstance(doc, dict):
        return

    # Three independent witnesses to "which band is this session acting as",
    # because one of them alone covered only 18 of 55 sessions and a rate
    # computed over a third of the corpus is not a corpus rate:
    #   post   — the board's own `author` stamp on an accepted envelope
    #   whoami — `identity`, the connection's own answer
    #   animate/enlist — `id`, the band just bound
    if "post" in name and isinstance(doc.get("author"), str) and doc.get("id") is not None:
        acting_bands.add(doc["author"])
    ident = doc.get("identity")
    if isinstance(ident, str) and ident.startswith("band:"):
        acting_bands.add(ident)
    bid = doc.get("id")
    if isinstance(bid, str) and bid.startswith("band:"):
        acting_bands.add(bid)

    envs = doc.get("envelopes")
    if isinstance(envs, list):
        for env in envs:
            if not isinstance(env, dict):
                continue
            author = env.get("author")
            payload = env.get("payload")
            if isinstance(author, str):
                drained.append((author, len(payload) if isinstance(payload, str) else 0))


def _attribute_self_reads(
    census: Census, acting_bands: set[str], drained: list[tuple[str, int]]
) -> None:
    """Split a session's drained envelopes into its own and other people's.

    **A session whose acting band could not be inferred is COUNTED AND
    EXCLUDED, never folded into 'other'.** Folding it in would quietly
    understate self-read by exactly the traffic we failed to attribute, and
    the resulting percentage would look like a measurement of the world.
    """
    if not acting_bands:
        census.sessions_without_known_band += 1
        return
    census.sessions_with_known_band += 1
    for author, chars in drained:
        if author in acting_bands:
            census.self_read_envelopes += 1
            census.self_read_chars += chars
        else:
            census.other_read_envelopes += 1
            census.other_read_chars += chars


def _record_result(
    census: Census, channel: str, verb: str | None, out_chars: int, raw: Any, session: str
) -> None:
    """Attribute a tool result's SIZE to its call. `raw` is inspected for
    envelope ids and discarded; it is never stored."""
    if out_chars >= LARGE_RESULT_CHARS:
        census.large_results += 1
        census.large_result_chars += out_chars

    target: dict[str, ToolStats] | None = None
    if channel == "cli:korax":
        target = census.korax_cli
    elif channel == "mcp:korax":
        target = census.korax_mcp
    if target is not None and verb is not None:
        st = target[str(verb)]
        st.uses = max(st.uses, 1)
        st.out_chars += out_chars
        st.out_samples.append(out_chars)

    is_drain = verb is not None and any(
        k in str(verb) for k in ("read", "watch", "wait", "docket", "onboard", "view")
    )
    if not (channel in {"cli:korax", "mcp:korax"} and is_drain):
        return

    census.drain_results += 1
    census.drain_out_chars += out_chars
    if isinstance(raw, str):
        _record_envelopes(census, raw, session, out_chars)


def _record_envelopes(
    census: Census, raw: str, session: str, out_chars: int
) -> None:
    """Count deliveries and weigh them, from ONE parse of the result.

    **THIS REPLACES A REGEX THAT COUNTED `refs` EDGE TARGETS AS DELIVERIES**
    (ISSUE #3175). `_ENVELOPE_ID` matched `"id"\\s*:\\s*N` anywhere in the
    serialised text, and an envelope's `refs` entries are `{"edge": …,
    "id": N}` — so every citation an envelope carried was counted as a
    delivery of the cited envelope. Measured inflation on a 57-file corpus:
    **24,022 naive deliveries against 7,236 real ones, 232.6%**, which moved
    the duplicate-delivery rate from a reported 27.7% to a true 58.0%.

    **The deeper defect was that this file had TWO extractions.** The byte
    path already recognised envelopes by SHAPE and was correct from the day
    it landed; the count path used the regex and was wrong for four hours in
    the same file over the same results, **and nothing here could notice the
    disagreement.** One extraction cannot silently disagree with itself, so
    both measurements now come from one walk over one parse.

    **Not "cleaner" — the regex is correct only by accident of an escaping
    convention it does not know about.** A payload quoting the JSON form
    serialises as `\\"id\\": N` and happens not to match; a surface that ever
    delivered text pre-unescaped would inject phantoms and nothing would
    announce it. Reading `envelope["id"]` off a parsed record cannot see
    inside a payload at all, because a payload is a string VALUE and not a
    container. Immune by construction rather than by convention (#3181).

    **The seam is unchanged and is re-demonstrated, not inherited:** this
    parses into locals, reads ints and lengths off them, and retains
    neither. No accumulator here holds text.
    """
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        # A result that cannot be read structurally contributes NOTHING and
        # is counted, never apportioned or regex-scraped as a fallback. A
        # fallback would reintroduce exactly the defect above on precisely
        # the inputs nobody is checking.
        census.weight_unreadable_results += 1
        census.weight_unreadable_chars += out_chars
        return
    census.weight_readable_results += 1
    census.weight_readable_chars += out_chars

    for env in _envelope_records(parsed):
        eid = env.get("id")
        if not isinstance(eid, int):
            continue
        census.envelope_deliveries += 1
        census.envelope_sessions[eid].add(session)
        size = len(json.dumps(env, ensure_ascii=False))
        key = (eid, session)
        if size > census.envelope_bytes.get(key, 0):
            census.envelope_bytes[key] = size


def _envelope_records(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every envelope-shaped dict anywhere in a parsed result.

    Recursive because the shape differs by surface and by verb: `/read` puts
    them under `envelopes`, reductions nest them under `output`, and a single
    `korax envelope` call returns one bare. Recognising them by SHAPE rather
    than by key name is why this does not need a list of surfaces to keep
    current — and the same reason it cannot be fooled by a payload that
    happens to contain the word `envelopes` (#2762's family: a reader keyed
    on a name goes quiet when the name changes).
    """
    if isinstance(node, dict):
        if "id" in node and "ts" in node and ("proto" in node or "type" in node):
            yield node
            return
        for value in node.values():
            yield from _envelope_records(value)
    elif isinstance(node, list):
        for item in node:
            yield from _envelope_records(item)


def run(root: Path) -> Census:
    census = Census()
    files = sorted(root.rglob("*.jsonl"))
    census.denom.files_found = len(files)
    census.toplevel_files = sum(1 for f in files if f.parent == root)
    census.subagent_files = len(files) - census.toplevel_files

    seen_requests: set[str] = set()
    for path in files:
        scan_file(path, census, seen_requests)
    return census


# ─────────────────────────────────────────────────────────────────────────
# report — labels on every number, denominators beside every count
# ─────────────────────────────────────────────────────────────────────────


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def report(census: Census, root: Path, naive_check: bool) -> None:
    d = census.denom
    e = census.exact
    out = print

    out("═" * 72)
    out("TRANSCRIPT TOKEN CENSUS — korax project sessions")
    out(f"root: {root}")
    out("═" * 72)

    out("\n── DENOMINATORS (what every number below is out of) ──")
    out(f"  files found            {d.files_found}   "
        f"({census.toplevel_files} top-level + {census.subagent_files} subagent)")
    out(f"  files parsed           {d.files_parsed}")
    out(f"  files unreadable       {d.files_unreadable}")
    out(f"  lines read             {d.lines_read:,}")
    out(f"  lines blank            {d.lines_blank:,}")
    out(f"  lines UNPARSEABLE      {d.lines_unparseable:,}   "
        "(counted and named, never silently dropped)")
    out(f"  assistant records      {d.assistant_records:,}")
    out(f"  distinct API requests  {d.distinct_requests:,}   <- the real denominator")
    out(f"  tool uses              {d.tool_uses:,}")
    out(f"  tool results matched   {d.tool_results:,}")
    out(f"  sessions               {len(census.sessions)}")

    out("\n── EXACT TOKENS (the API's own accounting, deduped by requestId) ──")
    out(f"  input (uncached)       {e.input_tokens:,}")
    out(f"  cache read             {e.cache_read_input_tokens:,}")
    out(f"  cache creation         {e.cache_creation_input_tokens:,}")
    out(f"  output                 {e.output_tokens:,}")
    out(f"  billed input total     {e.billed_input_total:,}")

    if naive_check:
        n = census.exact_naive
        ratio = n.output_tokens / e.output_tokens if e.output_tokens else 0.0
        out("\n  ── the double-count control ──")
        out(f"  NAIVE sum over assistant records: output {n.output_tokens:,}")
        out(f"  DEDUPED by requestId:             output {e.output_tokens:,}")
        out(f"  naive/deduped = {ratio:.2f}x  — the transcript repeats one")
        out("  request's usage on each of its records; dedup is EXACT, not")
        out("  an estimate, because the repeated values are identical.")

    out("\n── CACHE (exact; the usage fields' own rates) ──")
    cached = e.cache_read_input_tokens
    out(f"  cache-read share of billed input   {_pct(cached, e.billed_input_total)}"
        f"   ({cached:,} of {e.billed_input_total:,})")
    out(f"  full-rate share                    "
        f"{_pct(e.input_tokens + e.cache_creation_input_tokens, e.billed_input_total)}")

    out("\n── PER-TOOL, BY USE COUNT (in/out are CHARACTER estimates) ──")
    out("  ESTIMATED: the transcript records no per-block token counts.")
    out(f"  {'tool':32} {'uses':>6} {'in chars':>12} {'out chars':>13}")
    for name, st in sorted(census.by_tool.items(), key=lambda kv: -kv[1].uses)[:20]:
        out(f"  {name[:32]:32} {st.uses:>6} {st.in_chars:>12,} {st.out_chars:>13,}")

    out("\n── KORAX BY CLI vs BY MCP (the headline cut) ──")
    cli_uses = sum(s.uses for s in census.korax_cli.values())
    mcp_uses = sum(s.uses for s in census.korax_mcp.values())
    cli_out = sum(s.out_chars for s in census.korax_cli.values())
    mcp_out = sum(s.out_chars for s in census.korax_mcp.values())
    out(f"  CLI  uses {cli_uses:>6}   out chars {cli_out:>13,}")
    out(f"  MCP  uses {mcp_uses:>6}   out chars {mcp_out:>13,}")

    out(f"\n  {'verb':24} {'chan':5} {'uses':>6} {'out chars':>13} "
        f"{'median':>9} {'p90':>9} {'max':>9}")
    rows: list[tuple[str, str, ToolStats]] = []
    rows += [(v, "CLI", s) for v, s in census.korax_cli.items()]
    rows += [(v, "MCP", s) for v, s in census.korax_mcp.items()]
    for verb, chan, st in sorted(rows, key=lambda r: -r[2].out_chars)[:24]:
        dist = st.distribution()
        out(f"  {verb[:24]:24} {chan:5} {st.uses:>6} {st.out_chars:>13,} "
            f"{dist['median']:>9,} {dist['p90']:>9,} {dist['max']:>9,}")
    out("\n  Distribution shown because averages describe nothing here: one")
    out("  500-envelope drain sits beside many small reads.")

    out("\n── BASH, BY LEADING TOKEN (non-korax) ──")
    for head, st in sorted(census.by_bash.items(), key=lambda kv: -kv[1].uses)[:12]:
        out(f"  {head[:28]:28} {st.uses:>6} uses")

    out("\n── CHANNEL ACCOUNTING (brief §3, for the #2626 thread) ──")
    db = census.doorbell_exact
    out(f"  (a) doorbell turns                 {census.doorbell_turns:,}")
    out(f"      task-notification turns        {census.notification_turns:,}")
    out(f"      EXACT tokens on those turns    input {db.billed_input_total:,}  "
        f"output {db.output_tokens:,}")
    out(f"      share of all billed input      {_pct(db.billed_input_total, e.billed_input_total)}")
    out("      Each such turn bills the whole context as input, which is")
    out("      why the full-turn cost is the figure and not the message size.")
    out(f"  (b) drain results                  {census.drain_results:,}")
    out(f"      chars delivered through drains {census.drain_out_chars:,}")
    out(f"  (c) envelope deliveries observed   {census.envelope_deliveries:,}")
    multi = {k: v for k, v in census.envelope_sessions.items() if len(v) > 1}
    redundant = sum(len(v) - 1 for v in multi.values())
    out(f"      distinct envelope ids seen     {len(census.envelope_sessions):,}")
    out(f"      ids drained by >1 session      {len(multi):,}")
    out(f"      redundant deliveries           {redundant:,}   "
        f"({_pct(redundant, census.envelope_deliveries)} of deliveries)")

    out("\n── WASTE, EACH WITH ITS DEFINITION AND DENOMINATOR (#2667) ──")
    out("  duplicate drains: an envelope id delivered to N>1 distinct sessions,")
    out("    counted as N-1 redundant deliveries.")
    out(f"    {redundant:,} of {census.envelope_deliveries:,} deliveries "
        f"= {_pct(redundant, census.envelope_deliveries)}")

    # ISSUE #2751 — the same duplication, weighted by what it actually cost.
    by_id: dict[int, list[int]] = defaultdict(list)
    for (eid, _session), size in census.envelope_bytes.items():
        by_id[eid].append(size)
    weighted_total = sum(sum(v) for v in by_id.values())
    # Savings from de-duplicating: every delivery of an id except the one that
    # has to survive. Keeping the LARGEST is the conservative choice — a
    # session that needed the body must still get it — so this is a LOWER
    # bound on what removal is worth, and the max/min pair below is the range
    # rather than a single number pretending to be exact.
    weighted_redundant = sum(sum(v) - max(v) for v in by_id.values() if len(v) > 1)
    weighted_redundant_hi = sum(sum(v) - min(v) for v in by_id.values() if len(v) > 1)
    out("  duplicate drains, BYTE-WEIGHTED (#2751): the same ids, weighted by")
    out("    each delivery's own serialised size instead of counted as 1 each.")
    out(f"    {weighted_redundant:,} of {weighted_total:,} envelope chars "
        f"= {_pct(weighted_redundant, weighted_total)}"
        f"   (keeping the largest delivery of each id)")
    out(f"    upper bound if the SMALLEST is kept instead: "
        f"{weighted_redundant_hi:,} = {_pct(weighted_redundant_hi, weighted_total)}")
    rd_n, un_n = census.weight_readable_results, census.weight_unreadable_results
    rd_c, un_c = census.weight_readable_chars, census.weight_unreadable_chars
    out(f"    measured on {rd_n:,} structurally readable drain results; "
        f"{un_n:,} EXCLUDED as unreadable "
        f"({_pct(un_n, rd_n + un_n)} of drain results)")
    out(f"    EXCLUSION BIAS CHECK — mean result size, readable "
        f"{(rd_c // rd_n) if rd_n else 0:,} chars vs excluded "
        f"{(un_c // un_n) if un_n else 0:,} chars; excluded hold "
        f"{_pct(un_c, rd_c + un_c)} of drain chars")
    out("    (excluded, never apportioned: an estimated byte weight would be a")
    out("     second unit error wearing the first one's fix — #2751's caveat,")
    out("     made binding at #2752.)")
    out("  doorbell-only turn cost: billed input on turns whose triggering")
    out("    user record was a doorbell or task-notification.")
    out(f"    {db.billed_input_total:,} of {e.billed_input_total:,} billed input "
        f"= {_pct(db.billed_input_total, e.billed_input_total)}")
    out(f"  large tool results: a single result >= {LARGE_RESULT_CHARS:,} chars.")
    out(f"    {census.large_results:,} of {d.tool_results:,} results "
        f"= {_pct(census.large_results, d.tool_results)}, "
        f"{census.large_result_chars:,} chars")
    out("  cache misses: billed input NOT served from cache.")
    out(f"    {e.input_tokens + e.cache_creation_input_tokens:,} of "
        f"{e.billed_input_total:,} = "
        f"{_pct(e.input_tokens + e.cache_creation_input_tokens, e.billed_input_total)}")
    out("\n── ECHO WASTE: INPUT REFLECTED BACK AS OUTPUT (JOB #2702) ──")
    out("  Method: result parsed as JSON, input FIELDS compared by value —")
    out("  exact, no escaping question. Non-JSON results fall back to a")
    out(f"  similarity ratio >= {NEAR_MATCH_THRESHOLD}. Input fields shorter than")
    out(f"  {ECHO_MIN_CHARS} chars are not judged (short strings collide by chance);")
    out("  those calls appear as 'unjudged' and are excluded from the rates.")
    out("  `reverse` counts a RETURNED value found inside the input text —")
    out("  the only way a shell-quoted CLI call's echo is visible at all.")
    out(f"\n  {'verb':30} {'uses':>6} {'judged':>7} {'struct':>7} {'revrs':>6} "
        f"{'near':>5} {'echoed ch':>11} {'of out':>7}")
    echo_rows = sorted(census.echo.items(), key=lambda kv: -kv[1].echoed_chars)
    tot_echo = tot_out = 0
    for name, es in echo_rows[:16]:
        if es.considered == 0 and es.echoed_chars == 0:
            continue
        out(f"  {name[:30]:30} {es.uses:>6} {es.considered:>7} {es.structural_hits:>7} "
            f"{es.reverse_hits:>6} {es.near_hits:>5} {es.echoed_chars:>11,} "
            f"{_pct(es.echoed_chars, es.out_chars):>7}")
    for es in census.echo.values():
        tot_echo += es.echoed_chars
        tot_out += es.out_chars
    out(f"\n  corpus-wide: {tot_echo:,} echoed of {tot_out:,} tool-result chars "
        f"= {_pct(tot_echo, tot_out)}")

    out("\n── SELF-READS: DRAINS RETURNING THE READER'S OWN TEXT ──")
    tot_read = census.self_read_chars + census.other_read_chars
    out(f"  sessions with acting band inferred   {census.sessions_with_known_band}")
    out(f"  sessions NOT attributable (excluded) {census.sessions_without_known_band}")
    out(f"  own envelopes    {census.self_read_envelopes:>7}   "
        f"payload chars {census.self_read_chars:>12,}")
    out(f"  others'          {census.other_read_envelopes:>7}   "
        f"payload chars {census.other_read_chars:>12,}")
    out(f"  own share of drained payload chars   "
        f"{_pct(census.self_read_chars, tot_read)}")
    out("  The acting band is inferred from the board's own `author` stamp on")
    out("  this session's accepted posts — not assumed, and not constant")
    out("  across the corpus, since each transcript is a different band.")

    out("\n  Not measurable from this corpus, stated rather than forced:")
    out("  per-tool TOKEN cost (no per-block counts exist in the transcript),")
    out("  and watch-supervisor wakes that never entered a session (they are")
    out("  in the supervisor's own log, not here).")
    out("")


def to_json(census: Census) -> dict[str, Any]:
    d, e = census.denom, census.exact
    multi = {k: v for k, v in census.envelope_sessions.items() if len(v) > 1}
    return {
        "denominators": {
            "files_found": d.files_found,
            "files_toplevel": census.toplevel_files,
            "files_subagent": census.subagent_files,
            "files_parsed": d.files_parsed,
            "files_unreadable": d.files_unreadable,
            "lines_read": d.lines_read,
            "lines_blank": d.lines_blank,
            "lines_unparseable": d.lines_unparseable,
            "assistant_records": d.assistant_records,
            "distinct_requests": d.distinct_requests,
            "tool_uses": d.tool_uses,
            "tool_results": d.tool_results,
            "sessions": len(census.sessions),
            "records_by_type": dict(d.records_by_type),
        },
        "exact_tokens": {
            "basis": "message.usage, deduped one record per requestId",
            "input_tokens": e.input_tokens,
            "cache_read_input_tokens": e.cache_read_input_tokens,
            "cache_creation_input_tokens": e.cache_creation_input_tokens,
            "output_tokens": e.output_tokens,
            "billed_input_total": e.billed_input_total,
            "naive_output_tokens": census.exact_naive.output_tokens,
        },
        "estimated_chars_by_tool": {
            n: {"uses": s.uses, "in_chars": s.in_chars, "out_chars": s.out_chars}
            for n, s in census.by_tool.items()
        },
        "korax_cli": {
            v: {"uses": s.uses, "in_chars": s.in_chars, "out_chars": s.out_chars,
                **s.distribution()}
            for v, s in census.korax_cli.items()
        },
        "korax_mcp": {
            v: {"uses": s.uses, "in_chars": s.in_chars, "out_chars": s.out_chars,
                **s.distribution()}
            for v, s in census.korax_mcp.items()
        },
        "channel": {
            "doorbell_turns": census.doorbell_turns,
            "notification_turns": census.notification_turns,
            "doorbell_billed_input": census.doorbell_exact.billed_input_total,
            "doorbell_output": census.doorbell_exact.output_tokens,
            "drain_results": census.drain_results,
            "drain_out_chars": census.drain_out_chars,
            "envelope_deliveries": census.envelope_deliveries,
            "distinct_envelope_ids": len(census.envelope_sessions),
            "ids_drained_by_multiple_sessions": len(multi),
            "redundant_deliveries": sum(len(v) - 1 for v in multi.values()),
        },
        "waste": {
            "large_result_threshold_chars": LARGE_RESULT_CHARS,
            "large_results": census.large_results,
            "large_result_chars": census.large_result_chars,
        },
        "echo": {
            "method": "result parsed as JSON, input fields compared by value",
            "echo_min_chars": ECHO_MIN_CHARS,
            "near_match_threshold": NEAR_MATCH_THRESHOLD,
            "by_verb": {
                n: {
                    "uses": s.uses,
                    "judged": s.considered,
                    "structural_hits": s.structural_hits,
                    "reverse_hits": s.reverse_hits,
                    "near_hits": s.near_hits,
                    "no_echo": s.no_echo,
                    "in_chars": s.in_chars,
                    "out_chars": s.out_chars,
                    "echoed_chars": s.echoed_chars,
                }
                for n, s in census.echo.items()
                if s.considered or s.echoed_chars
            },
        },
        "self_reads": {
            "sessions_attributed": census.sessions_with_known_band,
            "sessions_unattributable": census.sessions_without_known_band,
            "self_envelopes": census.self_read_envelopes,
            "self_chars": census.self_read_chars,
            "other_envelopes": census.other_read_envelopes,
            "other_chars": census.other_read_chars,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                    help="transcript directory (default: the korax project dir)")
    ap.add_argument("--json", action="store_true", help="emit the raw table as JSON")
    ap.add_argument("--naive-check", action="store_true", default=True,
                    help="show the naive-vs-deduped double-count control")
    args = ap.parse_args(argv)

    if not args.root.is_dir():
        print(f"census: --root is not a directory: {args.root}", file=sys.stderr)
        return 2

    census = run(args.root)
    if args.json:
        json.dump(to_json(census), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        report(census, args.root, args.naive_check)
    return 0


if __name__ == "__main__":
    sys.exit(main())
