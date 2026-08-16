"""§2.2 blob store — JOB #2201, `artifact-store.md @ b158ef6`'s B1 section,
ruled at PROPOSAL #1934 (endorsed #1937, dedup x anchors seam #1948,
sealed under the operator's STAMP #2171/#2172).

Content-addressed bytes served by the board, so a §2.2 pointer becomes
checkable in one fetch without changing what a pointer means. Every
upload posts its own ANCHOR — a NOTE in ARTIFACTS_NS carrying
`korax:blob/<sha256>` as its pointer uri — always, even for bytes the
store already holds: attribution wins over dedup-by-silence (#1948
clause 1, refusing the cheaper "point at the existing anchor" alternative
because it breaks attribution and hands every band an existence oracle
for uploaded bytes, which is the exact leak class the seal exists to
refuse).

Visibility and retention key off the anchor(s), never off the blob row
itself — the row is dumb storage; every question with an answer lives
here, against the log, not in `store.py`:

    visibility  GET serves the blob if ANY (unrotated) anchor is
                readable by the requester (`access.verdict`) — independent
                possession is not disclosure (#1948 clause 2): if band B
                lawfully posted the same bytes publicly, band A's seal on
                identical bytes protects nothing still secret, and the
                mirror concern (B's public anchor "unsealing" A's) fails
                the same test — the bytes were independently B's to post.
    retention   the blob is servable while ANY anchor is unrotated
                (`retention.is_rotated`) — same sha->anchors scan the
                flood ledger already needs, no refcounting (#1948 clause
                3). All-rotated (or zero-anchor) reads as gone, not merely
                unreadable: retention's promise is that a rotated-away
                anchor reverts every pointer at it to what §2.2 always
                was, a claim nothing here can check any more.
    flood       per-blob cap MAX_BLOB_BYTES; per-band trailing-24h budget
                MAX_DAILY_BYTES, summed over the band's own anchors in
                ARTIFACTS_NS — an envelope scan, no new bookkeeping
                (slate's #1937: "an anchor carries author, ts and
                pointer.bytes, so the budget is a scan over the nest").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .access import verdict
from .log import Log
from .models import Act, Envelope
from .policy import PolicyTimeline
from .retention import eval_ts_at, is_rotated

#: B1 is scoped to this one nest — "the commons question waits" (the
#: brief's own words). A second program getting its own artifacts nest is
#: a future generalisation, not a B1 decision.
ARTIFACTS_NS = "/korax-dev/artifacts"

#: 8 MiB — the ruled per-blob cap (artifact-store.md, "Flood").
MAX_BLOB_BYTES = 8 * 1024 * 1024

#: 64 MiB — the ruled per-band trailing-24h budget.
MAX_DAILY_BYTES = 64 * 1024 * 1024


def blob_uri(sha256: str) -> str:
    return f"korax:blob/{sha256}"


def anchors_for(log: Log, offset: int, sha256: str) -> list[Envelope]:
    """Every ANCHOR for `sha256` in ARTIFACTS_NS, oldest first. One blob,
    N anchors (#1948) — a second upload of known bytes still gets its own
    entry here, because it is its own act."""
    uri = blob_uri(sha256)
    return sorted(
        (
            e for e in log.upto(offset)
            if e.ns == ARTIFACTS_NS and e.type == Act.NOTE
            and e.pointer is not None and e.pointer.uri == uri
        ),
        key=lambda e: e.id,
    )


def daily_usage(log: Log, offset: int, band: str) -> int:
    """Bytes `band` has anchored in ARTIFACTS_NS over the trailing 24h,
    by WALL CLOCK — the §4.2 lease-admission family, not a reproducible
    reduction. A live quota gates a live write against the clock the
    write is happening on, not the log's own time (§10's rule is for
    reductions; this is an admission check, same shape as lease liveness)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    return sum(
        (e.pointer.bytes or 0)
        for e in log.upto(offset)
        if e.ns == ARTIFACTS_NS and e.type == Act.NOTE and e.author == band
        and e.pointer is not None and e.ts >= cutoff
    )


def readable_anchor(
    log: Log, timeline: PolicyTimeline, offset: int, requester: str, sha256: str
) -> tuple[Envelope | None, bool]:
    """The first unrotated anchor (by id) that `requester` may read, or
    None. Second element is True iff at least one unrotated anchor exists
    but none is readable by this requester — the seal applies (403), not
    absence (404). A sha with zero anchors, or with every anchor rotated
    away, returns `(None, False)`: gone, not merely unreadable (#1948
    clause 3 — retention is not a visibility question)."""
    eval_ts = eval_ts_at(log, offset)
    live = [
        a for a in anchors_for(log, offset, sha256)
        if not is_rotated(timeline, a, offset, eval_ts)
    ]
    for a in live:
        if verdict(log, timeline, a, requester, offset) == "ok":
            return a, False
    return None, bool(live)
