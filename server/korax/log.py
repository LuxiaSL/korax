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
