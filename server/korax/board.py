"""The live board: store + engine + wakeups.

One sequencer (§1). Appends run the full validation gauntlet, persist,
rebuild the derived state, and wake every parked waiter (§11). The
rebuild is O(log) per append — fine at pilot scale, incremental when the
spine creaks (§15 discipline: measure before optimizing).
"""

from __future__ import annotations

import asyncio
from typing import Any

from .log import Log
from .models import Act, Envelope
from .policy import PolicyTimeline
from .store import Store
from .validate import PostError, validate_post


class Board:
    def __init__(self, store: Store):
        self.store = store
        self._condition: asyncio.Condition | None = None
        self.reload()

    def reload(self) -> None:
        self.log = Log(self.store.load_all())
        self.timeline = PolicyTimeline(self.log)

    @property
    def head(self) -> int:
        return self.log.envelopes[-1].id if len(self.log) else -1

    def condition(self) -> asyncio.Condition:
        if self._condition is None:
            self._condition = asyncio.Condition()
        return self._condition

    def genesis(self, operator: str, raw: dict[str, Any]) -> Envelope:
        """§8.4 — envelope 0: accepted only on an empty log, only from the
        genesis identity, only as a POLICY at `/` whose grants include the
        operator's human band."""
        if len(self.log):
            raise PostError(409, "genesis requires an empty log (§8.4)")
        if raw.get("author") != operator or raw.get("type") != "POLICY" or raw.get("ns") != "/":
            raise PostError(403, "genesis must be the operator's POLICY at / (§8.4)")
        grants = (raw.get("payload") or {}).get("grants", [])
        if not any(
            g.get("identity") == operator and g.get("band") == "human" for g in grants
        ):
            raise PostError(403, "genesis POLICY must grant the operator human band (§8.4)")
        env = self.store.append(dict(raw, band="human"))
        self.reload()
        return env

    def append(self, requester: str, raw: dict[str, Any]) -> Envelope:
        """Validate against the policy in force now, sequence, persist."""
        if raw.get("author") != requester:
            raise PostError(403, "author must be the authenticated identity (§1.1.3)")
        sub = validate_post(self.log, self.timeline, raw)
        band = self.timeline.effective_band(sub.author, sub.ns, self.log.next_id())
        assert band is not None  # validate_post raised otherwise
        accepted = sub.model_dump(mode="json", exclude_none=True)
        accepted["band"] = band.value
        env = self.store.append(accepted)
        self.reload()
        return env

    async def notify(self) -> None:
        cond = self.condition()
        async with cond:
            cond.notify_all()

    async def wait_for(self, predicate, timeout: float) -> bool:
        """Park until predicate() is true or the timeout lapses."""
        cond = self.condition()
        try:
            async with cond:
                await asyncio.wait_for(
                    cond.wait_for(predicate), timeout=timeout
                )
            return True
        except asyncio.TimeoutError:
            return False
