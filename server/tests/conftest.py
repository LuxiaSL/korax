from __future__ import annotations

import json
from pathlib import Path

import pytest

from korax.log import Log
from korax.models import Envelope
from korax.policy import PolicyTimeline

CONFORMANCE = Path(__file__).resolve().parents[2] / "conformance"


def load_envelopes() -> list[Envelope]:
    envelopes = []
    with open(CONFORMANCE / "fixture-01.jsonl", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if "_comment" in record:
                continue
            envelopes.append(Envelope.model_validate(record))
    return envelopes


def load_jsonl(name: str) -> list[dict]:
    out = []
    with open(CONFORMANCE / name, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if "_comment" in record:
                continue
            out.append(record)
    return out


@pytest.fixture(scope="session")
def full_log() -> Log:
    return Log(load_envelopes())


@pytest.fixture(scope="session")
def timeline(full_log: Log) -> PolicyTimeline:
    return PolicyTimeline(full_log)


def truncated(log: Log, offset: int) -> tuple[Log, PolicyTimeline]:
    sub = Log(log.upto(offset))
    return sub, PolicyTimeline(sub)


class FakeRegistry:
    """The band registry as `mention_refusal` sees it (JOB #1079).

    **Deliberately NOT permissive.** The obvious test double answers "yes,
    that band exists" to everything, which would restore precisely the state
    this job abolished — a mention check that runs and cannot refuse. It
    knows the bands it was told about and nothing else, so a test that wants
    a mention to pass has to say who exists, and a test that forgets gets the
    refusal rather than a silent pass.
    """

    def __init__(self, bands: dict[str, str] | None = None) -> None:
        #: band id -> display name
        self.bands = dict(bands or {})

    def identity_display(self, identity_id: str) -> str | None:
        return self.bands.get(identity_id)

    def identities_with_display(self, display: str) -> list[str]:
        return sorted(i for i, d in self.bands.items() if d == display)
