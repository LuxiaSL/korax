"""fixture-07 — lineages and work status (§5.1/§10.1/§10.6/§10.8, R29).

Two guarantees:
  1. every check in expected-07 matches this engine, including the
     ORDER of `fresh`, because the ranking inversion is the bug and a
     membership-only assertion passes while it is still wrong;
  2. the `must_not` list holds — one entry per lineage, distinct
     authors across a chain, no grade laundered from its own author,
     and `state` agreeing with `jobs` about who holds what at EVERY
     offset rather than at the one this file happens to check.
"""

from __future__ import annotations

import json

import pytest

from conftest import CONFORMANCE, load_jsonl
from test_expected import assert_subset
from korax.log import Log
from korax.models import Envelope
from korax.policy import PolicyTimeline
from korax.reductions import fresh, jobs, state

with open(CONFORMANCE / "expected-07.json", encoding="utf-8") as f:
    EXPECTED = json.load(f)


@pytest.fixture(scope="module")
def world() -> tuple[Log, PolicyTimeline]:
    log = Log([Envelope.model_validate(r) for r in load_jsonl("fixture-07.jsonl")])
    return log, PolicyTimeline(log)


def run(world, check: dict):
    log, tl = world
    args, offset = check["args"], check["offset"]
    if check["view"] == "fresh":
        return fresh(log, tl, offset, args["ns_set"].split(","), args["horizon"])
    if check["view"] == "state":
        return state(log, tl, offset, args["ns"])
    return jobs(log, tl, offset, args["ns"])


@pytest.mark.parametrize("check", EXPECTED["checks"],
                         ids=lambda c: f"{c['view']}@{c['offset']}-{c['cite']}")
def test_expected(world, check: dict) -> None:
    actual = run(world, check)
    expect = check["expect"]
    why = check["why"]

    if "order" in expect:
        assert [e["id"] for e in actual] == expect["order"], why
    for env_id, fields in expect.get("entries", {}).items():
        entry = next(e for e in actual if e["id"] == int(env_id))
        for key, value in fields.items():
            assert entry[key] == value, f"{why}\n  fresh[{env_id}].{key}"
    for env_id in expect.get("absent", []):
        assert env_id not in [e["id"] for e in actual], why
    for key in ("warns", "open", "superseded", "delivered", "taken", "claims"):
        if key in expect:
            # Subset semantics, as everywhere else in conformance: given
            # keys must match, extra keys the reduction carries (a hold's
            # `lease_until`) are not the fixture's business.
            assert_subset(expect[key], actual[key], f"{check['view']}.{key}")


# ── must_not: invariants no single row can express ────────────────────


def test_one_entry_per_lineage(world) -> None:
    log, tl = world
    digest = fresh(log, tl, 21, ["/rakes"], "P365D")
    ids = {e["id"] for e in digest}
    ancestors = {a for e in digest for a in e["supersedes"]}
    assert ancestors, "no chain in the fixture; the invariant proved nothing"
    assert not (ids & ancestors), (
        "a superseded envelope was emitted as its own entry as well as "
        "being listed under its head"
    )


def test_lineage_weight_counts_distinct_non_member_authors(world) -> None:
    """§5.3.3 across the chain. Rake A's corroboration sits on the dead
    ancestor and its author is not a member of the chain, so it counts
    once at the head — and the head's own weight stays 0, which is the
    pair of numbers that tells a reader the support attaches to older
    text."""
    log, tl = world
    head = next(e for e in fresh(log, tl, 21, ["/rakes"], "P365D") if e["id"] == 5)
    assert head["replication_weight"] == 0
    assert head["lineage_weight"] == 1
    assert head["lineage_corroborators"] == ["band:e2"]
    assert "band:e1" not in head["lineage_corroborators"], (
        "an author of the chain counted toward its own lineage weight"
    )


def test_no_grade_is_laundered_from_its_own_author(world) -> None:
    log, tl = world
    for entry in jobs(log, tl, 21, "/work/jobs")["delivered"]:
        source_author = log.get(entry["grade_by"]).author
        by_author = log.get(entry["by"]).author
        if source_author == by_author:
            assert entry.get("grade_source") in ("self", "unattested"), (
                f"job {entry['job']} reports a grade from its own deliverer "
                "without saying so"
            )
        else:
            assert "grade_source" not in entry


@pytest.mark.parametrize("offset", range(9, 22))
def test_state_and_jobs_agree_at_every_offset(world, offset: int) -> None:
    """The X2 invariant, checked across the whole log rather than at one
    convenient point — two canonical reductions answering one question
    two ways is the defect, and it would come back the moment either
    grew a clause the other did not."""
    log, tl = world
    st = {c["referent"] for c in state(log, tl, offset, "/work/jobs")["claims"]}
    jb = {t["job"] for t in jobs(log, tl, offset, "/work/jobs")["taken"]}
    assert st == jb, f"state says {sorted(st)}, jobs says {sorted(jb)} at {offset}"
