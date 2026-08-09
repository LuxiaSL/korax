"""Fixture-01 must parse cleanly into the envelope model.

This is the first rung of the conformance ladder: before any server
behavior exists, the wire types themselves are held to the fixture. The
reduction/reject suites build on top of this loader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from korax import PROTO
from korax.models import Act, EdgeType, Envelope

CONFORMANCE = Path(__file__).resolve().parents[2] / "conformance"


def load_fixture() -> list[Envelope]:
    envelopes: list[Envelope] = []
    with open(CONFORMANCE / "fixture-01.jsonl", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if "_comment" in record:
                continue
            envelopes.append(Envelope.model_validate(record))
    return envelopes


@pytest.fixture(scope="module")
def fixture() -> list[Envelope]:
    return load_fixture()


def test_fixture_loads_all_envelopes(fixture: list[Envelope]) -> None:
    assert len(fixture) == 34


def test_ids_are_gapless_and_ordered(fixture: list[Envelope]) -> None:
    assert [e.id for e in fixture] == list(range(34))


def test_ts_is_monotone_nondecreasing(fixture: list[Envelope]) -> None:
    stamps = [e.ts for e in fixture]
    assert stamps == sorted(stamps)


def test_proto_is_korax(fixture: list[Envelope]) -> None:
    assert {e.proto for e in fixture} == {PROTO}


def test_every_ref_targets_an_earlier_envelope(fixture: list[Envelope]) -> None:
    for env in fixture:
        for ref in env.refs:
            assert ref.id < env.id, f"envelope {env.id} refs forward to {ref.id}"


def test_genesis_is_a_human_policy_at_zero(fixture: list[Envelope]) -> None:
    genesis = fixture[0]
    assert genesis.id == 0
    assert genesis.type == Act.POLICY
    assert genesis.band.value == "human"
    assert genesis.ns == "/"


def test_fixture_exercises_every_v1_act_it_claims(fixture: list[Envelope]) -> None:
    used = {e.type for e in fixture}
    # PIN/ACK/UNSEAL are fixture-04/05 scope (conformance README); the rest
    # of the vocabulary must appear in fixture-01.
    expected = set(Act) - {Act.PIN, Act.ACK, Act.UNSEAL}
    assert expected <= used


def test_claims_edges_only_on_claim_acts(fixture: list[Envelope]) -> None:
    for env in fixture:
        if env.refs_of(EdgeType.CLAIMS):
            assert env.type == Act.CLAIM
