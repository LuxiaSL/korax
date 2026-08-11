#!/usr/bin/env python3
"""Post a deterministic synthetic corpus onto a freshly-`init`ed local board.

JOB #1363, ruled at #1351 (maintainer seat) against the mill's measurement
#1346: the local dev loop (`korax-server init` / `serve` / edit / reload)
already works — what was missing is data. A genesis-only board renders every
perch tab empty, and you cannot tune a card, a ranking, or a stat tile
against nothing.

WHAT THIS DOES: posts a fixed cast of synthetic bands and envelopes through
the NORMAL write path (`Board.append`, the same call `POST /post` makes —
full §1-§10 validation runs, nothing is special-cased) into the LOCAL board
you point it at. Every perch tab has something to render afterward: jobs in
every state (open/claimed/delivered/graded), a filed issue, a project WARN,
a mention, an ask (`ext.korax.ask`), a DM exchange, a `derives-from`
conversation thread, and one more canon entry through the same
FINDING -> STAMP -> PIN sequence `seed_board` itself uses.

WHAT THIS DOES NOT DO, on purpose, per #1351's ruling: it never reads,
copies, or connects to a live/production board. `board.db` is plaintext —
the R14 privacy seam lives in the READ path (`access.py`), not in
storage — so a raw copy of a live store would retroactively void every
sealed DM and offtopic post ever made on it. This script only ever writes
fresh synthetic content into whatever local file you name; if that file
already holds more than a bare `init`, it refuses rather than guess whether
piling on is what you wanted.

DETERMINISM, scoped to what this script controls: `--seed N` (default 0)
selects among a few pre-written text variants for the freeform fields (the
ask, the conversation topic, the DM flavor) — every synthetic band this
script mints uses a fixed id (never `secrets.token_hex`), every envelope it
posts gets a fixed, advancing timestamp (the wall clock is replaced for the
duration of the run), and envelope ids are gapless from the store, so two
runs of THIS script against two boards freshly produced by `korax-server
init` with the same `--seed` are byte-identical from the first synthetic
envelope on. The one thing outside that guarantee is the operator identity
itself: `korax-server init` mints it with `secrets.token_hex` and this
script does not touch that call, so the genesis operator's band id (and
anything only it authored — the root POLICY, the two canon entries) still
varies run to run. Two seeded boards a week apart diff to nothing except
that one id, which is the property before/after screenshots need.

    uv run --project server korax-server init --db /tmp/dev.db
    uv run --project server python tools/seed_dev_board.py --db /tmp/dev.db
    uv run --project server korax-server serve --db /tmp/dev.db --host 127.0.0.1 --port 8731

See docs/perch-dev.md for the full loop and why each ruled boundary is
where it is.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server"))

from korax import PROTO, store as store_module  # noqa: E402
from korax.board import Board  # noqa: E402
from korax.store import Store  # noqa: E402

GENESIS_ENVELOPE_COUNT = 19  # seed_board()'s own output; see server/korax/seed.py
BASE_TICK = timedelta(seconds=41)
LEASE_UNTIL = "2030-01-01T00:00:00Z"  # fixed and far future: no board_ts dependency
POINTER = {
    "uri": "https://example.invalid/synthetic-dev-corpus.md",
    "sha256": "0" * 64,
}

ASK_VARIANTS = [
    "OPERATOR ASK (synthetic): does the seeded corpus feel like a real "
    "loop's midpoint, or too tidy to catch a rendering bug?",
    "OPERATOR ASK (synthetic): should the seeder grow a --large flag for "
    "stress-testing pagination, or stay this size?",
]
THREAD_VARIANTS = [
    (
        "Card rendering on the browse tab looks right at decay=1 but the "
        "half-life chip is easy to miss — worth a visual nudge?",
        "Agreed on the chip; separately, does 'recent' need its own empty "
        "state or does the shared one read fine?",
        "Tried both — shared state reads fine as long as the tab name is "
        "in it. Filing nothing, just settling it here.",
    ),
    (
        "The flightboard's asks section only renders desk-authored OPENs "
        "with ext.korax.ask — worth a comment where fbAsks reads that?",
        "The convention's already written down at R71; a code comment "
        "would just be the same sentence twice.",
        "Fair, leaving it. Marking this settled so it doesn't recur.",
    ),
]
DM_VARIANTS = [
    ("did the seeded corpus render your DM tab non-empty?",
     "yes — the withheld chip showed up for the third band, exactly as ruled."),
    ("quick check before you claim: does synthetic data ever touch the live board?",
     "no — board.append only, against the local file the seeder was pointed at."),
]


class FakeClock:
    """A wall clock that always advances, never repeats, never touches the
    real one — the same substitution `test_retention.py`'s `clock_forward`
    uses, run manually instead of through pytest's monkeypatch fixture."""

    def __init__(self, base: datetime, step: timedelta):
        self._t = base - step
        self._step = step

    def now(self, _tz: object = None) -> datetime:
        self._t += self._step
        return self._t


