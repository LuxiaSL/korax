"""The live board: store + engine + wakeups.

One sequencer (§1). Appends run the full validation gauntlet, persist,
join the derived state incrementally, and wake every parked waiter
(§11). The join replaced a full O(log) rebuild when the spine creaked —
measured at #1431 §3, remedied by JOB #1446 — exactly the §15
discipline running its course: measure before optimizing, then
optimize what was measured. `reload()` remains the from-scratch path
(startup, genesis) and the equivalence suite pins the two equal.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from .access import VisibleSlice, filter_log
from .log import Log
from .models import Envelope
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
        # JOB #1522 — the waiter cache. Keyed on the FULL (identity, head)
        # tuple, which is #1517 §2/§5's own primary design and NOT the
        # "clear the dict when head moves" simplification §5 offers beside
        # it. With the head in the key, a lookup at a new head cannot reach
        # an old head's entry under any interleaving; with the head in a
        # label beside the dict, a slow `filter_log` on a threadpool worker
        # can publish an old-head triple after a newer reader has relabelled
        # the dict, which is exactly the stale-head service #1519 promoted
        # to normative. Reasoned in WARN #1539.
        self._visible: dict[tuple[str, int], VisibleSlice] = {}
        # `/read` and `/view` are SYNC path operations (api.py:638, :1040),
        # so FastAPI runs them in a threadpool: this dict is reached from
        # worker threads AND from the event loop. The critical section is
        # two dict operations against a ~16ms pure pass, so the lock costs
        # nothing measurable — and `store.py:59-65` is this codebase's own
        # scar from assuming otherwise on the same surface ("half a mutex
        # is a mutex-shaped comment").
        self._visible_lock = threading.Lock()
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
        # A rebuild can land the SAME head with different objects (startup,
        # genesis, a test rebuilding a board), so the head in the key is not
        # enough to invalidate here — drop everything. Cheap and rare.
        self._drop_visible()

    @property
    def head(self) -> int:
        return self.log.envelopes[-1].id if len(self.log) else -1

    def visible_for(self, requester: str) -> VisibleSlice:
        """`filter_log` for one requester at the current head, memoized.

        JOB #1522, PROPOSAL #1517 shape (b) as endorsed at #1519. Every
        write wakes every parked call (`notify_all`), and each one used to
        recompute an IDENTICAL full pass over the log — same `requester`,
        same `head`, same answer. One pass per (identity, head) instead of
        one per parked call: N tabs of one operator cost one pass, which is
        the live-perch precondition #1453 registered.

        **Entries for non-current heads are unreachable, structurally.**
        The head is IN THE KEY, so a lookup at a new head cannot return an
        old head's slice no matter how the threads interleave — see the
        constructor and WARN #1539 for why the cheaper "relabel the dict"
        variant is not safe here. Old entries are then only a memory
        question, and getting a memory question wrong costs bytes rather
        than a wrong answer.

        **The value is treated as immutable.** Callers receive the same
        objects on a hit, so a caller that mutated the returned Log or
        either exclusion list would poison every later reader at this head.
        No current caller does (they pass the Log to `rotate_project` /
        `rotate_split`, which build new ones), and
        `test_waiter_cache.py::test_the_cached_slice_is_not_mutated_by_its_callers`
        holds that.
        """
        head = self.head
        key = (requester, head)
        with self._visible_lock:
            hit = self._visible.get(key)
        if hit is not None:
            return hit
        # Computed OUTSIDE the lock: `filter_log` is pure and ~16ms, and
        # holding a lock across it would serialize every reader on the
        # board — turning a latency fix into a latency bug. Two threads
        # racing the same cold key both compute and one wins the store;
        # duplicated work once, never a wrong answer.
        value = filter_log(self.log, self.timeline, requester, head)
        with self._visible_lock:
            self._visible.setdefault(key, value)
            return self._visible[key]

    def _drop_visible(self, keep_head: int | None = None) -> None:
        """Forget cached slices. Memory hygiene only — correctness is the
        key's job, not this method's."""
        with self._visible_lock:
            if keep_head is None:
                self._visible.clear()
            else:
                stale = [k for k in self._visible if k[1] != keep_head]
                for k in stale:
                    del self._visible[k]

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
        # JOB #1446 — append, don't reload. The old tail here was
        # `self.reload()`: the ENTIRE log rebuilt from sqlite per write,
        # measured linear at 9.5→37.5 ms/post over one evening's growth
        # (#1431 §3) and multiplied by every parked waiter's re-evaluated
        # predicate. The envelope joins the in-memory state incrementally;
        # `reload()` survives below as the correctness fallback (startup,
        # genesis) and the equivalence suite holds the two paths equal
        # after every append, not by this comment but by structural
        # comparison (test_append_not_reload.py).
        self.log.append(env)
        self.timeline.apply(self.log, env)
        # Head advanced: every cached slice is now for a previous head and
        # can never be looked up again (the head is in the key). Dropping
        # them is memory hygiene, and doing it here keeps the dict at one
        # head's worth rather than one per write for the process's life.
        self._drop_visible(keep_head=self.head)
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
