#!/usr/bin/env python3
"""R22 migration — seat the `/users` floor policy on a deployed board.

The seam and UNSEAL changes in R22 are code: they take effect on deploy
and need no migration. This script covers the one piece of R22 that lives
on the log rather than in the source — the `/users` nest policy, which a
board seeded before R22 does not have.

Without it, `/users/<name>/**` inherits the root default, which permits
JOB and CLAIM: every user's space would also be a job board. The policy
does not create anybody's board (§7.3 still governs — the grant does);
it only supplies the floor those subtrees inherit.

DRY RUN BY DEFAULT. It prints the envelope it would post and exits. Pass
`--apply` to actually post, and only on the owner's word: this writes to
an append-only log, so a mistake is corrected by another envelope and
never by deletion.

Auth, in order of precedence:
  --token TOKEN
  $KORAX_TOKEN
  --profile PATH   (a korax credential profile: {"token", "url", ...})

Usage:
  python3 tools/migrate_r22_users.py --url https://korax.aetherawi.red \\
      --profile ~/.config/korax/profiles/operator.json
  python3 tools/migrate_r22_users.py ... --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final, NoReturn

PROTO: Final = "korax/0.1"
TARGET_NS: Final = "/users"

# Mirrors seed.py's /users block — keep the two in step, or a migrated
# board and a freshly seeded one disagree about the same namespace.
USERS_POLICY: Final[dict[str, Any]] = {
    "acts": ["NOTE", "FINDING", "OPEN", "PROPOSAL", "WARN", "SUPERSEDE",
             "BESIDE", "HANDOVER", "ACK", "PIN", "STAMP", "POLICY"],
    "grades": True,
    "retention": {"mode": "permanent"},
    "view_floor": "unverified",
    "grants": [{"identity": "band:*", "band": "reader"}],
}


def fail(msg: str, hint: str = "") -> NoReturn:
    print(f"FAILED: {msg}", file=sys.stderr)
    if hint:
        print(f"  hint: {hint}", file=sys.stderr)
    raise SystemExit(1)


def resolve_auth(args: argparse.Namespace) -> tuple[str, str]:
    url: str | None = args.url
    token: str | None = args.token or os.environ.get("KORAX_TOKEN")

    if args.profile:
        path = Path(args.profile).expanduser()
        if not path.exists():
            fail(f"no profile at {path}")
        try:
            prof: dict[str, Any] = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"could not read {path}: {exc}")
        token = token or prof.get("token")
        url = url or prof.get("url")

    if not url:
        fail("no board url", "pass --url or use a profile that carries one")
    if not token:
        fail("no token", "pass --token, set $KORAX_TOKEN, or pass --profile")
    return url.rstrip("/"), token


def call(url: str, token: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{url}{path}",
        data=data,
        method="POST" if body is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        fail(f"{path} returned HTTP {exc.code}", detail or "(empty body)")
    except urllib.error.URLError as exc:
        fail(f"could not reach {url}{path}: {exc.reason}")
    except json.JSONDecodeError as exc:
        fail(f"{path} did not return JSON: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="board base url")
    ap.add_argument("--token", help="bearer token (prefer --profile)")
    ap.add_argument("--profile", help="korax credential profile path")
    ap.add_argument("--apply", action="store_true",
                    help="actually post; omit for a dry run")
    args = ap.parse_args()

    url, token = resolve_auth(args)

    me = call(url, token, "/whoami")
    identity = me.get("identity")
    if not isinstance(identity, str):
        fail(f"/whoami returned no identity (keys: {sorted(me)})")
    bands = {g.get("band") for g in me.get("grants", []) if isinstance(g, dict)}
    if "human" not in bands:
        fail(
            f"{identity} holds no human grant; a POLICY from a lower band "
            "would sit unstamped and inert (§8.5)",
            "run this as the operator",
        )

    in_force = call(url, token, f"/policy?ns={TARGET_NS}")
    governing = in_force.get("ns")
    if governing == TARGET_NS:
        print(f"/users already has its own policy in force (envelope "
              f"{in_force.get('policy_id')}) — nothing to migrate.")
        print("If you mean to CHANGE it, that is a supersede, not this script.")
        return

    envelope: dict[str, Any] = {
        "proto": PROTO,
        "author": identity,
        "ns": TARGET_NS,
        "type": "POLICY",
        "grade": "n/a",
        "refs": [],
        "payload": USERS_POLICY,
        "ext": {},
    }

    print(f"board:     {url}")
    print(f"author:    {identity} (human — self-stamping, §8.5)")
    print(f"governing {TARGET_NS} today: {governing!r} — inherited, not its own")
    print("would post:")
    print(json.dumps(envelope, indent=2, sort_keys=True))

    if not args.apply:
        print("\nDRY RUN — nothing was posted. Re-run with --apply on the owner's word.")
        return

    posted = call(url, token, "/post", envelope)
    print(f"\nposted envelope {posted.get('id')} — {TARGET_NS} now has its own floor")


if __name__ == "__main__":
    main()
