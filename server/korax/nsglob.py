"""Namespace path matching — korax-protocol.md §7.

Globs use `*` (exactly one segment) and `**` (any depth, including zero).
Policies govern by prefix; grants match by glob.
"""

from __future__ import annotations


def segments(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def ns_matches(pattern: str, path: str) -> bool:
    """True if the glob pattern matches the namespace path."""
    return _match(segments(pattern), segments(path))


def _match(pat: list[str], path: list[str]) -> bool:
    if not pat:
        return not path
    head, rest = pat[0], pat[1:]
    if head == "**":
        return any(_match(rest, path[i:]) for i in range(len(path) + 1))
    if not path:
        return False
    if head == "*" or head == path[0]:
        return _match(rest, path[1:])
    return False


def governs(policy_ns: str, target_ns: str) -> bool:
    """A policy posted at `policy_ns` governs `target_ns` iff its path is a
    segment-wise prefix. The most specific match wins (§7)."""
    p, t = segments(policy_ns), segments(target_ns)
    return t[: len(p)] == p


def specificity(policy_ns: str) -> int:
    return len(segments(policy_ns))


def in_subtree(root: str, path: str) -> bool:
    """Path equals root or descends from it."""
    return governs(root, path)
