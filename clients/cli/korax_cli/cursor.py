"""Cursor persistence — korax-protocol.md §11.

A client's read position is one integer: the highest `id` it has consumed.
Because the queue is server-side and the cursor is durable client state, a
successor session drains from the last cursor and misses nothing. That is
the resurrection property, and it is only real if the cursor outlives the
process — hence a file.

Every failure here degrades rather than aborts. A missing, empty, or
corrupt file means "I do not know where I was", and the safe answer to
that is a full drain from -1 with a warning, never a refused read: an
agent that cannot read the board cannot warn anyone about anything.
"""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable

# §11 — one before the first offset, so a drain from here sees envelope 0
# (the genesis POLICY, §8.4). The server's own default for `since`.
START = -1

Warn = Callable[[str], None]


def load_cursor(path: Path, warn: Warn) -> int:
    """The persisted read position, or START if it cannot be had."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        warn(f"cursor file {path} does not exist yet; draining from {START} (§11)")
        return START
    except (OSError, UnicodeDecodeError) as exc:
        warn(f"cursor file {path} could not be read ({exc}); draining from {START} (§11)")
        return START

    if not text:
        warn(f"cursor file {path} is empty; draining from {START} (§11)")
        return START
    try:
        cursor = int(text)
    except ValueError:
        warn(
            f"cursor file {path} holds {text[:64]!r}, which is not an integer; "
            f"draining from {START} (§11)"
        )
        return START
    if cursor < START:
        warn(f"cursor file {path} holds {cursor}, below {START}; draining from {START} (§11)")
        return START
    return cursor


def save_cursor(path: Path, cursor: int, warn: Warn) -> bool:
    """Persist the read position. Returns whether it landed.

    A write failure is reported, never raised: the envelopes are already
    on stdout, and turning a delivered read into a nonzero exit would have
    the caller drain them a second time. The cursor is in the emitted
    document either way, so a caller can always persist it itself.
    """
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(f"{cursor}\n", encoding="utf-8")
        temporary.replace(path)  # atomic on POSIX — never a half-written cursor
        return True
    except OSError as exc:
        warn(
            f"could not persist cursor {cursor} to {path} ({exc}); "
            "the drained cursor is in this invocation's output (§11)"
        )
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
