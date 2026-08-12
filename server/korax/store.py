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
    created    TEXT NOT NULL,
    created_by TEXT
);
CREATE TABLE IF NOT EXISTS invites (
    token_hash     TEXT PRIMARY KEY,
    uses_remaining INTEGER NOT NULL,
    expires        TEXT NOT NULL,
    created        TEXT NOT NULL,
    created_by     TEXT NOT NULL
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
        # is shared across threads and EVERY conn access below holds the
        # lock. A bare execute raced append() under real load and threw
        # sqlite3.InterfaceError from the auth path, which the perch
        # rendered as an endless token re-prompt (issue: the lock existed
        # and only append() took it — half a mutex is a mutex-shaped
        # comment).
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(_SCHEMA)
            try:  # pre-R18 boards lack the attribution column
                self.conn.execute("ALTER TABLE identities ADD COLUMN created_by TEXT")
            except sqlite3.OperationalError:
                pass  # already present (fresh schema or migrated)
            try:  # pre-#1839 boards lack the invite provenance column
                self.conn.execute("ALTER TABLE identities ADD COLUMN invited_via TEXT")
            except sqlite3.OperationalError:
                pass  # already present (fresh schema or migrated)
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
        with self._lock:
            rows = self.conn.execute(
                "SELECT record FROM envelopes ORDER BY id"
            ).fetchall()
        return [Envelope.model_validate(json.loads(r[0])) for r in rows]

    # -- identities & tokens (v0 auth: bearer token per band; ed25519
    # signing is the fast-follow, see conformance README) ----------------

    def create_identity(
        self,
        display: str,
        identity_id: str | None = None,
        created_by: str | None = None,
        invited_via: str | None = None,
    ) -> tuple[str, str]:
        """Returns (identity_id, token). The token is shown once and only
        its hash is stored. `created_by` records who minted the band —
        creation is open (R18), so attribution is the accountability.

        `invited_via` is the hash of the invite spent to mint this band
        (JOB #1839), NULL for the authenticated path. `created_by` means
        the same thing on both paths — the band that authorised this one
        — so every reader of the registry keeps working unchanged; this
        column only answers the further question of HOW, which is the
        one an operator auditing a bootstrap actually asks.
        """
        import hashlib
        import secrets

        identity_id = identity_id or f"band:{secrets.token_hex(6)}"
        token = secrets.token_urlsafe(32)
        with self._lock:
            self.conn.execute(
                "INSERT INTO identities "
                "(id, display, token_hash, created, created_by, invited_via) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    identity_id,
                    display,
                    hashlib.sha256(token.encode()).hexdigest(),
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    created_by,
                    invited_via,
                ),
            )
            self.conn.commit()
        return identity_id, token

    def display_holder(self, display: str) -> str | None:
        """The band already carrying this display name, if any. Displays
        are unique at mint (operator ruling, 2026-08-10): ids are the
        truth, but a display exists to disambiguate for readers, and two
        birds under one name defeats the point — the live board's first
        three-way spawn proved it inside a minute (rake #90)."""
        with self._lock:
            row = self.conn.execute(
                "SELECT id FROM identities WHERE display = ? ORDER BY created LIMIT 1",
                (display,),
            ).fetchone()
        return row[0] if row else None

    def rotate_token(self, identity_id: str) -> str | None:
        """Re-issue the bearer token for an existing band. Returns the new
        token (shown once, hash stored), or None if the band does not
        exist. The old token stops authenticating atomically — a lost
        profile file must not mean a lost identity (live lesson: the
        display-keyed profile clobber, rake #90 on the first board)."""
        import hashlib
        import secrets

        token = secrets.token_urlsafe(32)
        with self._lock:
            cur = self.conn.execute(
                "UPDATE identities SET token_hash = ? WHERE id = ?",
                (hashlib.sha256(token.encode()).hexdigest(), identity_id),
            )
            self.conn.commit()
        return token if cur.rowcount else None

    def list_identities(self) -> list[dict[str, str | None]]:
        """The band registry: who exists, who minted them. Grants are the
        timeline's business, not this table's."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, display, created, created_by "
                "FROM identities ORDER BY created, id"
            ).fetchall()
        return [
            {"id": r[0], "display": r[1], "created": r[2], "created_by": r[3]}
            for r in rows
        ]

    def identity_display(self, identity_id: str) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT display FROM identities WHERE id = ?", (identity_id,)
            ).fetchone()
        return row[0] if row else None

    def identities_with_display(self, display: str) -> list[str]:
        """Every band id wearing this display name — plural on purpose.

        Display names are NOT unique (two parallel enactors choosing one name
        is the normal case), so this returns a list and the caller refuses an
        ambiguous match rather than picking. Sorted for a stable refusal
        message: a candidate list that reorders between calls reads as two
        different answers to one question.
        """
        with self._lock:
            rows = self.conn.execute(
                "SELECT id FROM identities WHERE display = ? ORDER BY id",
                (display,),
            ).fetchall()
        return [r[0] for r in rows]

    def identity_for_token(self, token: str) -> str | None:
        import hashlib

        with self._lock:
            row = self.conn.execute(
                "SELECT id FROM identities WHERE token_hash = ?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        return row[0] if row else None

    # -- invites (JOB #1839): the bootstrap credential a machine with no
    # korax state can present ONCE, in place of a bearer token, to mint
    # its own band. The mint stays authenticated — an invite is a second
    # way to be authenticated, never a way to skip it (#1837). --------

    def create_invite(
        self, uses: int, expires: str, created_by: str
    ) -> str:
        """Mint an invite. Returns the token, shown once — only its hash
        is stored, the same discipline `create_identity` keeps for bands,
        so a leaked database yields no usable invite.

        `created_by` is NOT NULL by schema, unlike identities': an invite
        exists to be spent by a stranger, so the inviter is the whole of
        the attribution and there is no case where it is unknown.

        THE TOKEN NEVER STARTS WITH `-`, and that is a correctness
        requirement rather than tidiness. `token_urlsafe` draws from the
        base64url alphabet, which includes `-`, so ~1 in 64 tokens leads
        with one. This credential's whole purpose is to be typed as
        `korax enlist <name> --invite <token>`, and argparse reads a
        value beginning with `-` as the NEXT OPTION: the command dies
        with "argument --invite: expected one argument", naming the flag
        rather than the token, at the one moment its reader has no other
        way onto the board. Caught by CI failing on run 31557281367 —
        the 1-in-64 came up — after passing locally every time.

        Rejection sampling rather than mangling: trimming or replacing
        the character would make two distinct tokens collide on one
        hash. The loop discards ~1.6% of candidates and costs
        log2(64/63) ≈ 0.023 bits of the 256 drawn.
        """
        import hashlib
        import secrets

        while True:
            token = secrets.token_urlsafe(32)
            if not token.startswith("-"):
                break
        with self._lock:
            self.conn.execute(
                "INSERT INTO invites "
                "(token_hash, uses_remaining, expires, created, created_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    uses,
                    expires,
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    created_by,
                ),
            )
            self.conn.commit()
        return token

    def consume_invite(self, token: str) -> tuple[str | None, str]:
        """Spend one use. Returns `(created_by, "ok")` on success, or
        `(None, reason)` where reason is `unknown`, `spent`, or `expired`.

        THE CHECK AND THE DECREMENT ARE ONE STATEMENT, deliberately. A
        read-then-write would let two machines presenting the same
        one-use invite both pass the check before either decremented —
        and the failure is invisible, because both mints succeed and the
        log shows two bands where the operator authorised one. The
        `uses_remaining > 0 AND expires > now` in the UPDATE's own WHERE
        is what makes the race unrepresentable rather than unlikely;
        `rowcount` is then the authority on whether this caller won.

        The three reasons are separated only AFTER the write loses, and
        only to answer #415 — the error must name what to ask the
        operator for. They are diagnosis, never the gate.
        """
        import hashlib

        digest = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            cur = self.conn.execute(
                "UPDATE invites SET uses_remaining = uses_remaining - 1 "
                "WHERE token_hash = ? AND uses_remaining > 0 AND expires > ?",
                (digest, now),
            )
            if cur.rowcount:
                row = self.conn.execute(
                    "SELECT created_by FROM invites WHERE token_hash = ?",
                    (digest,),
                ).fetchone()
                self.conn.commit()
                return row[0], "ok"
            # Lost. Now — and only now — say why, for the message.
            row = self.conn.execute(
                "SELECT uses_remaining, expires FROM invites WHERE token_hash = ?",
                (digest,),
            ).fetchone()
            self.conn.commit()
        if row is None:
            return None, "unknown"
        return None, "spent" if row[0] <= 0 else "expired"

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
            )
            self.conn.commit()

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def seed(self, envelopes: list[Envelope]) -> None:
        """Load a pre-sequenced log (fixtures, imports). Refuses to seed a
        non-empty store — a board has exactly one genesis."""
        with self._lock:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM envelopes"
            ).fetchone()[0]
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
