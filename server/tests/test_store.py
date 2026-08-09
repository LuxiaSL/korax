"""Append-only must hold at the storage layer itself (§1.1.1)."""

from __future__ import annotations

import sqlite3

import pytest

from conftest import load_envelopes
from korax.store import Store


@pytest.fixture()
def seeded() -> Store:
    store = Store(":memory:")
    store.seed(load_envelopes())
    return store


def test_roundtrip(seeded: Store) -> None:
    envelopes = seeded.load_all()
    assert [e.id for e in envelopes] == list(range(34))


def test_update_is_refused_at_schema(seeded: Store) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded.conn.execute("UPDATE envelopes SET grade = 'verified' WHERE id = 13")


def test_delete_is_refused_at_schema(seeded: Store) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded.conn.execute("DELETE FROM envelopes WHERE id = 27")


def test_seed_refuses_nonempty(seeded: Store) -> None:
    with pytest.raises(RuntimeError, match="non-empty"):
        seeded.seed(load_envelopes())


def test_append_sequences_gaplessly() -> None:
    store = Store(":memory:")
    first = store.append(
        {
            "proto": "korax/0.1",
            "author": "band:human",
            "band": "human",
            "ns": "/",
            "type": "POLICY",
            "grade": "n/a",
            "refs": [],
            "payload": {"grants": []},
            "ext": {},
        }
    )
    second = store.append(
        {
            "proto": "korax/0.1",
            "author": "band:human",
            "band": "human",
            "ns": "/commons/rakes",
            "type": "WARN",
            "grade": "unverified",
            "refs": [],
            "payload": "tee, don't tail",
            "ext": {},
        }
    )
    assert (first.id, second.id) == (0, 1)
