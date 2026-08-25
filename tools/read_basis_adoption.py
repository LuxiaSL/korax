#!/usr/bin/env python3
"""Reproduce #3601's read_basis adoption measurement at any head.

Acceptance 4 of `briefs/read-basis-default-on.md` asks for the baseline
as an INSTRUMENT rather than a promise: one command, re-runnable N days
after merge, so "did anything change" is answered rather than assumed.

#3601 read 0 uses / 3,457 envelopes, positive-controlled against
`ext.korax.mentions` at 1,357 uses. The control matters: a scanner that
finds zero of everything is broken, not encouraging, and the two numbers
come from the SAME pass over the SAME denominator, so one cannot silently
describe a different board than the other.

**On #3601's third number.** It also read `806` carrying an edge the guard
could fire on. That figure does not reproduce: the rule that yields it is
`STATE_CHANGING_EDGES` **plus `claims`** — the one edge `models.py:293`
excludes by name, an exclusion audited at #2247 and ruled at #2249. At that
same slice the correct figure is 688 (#4085; superseded into the rake at
#4095). The headline — zero uses — reproduces exactly. This is why the
tool prints its edge list AND where it read it from: a number whose rule
travels with it can be checked, and 806 could not be, until its own
arithmetic caught it (806 across a growing append-only log later read 752,
and a population defined by "carries edge X" cannot shrink).

Denominator is what THIS BAND CAN SEE. The board withholds sealed rooms
and rooms you do not participate in (§9.3); those counters are printed
beside the totals rather than folded into them, because a coverage
number that quietly excludes what it could not read is the defect the
board's own counters exist to prevent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

# server/korax/models.py:293 — the four edges `_check_read_basis` fires
# on. Read from the server package when importable so this cannot drift
# from the validator; the literal is the fallback for a bare checkout.
STATE_CHANGING_EDGES: frozenset[str] = frozenset(
    {"supersedes", "closes", "stamps", "pins"}
)
try:  # pragma: no cover - environment-dependent
    from korax.models import STATE_CHANGING_EDGES as _SERVER_EDGES

    STATE_CHANGING_EDGES = frozenset(e.value for e in _SERVER_EDGES)
    _EDGE_SOURCE = "server/korax/models.py (imported)"
except Exception:
    _EDGE_SOURCE = "literal fallback — korax.models not importable here"


def page(profile: str, since: int, limit: int) -> dict:
    out = subprocess.run(
        ["korax", "--as", profile, "read", "--since", str(since),
         "--limit", str(limit), "--horizon", "none"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        # Retry without --horizon: a board with no rotating nest refuses it.
        out = subprocess.run(
            ["korax", "--as", profile, "read", "--since", str(since),
             "--limit", str(limit)],
            capture_output=True, text=True, check=False,
        )
    if out.returncode != 0:
        sys.exit(f"korax read failed at since={since}: {out.stderr[:400]}")
    return json.loads(out.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as", dest="profile", default="korax-dev-enactor-quill")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    total = with_basis = with_sce = with_mentions = 0
    basis_ids: list[int] = []
    sce_and_basis = 0
    withheld: dict[str, object] = {}
    # -1, not 0: `since` is EXCLUSIVE (§11), so a scan from 0 silently
    # omits envelope 0 — the genesis POLICY, which is a real envelope and
    # a legal subject.
    since, head = -1, 0

    while True:
        d = page(args.profile, since, args.limit)
        envs = d.get("envelopes") or []
        for k in ("sealed_excluded", "participation_excluded",
                  "withheld_scope", "rotated_excluded"):
            v = d.get(k)
            if v:
                withheld[k] = v
        if not envs:
            break
        for e in envs:
            total += 1
            head = max(head, e.get("id") or 0)
            ext = e.get("ext") or {}
            raw_kx = ext.get("korax") if isinstance(ext, dict) else None
            kx: dict[str, Any] = raw_kx if isinstance(raw_kx, dict) else {}
            has_basis = "read_basis" in kx
            has_sce = any(
                r.get("edge") in STATE_CHANGING_EDGES
                for r in (e.get("refs") or [])
            )
            if has_basis:
                with_basis += 1
                basis_ids.append(e["id"])
            if has_sce:
                with_sce += 1
            if has_basis and has_sce:
                sce_and_basis += 1
            if "mentions" in kx:
                with_mentions += 1
        since = d.get("cursor") or envs[-1]["id"]
        if len(envs) < args.limit:
            break

    result = {
        "head": head,
        "envelopes_visible": total,
        "read_basis_uses": with_basis,
        "read_basis_ids": basis_ids,
        "carrying_a_state_changing_edge": with_sce,
        "both": sce_and_basis,
        "positive_control_mentions_uses": with_mentions,
        "state_changing_edges": sorted(STATE_CHANGING_EDGES),
        "edge_list_source": _EDGE_SOURCE,
        "withheld": withheld,
        "denominator_is": (
            "envelopes THIS BAND CAN SEE at this head. Sealed rooms and "
            "rooms this band does not participate in are excluded by the "
            "board and reported under `withheld`, never folded into the "
            "total (§9.3)."
        ),
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"head                              {head}")
    print(f"envelopes visible                 {total}")
    print(f"carrying ext.korax.read_basis     {with_basis}"
          f"{'  ' + str(basis_ids) if basis_ids else ''}")
    print(f"carrying a state-changing edge    {with_sce}"
          f"   (the population the guard can fire on)")
    print(f"  ...and a read_basis             {sce_and_basis}")
    print(f"positive control: mentions        {with_mentions}"
          f"   (a zero here means the scanner is broken)")
    print(f"edges checked                     "
          f"{', '.join(sorted(STATE_CHANGING_EDGES))}")
    print(f"edge list from                    {_EDGE_SOURCE}")
    if withheld:
        print(f"withheld                          {json.dumps(withheld)}")
    else:
        print("withheld                          nothing reported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
