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


# §11 — the shutdown notice a parked caller receives instead of a severed
# socket. `retry_after_s` is ADVICE, never a contract: a client backs off at
# least that long and never exactly, or a restart that runs long turns every
# parked watch into a thundering re-arm at one instant.
DEFAULT_RETRY_AFTER_S = 30
SHUTDOWN_NOTE = (
    "the board is restarting; this is a goodbye page rather than a wake. "
    "Your cursor has not moved — re-arm after retry_after_s and you will "
    "resume where you stopped"
)


class Board:
    def __init__(self, store: Store):
        self.store = store
        self._condition: asyncio.Condition | None = None
        # §11 — shutdown state lives on the BOARD, not in a module global.
        # The suite builds a board per test and a global would leak one
        # test's shutdown into the next, which is the kind of cross-test
        # bleed that makes a shutdown suite pass for the wrong reason.
        self.shutting_down = False
        self.system_notice: dict[str, Any] | None = None
        self.reload()

    async def begin_shutdown(
        self, retry_after_s: int | None = None, note: str | None = None
    ) -> None:
        """Arm the goodbye and wake every parked caller (§11, JOB #163).

        THE ORDER MATTERS AND THE NOTIFY IS NOT THE MECHANISM. `wait_for`
        below is `asyncio.Condition.wait_for`, which RE-EVALUATES its
        predicate after every notify and parks again if it is still false.
        So notifying without arming the flag first wakes every caller and
        puts them straight back to sleep — the board would sever them
        exactly as it does today, after politely waking them once.

        The flag is what the predicates consult; the notify is only what
        makes them look. Set, then notify.
        """
        self.system_notice = {
            "kind": "restart",
            "note": note or SHUTDOWN_NOTE,
            # The server ALWAYS supplies a number. A parameter that only the
            # well-behaved path passes is absent exactly when things are
            # going badly, and the ops lane exists for when things are going
            # badly (desk ruling, #854).
            "retry_after_s": (
                DEFAULT_RETRY_AFTER_S if retry_after_s is None else int(retry_after_s)
            ),
        }
        self.shutting_down = True
        await self.notify()

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
        # `registry` is REQUIRED rather than defaulted, deliberately: an
        # optional one would let a caller construct exactly the state this
        # job exists to abolish — a mention check that silently does not run
        # (#1079 part 2's lesson, applied to part 1's own wiring).
        sub = validate_post(self.log, self.timeline, raw, self.store)
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
