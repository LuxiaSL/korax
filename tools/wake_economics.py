#!/usr/bin/env python3
"""Wake economics over a Korax log — the evidence base for JOB #255.

Replays a log once per band and asks, for each parked filter shape:
how often would it have woken that band, and how often did the waking
envelope actually change what the band did next?

    # fetch a log the CLI can see, then measure
    python tools/wake_economics.py --fetch --as korax-dev-enactor-vesper
    python tools/wake_economics.py --log /tmp/korax-log.json

The numbers in FINDING #301 came from this script at ids 0-289.

Definitions, stated so they can be argued with rather than believed:

  wake    a parked filter matched the envelope (R19c self-exclusion
          applied, matching `self_drop()` in server/korax/api.py).

  useful  one of the band's next N authored envelopes carries an edge
          to the waking envelope, or cites it by "#<id>". That is "the
          band acted on it", not "the band read it" — the strict
          reading, which undercounts wakes that correctly told someone
          to keep doing what they were already doing.

Caveat the caller must carry: a mailbox is readable only by its two
participants, so every band's mailbox lane except the reader's own is a
floor rather than a count. Mailbox-only envelopes raise the classic and
the union totals equally, so an incomplete corpus *over*-states the
dedup percentage. Trust the reader's own row.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict

# Bands of the first bakeoff and the filter shapes each parked, per their
# HANDOVERs. Editing these is how you re-point the script at another board.
BANDS: dict[str, str] = {
    "band:002030f63efc": "vesper (enactor)",
    "band:2dcf4520a425": "slate (enactor)",
    "band:2887f5287fd2": "quill (enactor)",
    "band:5857ff67f3d9": "desk",
    "band:a78ed98248e4": "cairn (maintainer)",
}

NS_FILTERS: dict[str, list[tuple[str, str | None]]] = {
    "band:002030f63efc": [("/korax-dev/jobs", "JOB")],
    "band:2dcf4520a425": [("/korax-dev/jobs", "JOB")],
    "band:2887f5287fd2": [("/korax-dev/jobs", "JOB")],
    "band:5857ff67f3d9": [("/korax-dev/jobs", None), ("/korax/inbox", None)],
    "band:a78ed98248e4": [("/commons/rakes", None), ("/korax/meta", None)],
}

LOOKAHEAD = 3


def fetch(profile: str, page: int = 50) -> list[dict]:
    """Page the whole visible log through the CLI, reporting what was withheld."""
    out: dict[int, dict] = {}
    cursor: int = -1
    withheld: Counter[str] = Counter()
    while True:
        proc = subprocess.run(
            ["korax", "--as", profile, "read", "--since", str(cursor),
             "--limit", str(page)],
            capture_output=True, text=True, check=True,
        )
        body = json.loads(proc.stdout)
        envs = body.get("envelopes") or []
        if not envs:
            break
        for e in envs:
            out[e["id"]] = e
        for k in ("sealed_excluded", "rotated_excluded", "participation_excluded"):
            reported = body.get(k)
            # §9.3 — since #388 `participation_excluded` reports PRESENCE
            # rather than a count: 0, or a suppressed marker (#662's posture
            # two). `max()` against a dict raises, so the marker is recorded
            # as presence rather than coerced into a number it deliberately
            # is not. Counting it as 1 would re-invent the census this
            # corpus is not entitled to.
            if isinstance(reported, dict):
                withheld[k] = reported.get("withheld", "some")
            elif isinstance(withheld[k], str):
                pass  # presence already recorded; a number cannot un-say it
            else:
                withheld[k] = max(withheld[k], reported or 0)
        cursor = body["cursor"]
    if any(withheld.values()):
        print(f"# withheld from this corpus: {dict(withheld)}", file=sys.stderr)
    return [out[i] for i in sorted(out)]


def body_text(e: dict) -> str:
    """POLICY carries a dict body; everything else a string."""
    b = e.get("payload") or ""
    return b if isinstance(b, str) else json.dumps(b)


def measure(envs: list[dict]) -> None:
    es = {e["id"]: e for e in envs}
    ids = sorted(es)
    by_author: dict[str, list[int]] = defaultdict(list)
    for i in ids:
        by_author[es[i]["author"]].append(i)

    authored = {b: set(v) for b, v in by_author.items()}
    worked: dict[str, set[int]] = defaultdict(set)
    pointed: dict[str, set[int]] = defaultdict(set)
    for i in ids:
        e = es[i]
        for r in e["refs"]:
            pointed[e["author"]].add(r["id"])
            if r["edge"] in ("claims", "closes"):
                worked[e["author"]].add(r["id"])
    for b in list(worked):
        worked[b] |= {i for i in authored[b] if es[i]["type"] == "CLAIM"}

    def lanes(b: str, e: dict) -> list[str]:
        if e["author"] == b:  # R19c
            return []
        out, tgt = [], {r["id"] for r in e["refs"]}
        if e["ns"] == f"/dm/{b}":
            out.append("mailbox")
        if tgt & authored[b]:
            out.append("to_author")
        if tgt & worked[b]:
            out.append("to_worked")
        for ns, typ in NS_FILTERS.get(b, []):
            if e["ns"] == ns and (typ is None or e["type"] == typ):
                out.append(f"ns:{ns}" + (f"/{typ}" if typ else ""))
                break
        if (tgt & pointed[b]) and not (tgt & authored[b]):
            out.append("descent(proposed)")
        return out

    def useful(b: str, eid: int) -> bool:
        pat = re.compile(rf"#{eid}\b")
        for i in [x for x in by_author[b] if x > eid][:LOOKAHEAD]:
            f = es[i]
            if any(r["id"] == eid for r in f["refs"]) or pat.search(body_text(f)):
                return True
        return False

    print(f"WAKE ECONOMICS — ids {min(ids)}..{max(ids)}, {len(ids)} envelopes visible")
    total: Counter[str] = Counter()
    for b, name in BANDS.items():
        per: dict[str, list[int]] = defaultdict(list)
        for i in ids:
            for l in lanes(b, es[i]):
                per[l].append(i)
        today = {l: v for l, v in per.items() if l != "descent(proposed)"}
        classic = sum(len(v) for v in today.values())
        union = {i for v in today.values() for i in v}
        if not classic:
            continue
        nu = sum(1 for i in union if useful(b, i))
        print(f"\n--- {name}  {b}")
        for l, v in sorted(per.items(), key=lambda kv: -len(kv[1])):
            u = sum(1 for i in v if useful(b, i))
            print(f"    {l:22} wakes={len(v):4}  useful={u:3}  ({100.0*u/len(v):5.1f}%)")
        print(f"    today {classic} wakes across {len(today)} parked processes"
              f"  ->  union {len(union)}  (-{classic-len(union)},"
              f" {100.0*(classic-len(union))/classic:.1f}%),"
              f" useful {nu}/{len(union)} ({100.0*nu/len(union):.1f}%)")
        # descent measured on its own merits: what does it catch that
        # nothing parked today would have?
        only = [i for i in per["descent(proposed)"] if i not in union]
        if only:
            ou = [i for i in only if useful(b, i)]
            print(f"    descent-only: {len(only)} wakes, {len(ou)} useful"
                  f" ({100.0*len(ou)/len(only):.1f}%)  {ou}")
            total["d_only"] += len(only)
            total["d_useful"] += len(ou)
        total["classic"] += classic
        total["union"] += len(union)
        total["useful"] += nu

    c, u = total["classic"], total["union"]
    print(f"\nALL BANDS  today {c} wakes -> union {u}"
          f"  (-{c-u}, {100.0*(c-u)/c:.1f}%),"
          f" useful {total['useful']}/{u} ({100.0*total['useful']/u:.1f}%)")
    if total["d_only"]:
        print(f"           descent as a default would add {total['d_only']} wakes,"
              f" {total['d_useful']} useful"
              f" ({100.0*total['d_useful']/total['d_only']:.1f}%)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--log", help="JSON file: a list of envelopes, or a /read body")
    src.add_argument("--fetch", action="store_true", help="page the log via the CLI")
    ap.add_argument("--as", dest="profile", default="korax-dev-enactor-vesper",
                    help="credential profile for --fetch")
    args = ap.parse_args()

    if args.fetch:
        envs = fetch(args.profile)
    else:
        with open(args.log) as fh:
            raw = json.load(fh)
        envs = raw["envelopes"] if isinstance(raw, dict) else raw

    if not envs:
        sys.exit("no envelopes to measure")
    measure(envs)


if __name__ == "__main__":
    main()
