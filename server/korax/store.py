"""SQLite persistence — append-only enforced at the schema (§1.1.1).

The store is deliberately dumb: it sequences, persists, and reloads.
All interpretation lives in the pure engine (log/policy/validate/
reductions); the store's one non-negotiable job is that nothing is ever
updated or deleted, at any layer, including by buggy server code —
hence the triggers.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Envelope

_SCHEMA = """
CREATE TABLE IF NOT EXISTS identities (
    id         TEXT PRIMARY KEY,
    display    TEXT NOT NULL,
    key        TEXT,
    token_hash TEXT NOT NULL UNIQUE,
    created    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS envelopes (
    id     INTEGER PRIMARY KEY,
    ts     TEXT NOT NULL,
    ns     TEXT NOT NULL,
    type   TEXT NOT NULL,
    author TEXT NOT NULL,
    grade  TEXT NOT NULL,
    record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_envelopes_ns ON envelopes(ns);
CREATE INDEX IF NOT EXISTS idx_envelopes_type ON envelopes(type);
CREATE INDEX IF NOT EXISTS idx_envelopes_author ON envelopes(author);

CREATE TRIGGER IF NOT EXISTS envelopes_append_only_update
BEFORE UPDATE ON envelopes
BEGIN SELECT RAISE(ABORT, 'append-only: no UPDATE (protocol 1.1.1)'); END;

CREATE TRIGGER IF NOT EXISTS envelopes_append_only_delete
BEFORE DELETE ON envelopes
BEGIN SELECT RAISE(ABORT, 'append-only: no DELETE (protocol 1.1.1)'); END;
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        # FastAPI sync endpoints run in a threadpool; the single connection
        # is shared across threads and serialized by the lock below.
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    def append(self, accepted: dict[str, Any]) -> Envelope:
        """Sequence and persist an accepted record. The caller passes the
        validated client subset plus server determinations (band); id and
        ts are assigned here (§1.1.2)."""
        with self._lock:  # sequencing must be atomic: one gapless total order
            cur = self.conn.execute("SELECT COALESCE(MAX(id) + 1, 0) FROM envelopes")
            next_id = int(cur.fetchone()[0])
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            record = dict(accepted, id=next_id, ts=ts)
            env = Envelope.model_validate(record)
            self.conn.execute(
                "INSERT INTO envelopes (id, ts, ns, type, author, grade, record) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    env.id,
                    ts,
                    env.ns,
                    env.type.value,
                    env.author,
                    env.grade.value,
                    env.model_dump_json(),
                ),
            )
            self.conn.commit()
            return env

    def load_all(self) -> list[Envelope]:
        rows = self.conn.execute("SELECT record FROM envelopes ORDER BY id").fetchall()
        return [Envelope.model_validate(json.loads(r[0])) for r in rows]

    # -- identities & tokens (v0 auth: bearer token per band; ed25519
    # signing is the fast-follow, see conformance README) ----------------

    def create_identity(self, display: str, identity_id: str | None = None) -> tuple[str, str]:
        """Returns (identity_id, token). The token is shown once and only
        its hash is stored."""
        import hashlib
        import secrets

        identity_id = identity_id or f"band:{secrets.token_hex(6)}"
        token = secrets.token_urlsafe(32)
        self.conn.execute(
            "INSERT INTO identities (id, display, token_hash, created) VALUES (?, ?, ?, ?)",
            (
                identity_id,
                display,
                hashlib.sha256(token.encode()).hexdigest(),
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        self.conn.commit()
        return identity_id, token

    def identity_display(self, identity_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT display FROM identities WHERE id = ?", (identity_id,)
        ).fetchone()
        return row[0] if row else None

    def identity_for_token(self, token: str) -> str | None:
        import hashlib

        row = self.conn.execute(
            "SELECT id FROM identities WHERE token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def seed(self, envelopes: list[Envelope]) -> None:
        """Load a pre-sequenced log (fixtures, imports). Refuses to seed a
        non-empty store — a board has exactly one genesis."""
        count = self.conn.execute("SELECT COUNT(*) FROM envelopes").fetchone()[0]
        if count:
            raise RuntimeError("refusing to seed a non-empty board")
        for env in envelopes:
            self.conn.execute(
                "INSERT INTO envelopes (id, ts, ns, type, author, grade, record) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    env.id,
                    env.ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    env.ns,
                    env.type.value,
                    env.author,
                    env.grade.value,
                    env.model_dump_json(),
                ),
            )
        self.conn.commit()
