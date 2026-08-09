"""Lease resolution — korax-protocol.md §4.2 (with renewal/release semantics).

The one non-monotone corner of the vocabulary, resolved by the sequencer:
deterministic, computable from the log alone, identical across clients.
Renewals (same-author supersede) continue a hold; a SUPERSEDE with
`ext.released: true` truncates its lease at the release's ts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .log import Log
from .models import Act, EdgeType, Envelope


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class Hold:
    """One continuous hold on a referent: a head CLAIM plus its renewals."""

    links: list[Envelope]  # head first, renewals appended in id order
    admissible: bool = False
    released_by: Envelope | None = None  # SUPERSEDE with ext.released, if any

    @property
    def head(self) -> Envelope:
        return self.links[0]

    @property
    def current(self) -> Envelope:
        return self.links[-1]

    @property
    def author(self) -> str:
        return self.head.author

    def lease_until_raw(self) -> str:
        return str(self.current.ext["lease_until"])

    def lease_end(self) -> datetime:
        """§4.2 step 3 — earlier of the current link's lease_until and any
        release ts."""
        end = _parse_ts(self.lease_until_raw())
        if self.released_by is not None:
            end = min(end, _parse_ts(self.released_by.ts))
        return end

    def live_at(self, when: datetime) -> bool:
        return self.admissible and self.head.ts <= when < self.lease_end()


def resolve(log: Log, referent: int, offset: int) -> list[Hold]:
    """All holds on `referent` at `offset`, admissibility computed per
    §4.2. Returns holds in head-id order."""
    claims = [
        e
        for e in log.upto(offset)
        if e.type == Act.CLAIM and referent in e.refs_of(EdgeType.CLAIMS)
    ]
    by_id = {c.id: c for c in claims}

    # Renewal linking (§4.2 step 2): successor supersedes an earlier CLAIM
    # by the same author on the same referent.
    successor: dict[int, Envelope] = {}
    heads: list[Envelope] = []
    for c in claims:
        renewed = [
            t
            for t in c.refs_of(EdgeType.SUPERSEDES)
            if t in by_id and by_id[t].author == c.author
        ]
        if renewed:
            successor[renewed[0]] = c
        else:
            heads.append(c)

    holds: list[Hold] = []
    for head in sorted(heads, key=lambda e: e.id):
        links = [head]
        while links[-1].id in successor:
            links.append(successor[links[-1].id])
        hold = Hold(links=links)
        # §4.2 step 3 — early release of the current link.
        for rel in log.inbound(hold.current.id, EdgeType.SUPERSEDES, offset):
            if rel.type == Act.SUPERSEDE and rel.ext.get("released") is True:
                hold.released_by = rel
                break
        holds.append(hold)

    # §4.2 step 4 — admissibility in head-id order.
    for hold in holds:
        at = hold.head.ts
        blocked = any(
            other.admissible and other.head.ts <= at < other.lease_end()
            for other in holds
            if other.head.id < hold.head.id
        )
        hold.admissible = not blocked
    return holds


def live_holder(log: Log, referent: int, offset: int, eval_ts: datetime) -> Hold | None:
    """§4.2 step 5 — the admissible hold whose lease is running at
    `eval_ts` (the ts of the envelope at the reduction's offset)."""
    for hold in resolve(log, referent, offset):
        if hold.live_at(eval_ts):
            return hold
    return None