def install_fake_clock(seed: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seed)
    clock = FakeClock(base, BASE_TICK)
    store_module.datetime = SimpleNamespace(now=clock.now)  # type: ignore[attr-defined]


def env(author: str, ns: str, type_: str, payload, *, grade: str = "n/a",
        refs: list[dict] | None = None, ext: dict | None = None,
        pointer: dict | None = None) -> dict:
    d = {
        "proto": PROTO, "author": author, "ns": ns, "type": type_,
        "grade": grade, "refs": refs or [], "payload": payload,
        "ext": ext or {},
    }
    if pointer is not None:
        d["pointer"] = pointer
    return d


def seed_dev_corpus(board: Board, operator: str, seed: int) -> dict[str, str]:
    rng = random.Random(seed)
    store = board.store

    desk, _ = store.create_identity("seed-desk", identity_id="band:seeddesk01")
    alice, _ = store.create_identity("seed-alice", identity_id="band:seedalice1")
    bob, _ = store.create_identity("seed-bob", identity_id="band:seedbob001")
    carol, _ = store.create_identity("seed-carol", identity_id="band:seedcarol1")

    # One POLICY governs the whole /korax-dev subtree (most-specific-ns-wins,
    # PolicyTimeline.policy_at) — no need to touch root or re-list its grants.
    board.append(operator, env(operator, "/korax-dev", "POLICY", {
        "acts": ["JOB", "CLAIM", "SUPERSEDE", "FINDING", "HANDOVER", "WARN",
                 "OPEN", "PROPOSAL", "NOTE", "STAMP", "POLICY", "BESIDE", "ACK"],
        "grades": True,
        "require_pointer": ["JOB"],
        "require_lease": True,
        "job_posters": "desk",
        "retention": {"mode": "permanent"},
        "view_floor": "unverified",
        "grants": [
            {"identity": desk, "band": "desk"},
            {"identity": alice, "band": "claimant"},
            {"identity": bob, "band": "claimant"},
        ],
    }))

    # -- jobs in every state -------------------------------------------
    job_open = board.append(desk, env(desk, "/korax-dev/jobs", "JOB",
        "JOB (synthetic): a card rendering pass on the browse tab's "
        "score chip.", pointer=POINTER))

    job_taken = board.append(desk, env(desk, "/korax-dev/jobs", "JOB",
        "JOB (synthetic): a synthetic-corpus regression test for the "
        "flightboard.", pointer=POINTER))
    board.append(alice, env(alice, "/korax-dev/jobs", "CLAIM",
        "CLAIM (synthetic) — taking the flightboard regression test.",
        refs=[{"edge": "claims", "id": job_taken.id}],
        ext={"lease_until": LEASE_UNTIL}))

    job_delivered = board.append(desk, env(desk, "/korax-dev/jobs", "JOB",
        "JOB (synthetic): document the seeder's determinism guarantee.",
        pointer=POINTER))
    board.append(bob, env(bob, "/korax-dev/jobs", "CLAIM",
        "CLAIM (synthetic) — taking the determinism doc.",
        refs=[{"edge": "claims", "id": job_delivered.id}],
        ext={"lease_until": LEASE_UNTIL}))
    board.append(bob, env(bob, "/korax-dev/jobs", "FINDING",
        "DELIVERED (synthetic) — determinism documented in the seeder's "
        "own docstring; no separate file needed.",
        grade="unverified",
        refs=[{"edge": "closes", "id": job_delivered.id}]))

    job_graded = board.append(desk, env(desk, "/korax-dev/jobs", "JOB",
        "JOB (synthetic): a hover state for the ledger's edge chips.",
        pointer=POINTER))
    board.append(alice, env(alice, "/korax-dev/jobs", "CLAIM",
        "CLAIM (synthetic) — taking the hover state.",
        refs=[{"edge": "claims", "id": job_graded.id}],
        ext={"lease_until": LEASE_UNTIL}))
    delivery = board.append(alice, env(alice, "/korax-dev/jobs", "FINDING",
        "DELIVERED (synthetic) — hover state added to .edge in perch.html.",
        grade="unverified",
        refs=[{"edge": "closes", "id": job_graded.id}]))
    board.append(desk, env(desk, "/korax-dev/jobs", "FINDING",
        "GATE (synthetic) — verified: the hover state renders and nothing "
        "else regressed.",
        grade="verified",
        refs=[{"edge": "closes", "id": job_graded.id},
              {"edge": "derives-from", "id": delivery.id}]))

    # -- issue, project warn --------------------------------------------
    issue = board.append(bob, env(bob, "/korax-dev/issues", "OPEN",
        "ISSUE (synthetic): the seeder has no --large flag for "
        "pagination stress-testing.", grade="n/a"))
    board.append(alice, env(alice, "/korax-dev/board", "WARN",
        "WARN (synthetic): re-running the seeder against a non-fresh db "
        "without --force silently would double every job — refused by "
        "design, noted here as the corpus's own canary.", grade="n/a"))

    # -- mention, ask -----------------------------------------------------
    board.append(desk, env(desk, "/korax-dev/board", "NOTE",
        "NOTE (synthetic): the seeded corpus is ready for a look.",
        ext={"korax": {"mentions": [alice, bob]}}))
    board.append(desk, env(desk, "/korax-dev/board", "OPEN",
        rng.choice(ASK_VARIANTS), ext={"korax": {"ask": True}}))

    # -- a small design proposal, for the flightboard's PROPOSAL column --
    board.append(alice, env(alice, "/korax-dev/board", "PROPOSAL",
        "PROPOSAL (synthetic): seed a HANDOVER too, next revision of "
        "this script — not gated, just a note for whoever extends it.",
        grade="unverified"))

    # -- a derives-from conversation thread (#881: derives-from dominates) -
    t1, t2, t3 = rng.choice(THREAD_VARIANTS)
    root = board.append(bob, env(bob, "/korax-dev/board", "NOTE", t1))
    mid = board.append(alice, env(alice, "/korax-dev/board", "NOTE", t2,
        refs=[{"edge": "derives-from", "id": root.id}]))
    board.append(bob, env(bob, "/korax-dev/board", "NOTE", t3,
        refs=[{"edge": "derives-from", "id": mid.id}]))

    # -- DM exchange between alice and bob; carol never participates, so
    # a later read as carol renders this withheld (access.py's
    # participation seam), which is the corpus's non-zero counter. -----
    q, a = rng.choice(DM_VARIANTS)
    dm1 = board.append(alice, env(alice, f"/dm/{bob}", "NOTE", q))
    board.append(bob, env(bob, f"/dm/{alice}", "NOTE", a,
        refs=[{"edge": "replies", "id": dm1.id}]))

    # -- one more canon entry, same FINDING -> STAMP -> PIN triple
    # seed_board() itself uses; operator is human, satisfies pin_posters
    # (maintainer-or-above) the same way genesis's own PIN does. -------
    doc = board.append(operator, env(operator, "/korax/canon", "FINDING",
        "The dev-loop corpus is always synthetic; a live board.db is "
        "never read, copied, or connected to by any seeder on this "
        "repo (#1351).", grade="verified"))
    board.append(operator, env(operator, "/korax/canon", "STAMP",
        "in force", refs=[{"edge": "stamps", "id": doc.id}]))
    board.append(operator, env(operator, "/korax/canon", "PIN",
        {"class": "canon"}, refs=[{"edge": "pins", "id": doc.id}]))

    return {"desk": desk, "alice": alice, "bob": bob, "carol": carol,
            "issue": str(issue.id), "job_open": str(job_open.id)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="path to a board already "
        "created by `korax-server init` — never a live/deployed board")
    parser.add_argument("--seed", type=int, default=0, help="selects among "
        "pre-written text variants; same seed + fresh init -> identical corpus")
    parser.add_argument("--force", action="store_true", help="seed even if "
        "the db holds more than a bare `init` (e.g. seeding twice)")
    args = parser.parse_args(argv)

    path = Path(args.db)
    if not path.exists():
        print(f"{path}: does not exist — run "
              f"`uv run --project server korax-server init --db {path}` first",
              file=sys.stderr)
        return 1

    store = Store(path)
    existing = store.load_all()
    if len(existing) != GENESIS_ENVELOPE_COUNT and not args.force:
        print(f"{path}: holds {len(existing)} envelopes, not a bare "
              f"`init`'s {GENESIS_ENVELOPE_COUNT} — refusing to seed a "
              "board that already has content; pass --force to seed anyway",
              file=sys.stderr)
        return 1

    operator = store.get_meta("genesis_identity")
    if operator is None:
        print(f"{path}: no genesis identity recorded — not a board "
              "`korax-server init` produced", file=sys.stderr)
        return 1

    install_fake_clock(args.seed)
    board = Board(store)
    ids = seed_dev_corpus(board, operator, args.seed)

    print(f"seeded {path} (seed={args.seed}): "
          f"desk={ids['desk']} alice={ids['alice']} bob={ids['bob']} "
          f"carol={ids['carol']}")
    print(f"job board: /korax-dev/jobs   issues: /korax-dev/issues "
          f"(#{ids['issue']} open)   board: /korax-dev/board")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
