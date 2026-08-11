"""The append-only log as a pure, queryable value.

Reductions and validation operate on `Log` — a fully-materialized,
immutable view of accepted envelopes — so the whole engine is
deterministic and storage-agnostic (§10: same log, same offset, same
output). The SQLite layer feeds this; tests feed it fixtures directly.
"""

from __future__ import annotations

from collections import defaultdict

from .models import Act, EdgeType, Envelope


class Log:
    def __init__(self, envelopes: list[Envelope]):
        self.envelopes = list(envelopes)
        self._by_id: dict[int, Envelope] = {e.id: e for e in self.envelopes}
        # inbound[target_id] -> [(edge, source_envelope)]
        self._inbound: dict[int, list[tuple[EdgeType, Envelope]]] = defaultdict(list)
        for env in self.envelopes:
            for ref in env.refs:
                self._inbound[ref.id].append((ref.edge, env))

    def append(self, env: Envelope) -> None:
        """Join one accepted envelope to the indexes — JOB #1446.

        The exact per-envelope body of `__init__`'s loops, so an appended
        log and a rebuilt log are the same object by construction; the
        equivalence suite (`test_append_not_reload.py`) asserts it after
        every append of a mixed-act workload rather than trusting this
        sentence. Appends must arrive in id order — the log is a total
        order (§1) and the indexes assume it the same way `__init__` does.
        """
        assert not self.envelopes or env.id > self.envelopes[-1].id, (
            f"append out of order: {env.id} after {self.envelopes[-1].id}"
        )
        self.envelopes.append(env)
        self._by_id[env.id] = env
        for ref in env.refs:
            self._inbound[ref.id].append((ref.edge, env))

    def __len__(self) -> int:
        return len(self.envelopes)

    def get(self, env_id: int) -> Envelope | None:
        return self._by_id.get(env_id)

    def upto(self, offset: int) -> list[Envelope]:
        """Envelopes with id <= offset (offsets are inclusive throughout)."""
        return [e for e in self.envelopes if e.id <= offset]

    def inbound(
        self, target: int, edge: EdgeType | None = None, offset: int | None = None
    ) -> list[Envelope]:
        """Sources of inbound edges to `target`, optionally filtered by edge
        type and capped at an offset."""
        out = []
        for e, src in self._inbound.get(target, []):
            if edge is not None and e != edge:
                continue
            if offset is not None and src.id > offset:
                continue
            out.append(src)
        return out

    def acts_in(self, act: Act, offset: int) -> list[Envelope]:
        return [e for e in self.envelopes if e.type == act and e.id <= offset]

    def next_id(self) -> int:
        return self.envelopes[-1].id + 1 if self.envelopes else 0

    def ts_at(self, offset: int) -> str:
        """Evaluation time for a reduction at `offset` — the ts of that
        envelope, never wall clock (§4.2 step 5)."""
        env = self._by_id.get(offset)
        if env is None:
            raise KeyError(f"no envelope at offset {offset}")
        return env.ts.strftime("%Y-%m-%dT%H:%M:%SZ")
