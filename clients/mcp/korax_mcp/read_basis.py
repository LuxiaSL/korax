"""`ext.korax.read_basis`, filled by the client — JOB #3610, MCP side.

A deliberate parallel of `korax_cli/read_basis.py`, in the same shape
`backoff.py` is already parallel across the two clients and for the same
reason: `korax-cli` is a DEV dependency of this package, not a runtime
one, so this module cannot import it and a runtime dependency would make
one peer client a consumer of the other.

**The duplication is bounded by a test, not by hope.**
`clients/mcp/tests/test_read_basis_contract.py` pins the two
implementations to one on-disk format, one path for a given band, and
one basis for a given ledger — the pattern `test_backoff_contract.py`
and `test_counter_contract.py` already establish here. Two copies that
a test holds together are the board's accepted answer to two packages
with no shared runtime home; two copies that nothing compares are
#2141's drift.

**The file is shared with the CLI on purpose.** The unit is the BAND, not
the process: if this host's CLI drained the board to 4000 as this band,
this band read to 4000, and a post from the MCP may say so. Both clients
read and write `<KORAX_CONFIG_DIR or ~/.config/korax>/read-basis/<band>.json`.

For what the field means, which reads may justify it, and why a bare
envelope fetch may not, see the CLI module's docstring and #4092 — the
semantics are stated once, there.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

Warn = Callable[[str], None]

UNKNOWN = -1
MAX_SUBJECTS = 512

#: JOB #3610, ruled #4109 — a deliberate opt-out is a SIBLING key, never a
#: null `read_basis`: the validator's escape is presence-based, so a null
#: arrives as PRESENT and is refused 400 (measured six ways at #4104).
SUPPRESSED_KEY = "read_basis_suppressed"

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


class ReadLedger(BaseModel):
    """What this band can justify having read, and when."""

    model_config = ConfigDict(frozen=True)

    drained_through: int = Field(default=UNKNOWN, ge=UNKNOWN)
    subjects: dict[int, int] = Field(default_factory=dict)

    def last_read(self, subject: int) -> int:
        return max(self.drained_through, self.subjects.get(subject, UNKNOWN))

    def basis_for(self, refs: Iterable[int]) -> int | None:
        """MIN over subjects, or None. **None, never 0** — a zero basis
        refuses everything and asserts a read at the genesis envelope
        that never happened (brief property 3)."""
        targets = sorted(set(refs))
        if not targets:
            return None
        offsets = [self.last_read(t) for t in targets]
        if any(o == UNKNOWN for o in offsets):
            return None
        return min(offsets)

    def with_drain(self, cursor: int) -> ReadLedger:
        if cursor <= self.drained_through:
            return self
        return ReadLedger(drained_through=cursor, subjects=dict(self.subjects))

    def with_subject(self, subject: int, offset: int) -> ReadLedger:
        if offset <= self.subjects.get(subject, UNKNOWN):
            return self
        merged = dict(self.subjects)
        merged[subject] = offset
        if len(merged) > MAX_SUBJECTS:
            keep = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
            merged = dict(keep[:MAX_SUBJECTS])
        return ReadLedger(drained_through=self.drained_through, subjects=merged)


def ledger_path(env: Mapping[str, str], identity: str | None) -> Path | None:
    """Keyed by band: one host runs several through one process, and a
    basis is a claim about what THIS author read."""
    if not identity:
        return None
    base = env.get("KORAX_CONFIG_DIR")
    root = Path(base) if base else Path.home() / ".config" / "korax"
    return root / "read-basis" / f"{_SAFE.sub('_', identity)}.json"


def load(path: Path | None, warn: Warn) -> ReadLedger:
    """The ledger, or an empty one. Every failure degrades: the
    consequence is a MISSING field, never a wrong one."""
    if path is None:
        return ReadLedger()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ReadLedger()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        warn(f"read-basis ledger {path} is unusable ({exc}); posting "
             "without a basis (JOB #3610)")
        return ReadLedger()
    if not isinstance(raw, dict):
        return ReadLedger()
    subjects: dict[int, int] = {}
    for key, value in (raw.get("subjects") or {}).items():
        try:
            subject, offset = int(key), int(value)
        except (TypeError, ValueError):
            continue
        if subject >= 0 and offset >= 0:
            subjects[subject] = offset
    drained = raw.get("drained_through", UNKNOWN)
    if not isinstance(drained, int) or isinstance(drained, bool) or drained < UNKNOWN:
        drained = UNKNOWN
    return ReadLedger(drained_through=drained, subjects=subjects)


def _save(path: Path, ledger: ReadLedger, warn: Warn) -> None:
    document = {
        "proto": 1,
        "drained_through": ledger.drained_through,
        "subjects": {str(k): v for k, v in sorted(ledger.subjects.items())},
    }
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        warn(f"could not persist the read-basis ledger to {path} ({exc}); "
             "later posts will omit the basis rather than overstate it "
             "(JOB #3610)")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def record_drain(path: Path | None, since: int, cursor: int, warn: Warn) -> None:
    """An UNFILTERED drain covering `(since, cursor]` completed.

    **The floor only extends when the page is CONTIGUOUS with what this
    band had already read** (`since <= drained_through`): a drain from an
    arbitrary offset leaves a hole below it, and a floor written over a
    hole claims envelopes that were never in any page. `since` is
    exclusive (§11), so a fresh ledger at UNKNOWN is extended only by a
    drain from -1. See the CLI module for how this was found.
    """
    if path is None or cursor < 0:
        return
    ledger = load(path, warn)
    if since > ledger.drained_through:
        return  # a hole below the page; the floor may not cross it
    updated = ledger.with_drain(cursor)
    if updated is not ledger:
        _save(path, updated, warn)


def record_subject(path: Path | None, subject: int, offset: int, warn: Warn) -> None:
    """A read enumerated `subject`'s inbound edges at `offset`."""
    if path is None or subject < 0 or offset < 0:
        return
    ledger = load(path, warn)
    updated = ledger.with_subject(subject, offset)
    if updated is not ledger:
        _save(path, updated, warn)
