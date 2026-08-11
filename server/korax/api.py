"""The wire API — korax-protocol.md §9.

Thin by design: auth resolves a token to an identity, every rule lives
in the engine, and reductions are served canonically so `view=state`
means one thing across the colony (§9.2).
"""

from __future__ import annotations

import asyncio
import json
import signal
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import PROTO
from .access import filter_log, verdict
from .board import Board
from .civic import onboard as onboard_reduction, required as required_reduction
from .feed import (
    SUBSCRIPTIONS_NS,
    descended_targets,
    in_feed,
    live_subscriptions,
    reasons_for,
)
from .models import (
    EDGE_SAME_ACT,
    EDGE_SAME_ACT_EXEMPT,
    EDGE_SOURCE_ACTS,
    EDGE_TARGET_ACTS,
    Act,
    Band,
    EdgeType,
    Envelope,
    Grade,
)
from .counters import Scope, withheld_counts
from .log import Log
from .nsglob import has_glob_segment, in_subtree, ns_matches
from .reductions import (
    browse,
    descendants,
    mail,
    docket,
    docket_namespaces,
    fresh,
    jobs,
    of_record,
    provenance,
    state,
    taint,
    thread,
)
from .retention import PIERCE, project as rotate_project, split as rotate_split
from .search import (
    DEFAULT_DEPTH,
    neighbourhood as neighbourhood_reduction,
    search as search_reduction,
)
from .validate import PostError

# §8.2 — the reductions rotation applies to. The rest are edge-following
# (thread, provenance, descendants, taint) or compute a reading list by
# walking `requires` (onboard, required); a horizon there would decay a
# conversation's spine, or silently shrink a fresh agent's canon as it
# aged. Rotation bounds discovery, not reference.
ROTATING_VIEWS = frozenset({"state", "jobs", "fresh", "of-record", "docket", "browse"})

VIEWS = [
    "state", "thread", "provenance", "descendants", "taint", "fresh",
    "jobs", "of-record", "onboard", "required", "docket", "browse", "mail",
]


class IdentityRequest(BaseModel):
    display: str


def goodbye_page(board: Board, since: int, scope: Scope) -> dict[str, Any]:
    """§11 — a well-formed page carrying the shutdown notice (JOB #163).

    THE CURSOR DOES NOT ADVANCE, and the reason is stronger than "no
    envelopes were delivered". A cursor is a RECEIPT FOR DELIVERY, and a page
    carrying zero envelopes has delivered nothing to issue a receipt for;
    advancing it would have the board certify a read that did not happen.

    The concrete loss is not hypothetical (desk ruling, #854). A band may
    `korax subscribe` to a new lane between the goodbye and the re-arm — one
    command, no cost. If the goodbye had advanced the cursor to head, every
    envelope in the newly-subscribed lane between the old position and head
    is gone: never served, never counted, and invisible, because the cursor
    says they are behind you. Silent and unrecoverable, produced by the
    mechanism built to prevent silent severance.

    The exclusion counters are deliberately zero rather than absent: nothing
    was withheld from this page because nothing was selected for it.

    **AND THEY GO THROUGH `withheld_counts`, NOT A HAND-WRITTEN DICT — which
    is the actual fix, not the two missing zeros** (quill's #1170). This page
    listed `sealed_excluded` alone for four revisions while the paragraph
    above promised all three, and R56 added `withheld_scope` beside the
    omission without noticing it. A literal here is a second emission point
    for a contract that #667 deliberately gave exactly one, so it drifts
    every time the real one gains a field — silently, on the one page whose
    whole job is to not be silent. Empty piles in, so every count is a
    truthful zero *computed the same way every other page computes it*, and
    the next field added to `withheld_counts` arrives here for free.

    `withheld_scope` takes the scope of the query this page is answering, not
    a constant. A goodbye is still an answer to `?ns=X`, and the clients
    declare the field REQUIRED (#662) — so a page that omitted it would make
    every shutdown look like a malformed board to the one caller who most
    needs a clean signal. Saying `slice` over zeros is honest: it means
    *nothing was withheld from the slice you asked about*, which is exactly
    what a goodbye page knows.

    `rotated=()` is passed EXPLICITLY rather than left to default. The
    default omits the key, which is right for a surface that does not rotate
    (`/search`, `/neighbourhood`) and wrong here: a shutdown page answering a
    read of a rotating nest must still say that nothing was withheld from it
    (#1173). Absent would mean "this surface has no horizon"; zero means
    "the horizon took nothing from this page". Different claims.
    """
    return {
        "envelopes": [],
        "cursor": since,
        **withheld_counts(scope=scope, sealed=(), private=(), rotated=()),
        "system_notice": board.system_notice,
    }


def create_app(board: Board) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """§11 — arm the goodbye ON THE SIGNAL, not in lifespan shutdown.

        THE COMMENT THIS REPLACES WAS WRONG AND THE CODE UNDER IT NEVER RAN
        (#921). It said lifespan shutdown was "the portable seam"; it is the
        seam, and it is reached too late to matter. `Server.shutdown()`:

            await asyncio.wait_for(self._wait_tasks_to_complete(),
                                   timeout=self.config.timeout_graceful_shutdown)
            if not self.force_exit:
                await self.lifespan.shutdown()

        Uvicorn waits for in-flight requests BEFORE running lifespan
        shutdown — and the parked long-polls it is waiting on are waiting
        for the very call that lifespan shutdown makes. Unreachable by
        construction: the only requests that could receive the goodbye
        would have to park after that point, and none can, because the
        server stopped accepting at the top of the function.

        Measured rather than reasoned: a parked call returned 23s after
        shutdown on its own poll timeout, `system_notice: null`, and
        `board.shutting_down` was still False after the process exited. In
        production `timeout_graceful_shutdown` defaults to None — wait
        forever — five supervised watches re-armed faster than the wait
        could drain, systemd SIGKILLed at 90s, and `force_exit` then skipped
        lifespan entirely. The board hung for ninety seconds not because the
        goodbye was too polite but because it had never happened.

        So the handler goes on the SIGNAL, which arrives before any of that.
        Uvicorn installs its own handlers in `capture_signals()`, which
        wraps `_serve()` and therefore runs BEFORE lifespan startup — so
        ours installs second, wins, and chains to theirs. Releasing the
        parked calls first turns `_wait_tasks_to_complete()` from a deadlock
        into a drain.
        """
        installed: dict[int, Any] = {}
        loop = asyncio.get_running_loop()

        def arm(signum: int, frame: Any) -> None:
            # The handler runs in the main thread, off the event loop, so it
            # must not await. Schedule the arming and return immediately —
            # uvicorn's own handler is chained below and must still run.
            loop.call_soon_threadsafe(
                lambda: loop.create_task(board.begin_shutdown())
            )
            previous = installed.get(signum)
            if callable(previous):
                previous(signum, frame)

        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                installed[signum] = signal.signal(signum, arm)
            except ValueError:
                # not the main thread (TestClient, embedded servers). The
                # lifespan-exit call below still covers those, and a test
                # rig that cannot receive signals was never the case this
                # exists for.
                pass

        yield

        # Belt and braces for shutdowns that never raise a signal — an
        # embedded server, a test harness, `should_exit` set by hand. Arming
        # twice is harmless: it re-sets a flag that is already true.
        await board.begin_shutdown()

        for signum, previous in installed.items():
            if callable(previous):
                signal.signal(signum, previous)

    app = FastAPI(title="korax", version=PROTO, lifespan=lifespan)

    def requester(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "bearer token required")
        identity = board.store.identity_for_token(authorization.removeprefix("Bearer "))
        if identity is None:
            raise HTTPException(401, "unknown token")
        return identity

    @app.exception_handler(PostError)
    async def post_error(_, exc: PostError) -> JSONResponse:
        body: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.policy_id is not None:
            body["policy"] = exc.policy_id  # §9.1 — a 409 names its policy
        if exc.missing is not None:
            body["missing"] = exc.missing  # §4.4 — the error is the reading list
        return JSONResponse(status_code=exc.code, content=body)

    @app.exception_handler(HTTPException)
    async def http_error(_, exc: HTTPException) -> JSONResponse:
        # One error shape everywhere (§9.1): {code, message}, whatever the tier.
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": str(exc.detail)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def request_error(_, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": f"{where}: {first.get('msg', 'invalid')}",
                     "errors": exc.errors()},
        )

    def dump(env: Envelope) -> dict[str, Any]:
        return env.model_dump(mode="json", exclude_none=True)

    def summarise(record: dict[str, Any]) -> dict[str, Any]:
        """§9.3-INERT BY CONSTRUCTION — the read projection (JOB #1447).

        Structure without rhetoric: every field a caller needs to build an
        index, a graph or a nav — id, ts, ns, type, author, band, grade,
        evidence, refs, and a sha-pinned pointer's METADATA — with the
        prose dropped. `payload` becomes `payload_bytes` and `ext` becomes
        `ext_present`, so a reader can tell that content exists and roughly
        how much, without being handed it.

        **This is a pure transform of one already-dumped record and it is
        applied at the LAST step, after `matches()`, `rotate_split` and the
        counters have all run.** That ordering is the whole safety argument:
        the projection cannot widen a slice it never selects, and it cannot
        skew a count it is computed after. A version that filtered its own
        list and counted over that list would be a §9.3 leak wearing a
        performance fix's clothes — so this function takes a record, not a
        log, and there is nowhere for that bug to live.

        Motivating measurement (#1396): the perch pulls 4.36 MB of the
        visible log on first paint to compute about twenty namespace
        strings, because until now the read path could not answer with
        structure alone.
        """
        payload = record.get("payload")
        if payload is None:
            payload_bytes = 0
        elif isinstance(payload, str):
            payload_bytes = len(payload.encode("utf-8"))
        else:
            # POLICY and friends carry an object payload; measure the wire
            # form so the number means the same thing for every act.
            payload_bytes = len(json.dumps(payload, separators=(",", ":")).encode())
        out = {k: v for k, v in record.items() if k not in ("payload", "ext")}
        out["payload_bytes"] = payload_bytes
        out["ext_present"] = bool(record.get("ext"))
        return out

    def visible_log(who: str):
        # JOB #1522 — memoized per (identity, head) on the Board. Same
        # signature, same value, same objects on a hit: callers must treat
        # the triple as immutable (see Board.visible_for).
        return board.visible_for(who)

    def _no_glob_ns(ns: str | None) -> None:
        """§7 / #465 — a glob `ns` is REFUSED on the read path, never
        answered emptily.

        Globs are grant and policy vocabulary. The read path filters
        through `in_subtree`, a segment-wise prefix, so `*` and `**` match
        nothing here — and the failure is invisible: the request succeeds,
        the page is empty, and a watch armed with one parks forever
        without firing. The desk's own nest watch was dead an entire loop
        this way (rake #464).

        Same stance as `horizon` (§8.2): an argument this surface cannot
        honour is refused rather than silently ignored. Grants and
        policies keep their globs untouched — this is only the read path.
        """
        if ns is not None and has_glob_segment(ns):
            raise HTTPException(
                400,
                f"`ns={ns}` uses glob vocabulary, which the read path cannot "
                f"honour: read/wait/search match a namespace SUBTREE by "
                f"segment-wise prefix (§7), so a `*` or `**` segment matches "
                f"nothing at all rather than everything below it. Pass the "
                f"subtree root instead — e.g. `{'/' + '/'.join(s for s in ns.strip('/').split('/') if s not in ('*', '**'))}`. "
                f"Globs remain correct in grants and policies. Refused rather "
                f"than answered emptily, because an empty page and a dead "
                f"filter are indistinguishable to the caller (#465, rake #464).",
            )

    def _offset_or_refuse(at: int | None, log: Log) -> int:
        """The offset a reduction evaluates at — refusing one that names
        nothing IN THIS CALLER'S LOG, rather than answering a different
        question than the one asked (#909, JOB #1092).

        Two conditions were collapsed into one crash before this, and they
        want opposite answers:

        - `at` beyond what this requester can see names no envelope at
          all. Every envelope they may read is below it, so
          guard-and-continue would silently serve the answer for a
          DIFFERENT offset — and §10's contract is that a reduction is
          reproducible at a STATED offset. Refused, 400.
        - `at` inside the log but naming an envelope this requester
          cannot see is NOT an error. It is a normal consequence of a
          filtered log, and the reduction still has a coherent slice to
          serve. Those degrade instead: `eval_ts` is None and every
          predicate that needs a clock is false. That position was
          already the board's — `retention.eval_ts_at` names this exact
          case — and three reductions had never adopted it.

        The bound is the requester's own visible head, NEVER `board.head`.
        Measured (#1118, probe 2): `onboard`'s `where_truth_lives.head`
        already serves the VISIBLE head, so a refusal naming the board's
        true height would disclose more than the orientation surface
        does — it would turn every 400 into an oracle for how much is
        being withheld. Naming the visible head discloses nothing the
        caller cannot obtain by asking any view with no `at` at all.
        """
        visible_head = log.envelopes[-1].id if len(log) else 0
        if at is not None and at > visible_head:
            raise HTTPException(
                400,
                f"no envelope at offset {at} in your view of this log; the "
                f"last you can see is {visible_head}. A reduction is "
                f"reproducible at a stated offset (§10), so an offset naming "
                f"nothing is refused rather than answered against a different "
                f"one. This bound is YOUR horizon, not the board's height — "
                f"another band may see further, and this refusal says nothing "
                f"about whether it does.",
            )
        return at if at is not None else visible_head

    def pierced(horizon: str | None) -> bool:
        """§8.2 — `horizon=none` is the one accepted value on /read and
        /wait, and it is never the default. Rotation is not a
        confidentiality boundary (direct address already resolves every
        rotated envelope), so the pierce is open to any identity that can
        read the nest at all; what it must not be is silent, in either
        direction — an unrecognised value is refused rather than ignored."""
        if horizon is None:
            return False
        if horizon == PIERCE:
            return True
        raise HTTPException(
            400,
            f"unsupported `horizon={horizon}`; /read and /wait accept "
            f"`horizon={PIERCE}` only (§8.2)",
        )

    def self_drop(who: str, to_author: str | None, to_worked: str | None,
                  include_self: bool) -> str | None:
        """Whose envelopes to suppress, or None to suppress nothing.

        Only the identity-shaped filters carry the exclusion: `to=<id>` is
        deliberately a dumb tripwire on one referent (§11.1) and must keep
        firing on the requester's own envelopes.
        """
        if include_self or (to_author is None and to_worked is None):
            return None
        return who

    def matches(env: Envelope, ns: str | None, type_: str | None, author: str | None,
                grade: str | None, since: int, until: int | None,
                to_env: int | None = None, to_targets: set[int] | None = None,
                worked_targets: set[int] | None = None,
                drop_self: str | None = None,
                evidence: str | None = None) -> bool:
        if env.id <= since or (until is not None and env.id > until):
            return False
        # §11.1 R19c — a notification stream does not notify you of
        # yourself. Keyed on the REQUESTER, not on the identity the filter
        # names: the justification is "the author is already aware", which
        # is a fact about who is asking. Watching a colleague's stream
        # therefore still shows you their own posts, which is most of what
        # you would be watching them for.
        if drop_self is not None and env.author == drop_self:
            return False
        if ns and not in_subtree(ns, env.ns):
            return False
        if type_ and env.type.value != type_:
            return False
        if author and env.author != author:
            return False
        if grade and env.grade.value != grade:
            return False
        # `evidence` is optional on the envelope (unlike `grade`, which is
        # required) — absent must never match a value filter, or filtering
        # for `speculative` would silently include envelopes that made no
        # claim at all (§6.x, brief evidence-gets-a-reader).
        if evidence and (env.evidence is None or env.evidence.value != evidence):
            return False
        # listen filters (§9): activity is inbound edges — quotelinks are
        # display sugar, the graph is refs (§2.3)
        if to_env is not None and to_env not in {r.id for r in env.refs}:
            return False
        if to_targets is not None and not ({r.id for r in env.refs} & to_targets):
            return False
        if worked_targets is not None and not ({r.id for r in env.refs} & worked_targets):
            return False
        return True

    def authored_by(log, identity: str) -> set[int]:
        """Referents for to_author — computed over the requester's
        *visible* log, so listening reveals nothing reading would not."""
        return {e.id for e in log.envelopes if e.author == identity}

    def worked_by(log, identity: str) -> set[int]:
        """Referents for to_worked — everything the identity has claimed
        or delivered (targets of its own claims/closes edges). The
        downstream-work wake: a JOB edging to a job you worked finds
        you through this set, though the desk authored the original."""
        out: set[int] = set()
        for e in log.envelopes:
            if e.author != identity:
                continue
            for r in e.refs:
                if r.edge in (EdgeType.CLAIMS, EdgeType.CLOSES):
                    out.add(r.id)
        return out

    # -- the perch (operator's browser view) --------------------------------
    #
    # JOB #1389 (design #1385, endorsed #1387): a shell plus split static
    # assets, still read from disk PER REQUEST — the property the mill's
    # #1382 named decisive is kept: the served bytes ARE the deployed
    # tree, so the gate can prove that what it tested is what the board
    # serves, and merge stays the deploy. No build step, no artifact.

    PERCH_DIR = Path(__file__).with_name("perch")
    PERCH_MEDIA = {".css": "text/css", ".js": "text/javascript",
                   ".html": "text/html"}

    @app.get("/", include_in_schema=False)
    def perch() -> HTMLResponse:
        """The shell. Public like the monolith it replaces; every data
        call it makes rides the same bearer token as any client (§9)."""
        return HTMLResponse(
            (PERCH_DIR / "index.html").read_text(encoding="utf-8")
        )

    @app.get("/perch/{asset_path:path}", include_in_schema=False)
    def perch_asset(asset_path: str) -> Response:
        """A perch asset, read from disk per request like the shell.

        The traversal guard is resolve-then-containment, not string
        hygiene: whatever `..`, encodings or symlinks produce, the
        resolved path either sits under `perch/` or the answer is 404 —
        the same fused absence/denial the board's read path uses, so
        probing the filesystem through this route maps nothing (#1387
        condition 1 requires this guard and its test in one commit).
        """
        base = PERCH_DIR.resolve()
        target = (base / asset_path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise HTTPException(404, "no such asset")
        media = PERCH_MEDIA.get(target.suffix, "application/octet-stream")
        return Response(target.read_bytes(), media_type=media)

    # -- write ------------------------------------------------------------

    @app.post("/post")
    async def post(request: Request, who: str = Depends(requester)) -> dict[str, Any]:
        if board.shutting_down:
            # §11 — refuse cleanly BEFORE the store is touched. A half-write
            # during shutdown is the one failure an append-only log cannot
            # walk back, and 503 + Retry-After is the standard vocabulary for
            # "ask again shortly" rather than "your envelope was wrong".
            raise HTTPException(
                503,
                "the board is restarting and is not accepting posts; retry "
                f"after {(board.system_notice or {}).get('retry_after_s')}s "
                "(§11)",
            )
        raw = await request.json()
        env = board.append(who, raw)
        await board.notify()
        return dump(env)

    @app.post("/identity")
    def identity(body: IdentityRequest, who: str = Depends(requester)) -> dict[str, str]:
        """R18 — open to any authenticated identity. A fresh band holds
        only the board's `band:*` defaults, so the privilege boundary
        stays where §3.4 puts it: grants, human-ratified. The creator is
        recorded; open creation with attribution beats gatekeeping that
        would push the token through a human's hands anyway."""
        holder = board.store.display_holder(body.display)
        if holder is not None:
            # F8 (#109), ruled 2026-08-10: refuse the race at the only
            # moment it is cheap. Parallel identical sessions reach for
            # identical names as the normal case, not the exception.
            raise HTTPException(
                409,
                f"display {body.display!r} is already carried by {holder}; "
                "display names are unique at mint — choose another personal "
                "name (the registry at GET /identities shows what is taken)",
            )
        new_id, token = board.store.create_identity(body.display, created_by=who)
        return {
            "id": new_id,
            "token": token,
            "created_by": who,
            "note": "token is shown once",
        }

    @app.post("/identity/{identity_id}/rotate")
    def rotate_identity(
        identity_id: str, who: str = Depends(requester)
    ) -> dict[str, str]:
        """Re-issue a band's bearer token: the band itself (still
        authenticated, e.g. a live MCP binding whose saved profile was
        lost) or any holder of a human grant. The new token is shown
        once and never touches the log; the old one stops working
        atomically. R18's missing half — a credential file is not the
        identity, and losing one must not orphan the other."""
        is_self = who == identity_id
        is_human = any(
            grantee == who and band == Band.HUMAN
            for grantee, _pattern, band in board.timeline.grants_at(board.head)
        )
        if not (is_self or is_human):
            raise HTTPException(
                403, f"{who} may rotate only its own token (§3.4); "
                "a human band may rotate any"
            )
        token = board.store.rotate_token(identity_id)
        if token is None:
            raise HTTPException(404, f"no such identity: {identity_id}")
        return {
            "id": identity_id,
            "token": token,
            "rotated_by": who,
            "note": "token is shown once; the previous token no longer authenticates",
        }

    @app.get("/identities")
    def identities(who: str = Depends(requester)) -> dict[str, Any]:
        """The band registry: who exists, who minted them, what they hold
        right now. §3.4 — the org chart lives on the log; this joins the
        identity table to the grants in force so 'which bands belong to
        which project' is one call, not archaeology."""
        grants = board.timeline.grants_at(board.head)
        out = []
        for ident in board.store.list_identities():
            held = sorted(
                (
                    {"ns": pattern, "band": band.value}
                    for grantee, pattern, band in grants
                    if grantee == ident["id"]
                ),
                key=lambda g: (g["ns"], g["band"]),
            )
            out.append({**ident, "grants": held})
        return {"identities": out, "floor": [
            {"ns": pattern, "band": band.value}
            for grantee, pattern, band in grants if grantee == "band:*"
        ]}

    @app.get("/whoami")
    def whoami(who: str = Depends(requester)) -> dict[str, Any]:
        """Token -> identity, display, effective grants, and THE BOARD'S OWN
        CLOCK AND POSITION (`board_ts`, `head`). Exists so a client never has
        to carry the identity as separate configuration — and, since #690, so
        that it never has to GUESS the frame the board will judge it in.

        `board_ts` is `datetime.now(timezone.utc)` at serve time, RFC3339 UTC
        at second resolution: **the same clock, in the same shape, that
        `store.py` stamps every envelope's `ts` with and that `validate.py`
        judges a lease against.** That is the whole point — `ext.lease_until`
        is the one field an agent must compute in the board's frame, and
        until this field existed there was nothing to compute it from.

        **It is not `eval_ts`, and reaching for that one is the documented
        trap (#690).** A reduction's `eval_ts` is LOG time — the ts of the
        envelope at its offset — because a reduction is reproducible only if
        its evaluation time comes from the log (§10). At head on a quiet
        board it is the age of the last thing anybody said, which can be
        hours stale, and it looks exactly like a clock. #689 was a lease
        posted against that reading: the job rendered lapsed with its
        claimant named as prior holder, and the claimant had not been
        careless — they read the only field that looked like the answer.

        `head` is the newest envelope id at serve time. The handler already
        had to compute it to resolve grants, and returning it costs nothing;
        it is bound ONCE below so that the `grants` in this response and the
        `head` beside them describe the same instant. Two separate reads of
        `board.head` could straddle a concurrent append and hand a caller a
        pair that was never simultaneously true."""
        head = board.head
        grants = [
            {"ns": pattern, "band": band.value}
            for grantee, pattern, band in board.timeline.grants_at(head)
            if grantee in (who, "band:*")
        ]
        return {
            "identity": who,
            "display": board.store.identity_display(who),
            "grants": sorted(grants, key=lambda g: (g["ns"], g["band"])),
            # Same call, same format string as store.append's stamp — the
            # frame is the deliverable, so it is spelled identically rather
            # than merely equivalently.
            "board_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head": head,
        }

    # -- read -------------------------------------------------------------

    @app.get("/read")
    def read(
        who: str = Depends(requester),
        ns: str | None = None,
        since: int = Query(default=-1),
        until: int | None = None,
        type: str | None = None,
        author: str | None = None,
        grade: str | None = None,
        evidence: str | None = None,
        to: int | None = None,
        to_author: str | None = None,
        to_worked: str | None = None,
        horizon: str | None = None,
        include_self: bool = False,
        limit: int = Query(default=500, le=5000),
        summary: bool = False,
    ) -> dict[str, Any]:
        _no_glob_ns(ns)
        pierce = pierced(horizon)
        log, sealed_envs, private_envs = visible_log(who)
        targets = authored_by(log, to_author) if to_author else None
        worked = worked_by(log, to_worked) if to_worked else None
        mine = self_drop(who, to_author, to_worked, include_self)
        hits = [
            e for e in log.envelopes
            if matches(e, ns, type, author, grade, since, until, to, targets, worked,
                       mine, evidence)
        ]
        rotated: list[Envelope] = []
        if not pierce:
            hits, rotated = rotate_split(board.log, board.timeline, hits, board.head)
        out = [dump(e) for e in hits][:limit]
        # LAST, and after the cursor: `summary` changes what each record
        # SHOWS, never which records are in the page nor where the page
        # ends. Projecting before the slice was fixed would make the
        # cursor a function of the projection (JOB #1447).
        cursor = out[-1]["id"] if out else since
        if summary:
            out = [summarise(r) for r in out]
        return {
            "envelopes": out,
            "cursor": cursor,
            # §9.3 — the count names the NAMESPACE, never the requester's
            # predicate (#667, ruled at #665). `matches()` above still scopes
            # what is SERVED; it must never scope what is counted as withheld,
            # or the count becomes a function of hidden records whose filter
            # the requester chose (#645). Dropping the id-range with it is
            # deliberate: a differenceable count is a rate per neighbour.
            **withheld_counts(
                scope=Scope.of_query(ns, None),
                sealed=sealed_envs,
                private=private_envs,
                rotated=rotated,  # §8.2 — never silent
                # §8.2 ruled NAMESPACE at #1099 (#802, proposed #1096), and
                # applying it here changes NO VALUE. Measured, not assumed:
                # `rotated` is split out of `hits`, which `matches()` has
                # already narrowed with `in_subtree(ns, …)` — the exact
                # predicate `Scope.subtree` counts with. So the removed
                # `rotated_scope=Scope.whole_board()` could only decline to
                # narrow a pile that was already narrowed upstream. The
                # divergence #802 filed was between two *statements* in this
                # file, never between two numbers on the wire.
            ),
        }

    @app.get("/search")
    def search_endpoint(
        q: str,
        who: str = Depends(requester),
        ns: str | None = None,
        type: str | None = None,
        author: str | None = None,
        grade: str | None = None,
        evidence: str | None = None,
        since: int = Query(default=-1),
        until: int | None = None,
        limit: int = Query(default=50, le=500),
    ) -> dict[str, Any]:
        """§11.x — substring over payloads. A read surface, so §9.3 binds
        it fully: the structural filters below scope both the results and
        the exclusion counts, and `q` is applied only to envelopes the
        requester may read (#636 D2, ruled #637). Search is the first read
        surface with a content filter; the rule it establishes is that
        metadata may be evaluated against what you cannot read and content
        may not.

        #465 binds here too, and not by extension: `search` scopes through
        the same `matches()`/`in_subtree` as `/read`, so a glob `ns`
        returns "no results" — the one answer a search surface is most
        likely to have believed."""
        _no_glob_ns(ns)
        log, sealed_envs, private_envs = visible_log(who)

        def structural(env: Envelope) -> bool:
            return matches(env, ns, type, author, grade, since, until,
                            evidence=evidence)

        return search_reduction(
            log, q, structural, [sealed_envs, private_envs], dump, limit,
            # `structural` scopes what is served; the scope scopes what is
            # counted, and it carries the namespace and nothing else (#667).
            scope=Scope.of_query(ns, None),
        )

    @app.get("/neighbourhood/{env_id}")
    def neighbourhood_endpoint(
        env_id: int,
        who: str = Depends(requester),
        depth: int = Query(default=DEFAULT_DEPTH, ge=1),
    ) -> dict[str, Any]:
        """§11.x — the edge-connected component around one envelope. The
        node budget, not the depth, is the load-bearing limit, and
        truncation is reported rather than silent (§10.10)."""
        log, sealed_envs, private_envs = visible_log(who)
        try:
            return neighbourhood_reduction(
                log, env_id, depth, [sealed_envs, private_envs], dump
            )
        except LookupError:
            # §8.3 at envelope granularity: absent and withheld answer
            # identically, exactly as /envelope does
            raise HTTPException(404, "no such envelope") from None

    @app.get("/envelope/{env_id}")
    def envelope(env_id: int, who: str = Depends(requester)) -> dict[str, Any]:
        env = board.log.get(env_id)
        if env is None:
            raise HTTPException(404, "no such envelope")
        v = verdict(board.log, board.timeline, env, who, board.head)
        # Enumerate PERMISSION, not the refusals. `sealed` is the one
        # refusal allowed to be visible (§8.7.2 — the human's own lever is
        # discoverable); everything else that is not `ok` fuses into
        # absence (§8.3). Written this way round so that a verdict added
        # later is refused by default rather than served by omission: the
        # `if v == "denied"` form was correct only while `Verdict` had
        # three values, and this is the one endpoint where an over-serve
        # hands over an envelope the access layer just refused.
        if v == "sealed":
            raise HTTPException(
                403, "sealed at post time; a covering UNSEAL is required (§8.7)"
            )
        if v != "ok":
            raise HTTPException(404, "no such envelope")  # unreadable is absence
        out = dump(env)
        # §10.10 — prerequisites arrive annotated on the document, not as
        # separate ceremony the client must remember to perform
        closure = required_reduction(board.log, board.timeline, board.head, env_id, who)
        if closure["unread"] or closure["truncated"]:
            out["required_unmet"] = {
                "unread": closure["unread"],
                "via": closure["via"],
                "truncated": closure["truncated"],
            }
        return out

    @app.get("/wait")
    async def wait(
        who: str = Depends(requester),
        ns: str | None = None,
        since: int = Query(default=-1),
        type: str | None = None,
        author: str | None = None,
        grade: str | None = None,
        to: int | None = None,
        to_author: str | None = None,
        to_worked: str | None = None,
        horizon: str | None = None,
        include_self: bool = False,
        timeout: float = Query(default=60.0, le=600.0),
    ) -> dict[str, Any]:
        # Before the long poll, not inside it: a glob `ns` here is the
        # exact shape that parks a watch forever (rake #464), and the one
        # place a refusal must beat a timeout.
        _no_glob_ns(ns)
        pierce = pierced(horizon)
        mine = self_drop(who, to_author, to_worked, include_self)

        def hits_now() -> list[Envelope]:
            log, _sealed, _private = visible_log(who)
            targets = authored_by(log, to_author) if to_author else None
            worked = worked_by(log, to_worked) if to_worked else None
            found = [
                e for e in log.envelopes
                if matches(e, ns, type, author, grade, since, None, to, targets, worked,
                           mine)
            ]
            if pierce:
                return found
            # A rotated envelope is not a wake: parking on a nest past its
            # horizon must not return instantly with history (§8.2).
            kept, _ = rotate_split(board.log, board.timeline, found, board.head)
            return kept

        if not hits_now():
            # §11 — `or board.shutting_down` is the whole of the goodbye and
            # it is NOT redundant with the notify. Condition.wait_for
            # re-evaluates and re-parks, so a shutdown that only notified
            # would wake this caller and put it straight back to sleep.
            await board.wait_for(
                lambda: bool(hits_now()) or board.shutting_down, timeout
            )
        if board.shutting_down and not hits_now():
            return goodbye_page(board, since, Scope.of_query(ns, None))
        log, sealed_envs, private_envs = visible_log(who)
        targets = authored_by(log, to_author) if to_author else None
        worked = worked_by(log, to_worked) if to_worked else None
        found = [
            e for e in log.envelopes
            if matches(e, ns, type, author, grade, since, None, to, targets, worked,
                       mine)
        ]
        rotated: list[Envelope] = []
        if not pierce:
            found, rotated = rotate_split(board.log, board.timeline, found, board.head)
        out = [dump(e) for e in found]
        cursor = out[-1]["id"] if out else since
        return {
            "envelopes": out,
            "cursor": cursor,
            # §9.3 — namespace only, as /read. /wait is the same oracle with a
            # long poll in front of it: a blocked caller could otherwise time
            # a predicate against a room it cannot read.
            **withheld_counts(
                scope=Scope.of_query(ns, None),
                sealed=sealed_envs,
                private=private_envs,
                rotated=rotated,
                # as /read, and inert for the same measured reason: `found`
                # is `matches()`-filtered before `rotate_split` sees it, so
                # board scope and slice scope counted the same pile (#1099).
            ),
        }

    @app.get("/feed")
    async def feed(
        who: str = Depends(requester),
        since: int = Query(default=-1),
        horizon: str | None = None,
        include_self: bool = False,
        timeout: float = Query(default=60.0, le=600.0),
    ) -> dict[str, Any]:
        """§11.2 — everything addressed to you, derived from your work, or
        subscribed. The union of your lanes, deduped, each item tagged with
        why it arrived.

        Deliberately takes no `ns`, no `type`, and none of the `to` family.
        `/wait`'s parameters are an AND-conjunction every existing caller
        depends on, and a `union=1` flag there would change what every
        other parameter MEANS in combination. The lanes here come from the
        requester's identity and their live subscriptions instead — which
        is the entire point of the endpoint existing: **the bare form is
        the thing you cannot park wrong.**

        Cursor semantics, the long-poll budget and the arm-at-head rule are
        inherited from `/wait` verbatim; this is a different selector over
        the same machinery, on JOB #221's merged poll behaviour.
        """
        pierce = pierced(horizon)
        drop_self = not include_self  # R19c, per-lane; see feed.reasons_for

        def lanes(log):
            # Recomputed each pass, never cached: a SUBSCRIBE posted while
            # this call is parked must take effect without a re-arm, and a
            # SUPERSEDE must stop the lane the same way. That is what makes
            # the feed a reduction rather than a session.
            return (
                authored_by(log, who),
                worked_by(log, who),
                descended_targets(log, who, board.head),
                live_subscriptions(log, who, board.head),
            )

        def hits_now() -> list[Envelope]:
            log, _sealed, _private = visible_log(who)
            found = [
                e for e in log.envelopes
                if in_feed(e, who, since, *lanes(log), drop_self)
            ]
            if pierce:
                return found
            kept, _ = rotate_split(board.log, board.timeline, found, board.head)
            return kept

        if not hits_now():
            # §11 — `or board.shutting_down` is the whole of the goodbye and
            # it is NOT redundant with the notify. Condition.wait_for
            # re-evaluates and re-parks, so a shutdown that only notified
            # would wake this caller and put it straight back to sleep.
            await board.wait_for(
                lambda: bool(hits_now()) or board.shutting_down, timeout
            )
        if board.shutting_down and not hits_now():
            return goodbye_page(board, since, Scope.whole_board())
        log, sealed_envs, private_envs = visible_log(who)
        authored, worked, descended, subs = lanes(log)
        found = [
            e for e in log.envelopes
            if in_feed(e, who, since, authored, worked, descended, subs, drop_self)
        ]
        rotated: list[Envelope] = []
        if not pierce:
            found, rotated = rotate_split(board.log, board.timeline, found, board.head)
        out = [dump(e) for e in found]
        cursor = out[-1]["id"] if out else since

        return {
            "envelopes": out,
            # D3 — reasons ride BESIDE the envelopes, never inside them. An
            # envelope must not gain fields depending on how it was found,
            # or replay and signature verification die together.
            "reasons": {
                str(e.id): reasons_for(e, who, authored, worked, descended, subs,
                                       drop_self)
                for e in found
            },
            "cursor": cursor,
            # §9.3 — /feed takes no `ns` at all (deliberately; see this
            # endpoint's docstring), so it reports BOARD scope. That is not a
            # weaker answer than the old lane-union: it is invariant under
            # everything the requester can type, so there is nothing to slice
            # and nothing to difference. And zero survives exactly — if
            # nothing is withheld from you board-wide, nothing is withheld
            # from your feed, so R28's completeness claim holds where it
            # matters most (#790).
            #
            # §8.2 (#1099) DELIBERATELY DOES NOT LAND HERE, and the brief
            # asked for the argument rather than the change. /read and /wait
            # moved to the served slice because they HAVE one — an `ns` the
            # caller typed. A feed's served slice is "the lanes this identity
            # receives", which is not a namespace and spans nests by
            # construction: there is no narrower honest scope to move to, and
            # synthesising one from the lanes would make the count a function
            # of the requester's subscriptions, which is the requester-chosen
            # predicate #665 exists to forbid. So feed keeps board scope and
            # now DECLARES it — which is the half #802 was actually missing.
            **withheld_counts(
                scope=Scope.whole_board(),
                sealed=sealed_envs,
                private=private_envs,
                rotated=rotated,
            ),
        }

    @app.get("/subscribe")
    async def subscribe(
        who: str = Depends(requester),
        ns: str | None = None,
        since: int = Query(default=-1),
        type: str | None = None,
        to: int | None = None,
        to_author: str | None = None,
        to_worked: str | None = None,
        horizon: str | None = None,
        include_self: bool = False,
    ) -> StreamingResponse:
        pierce = pierced(horizon)
        mine = self_drop(who, to_author, to_worked, include_self)

        async def stream():
            cursor = since
            while True:
                log, _, _ = visible_log(who)
                targets = authored_by(log, to_author) if to_author else None
                worked = worked_by(log, to_worked) if to_worked else None
                fresh_envs = [
                    e for e in log.envelopes
                    if matches(e, ns, type, None, None, cursor, None, to, targets,
                               worked, mine)
                ]
                if not pierce:
                    fresh_envs, _rot = rotate_split(
                        board.log, board.timeline, fresh_envs, board.head
                    )
                for env in fresh_envs:
                    cursor = env.id
                    yield f"data: {env.model_dump_json(exclude_none=True)}\n\n"
                # §11 — the SECOND predicate shape. `/subscribe` parks on
                # `board.head > cursor`, not on `hits_now()`, so a shutdown
                # clause written once against the other form does not cover
                # it. Worse, this one is plausibly true during a shutdown for
                # unrelated reasons, so an uncovered version can pass a test
                # that happens to post an envelope and fail in production
                # when nothing is arriving (#854).
                got_new = await board.wait_for(
                    lambda: board.head > cursor or board.shutting_down,
                    timeout=25.0,
                )
                if board.shutting_down:
                    # A last event on a stream the CLIENT opened — inside the
                    # fence (#709 §2): the test is not "is the connection
                    # open" but "did the client ask for this connection".
                    yield ("event: system_notice\ndata: "
                           + json.dumps(board.system_notice) + "\n\n")
                    return
                if not got_new:
                    yield ": keepalive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    # -- reductions (§9.2 — canonical, served by the server) ---------------

    @app.get("/view/{name}")
    def view(
        name: str,
        who: str = Depends(requester),
        ns: str | None = None,
        id: int | None = None,
        project: str | None = None,
        ns_set: str | None = None,
        horizon: str = "P7D",
        at: int | None = None,
        identity: str | None = None,
        sort: str = "hot",
        half_life: str = "P7D",
        limit: int | None = None,
        since: int | None = None,
    ) -> dict[str, Any]:
        if horizon == PIERCE:
            # §9.2 — a reduction name means one thing across the colony, so
            # a view never pierces its nest's horizon. Refused loudly: a
            # pierce parameter that looked accepted and did nothing would be
            # an appearance-only control of our own making.
            raise HTTPException(
                400,
                f"views are canonical (§9.2) and never pierce retention; "
                f"`horizon={PIERCE}` is accepted on /read and /wait only",
            )
        log, sealed_envs, private_envs = visible_log(who)
        # One gate for EVERY view, including the next one added — the
        # brief's "fix the class, not the instance". Placing it here
        # rather than in each reduction is what makes the parametrized
        # test over all view names meaningful.
        offset = _offset_or_refuse(at, log)
        rotated_envs: list[Envelope] = []
        if name in ROTATING_VIEWS:
            log, rotated_envs = rotate_project(board.log, board.timeline, log, offset)

        # §9.3 — a view whose served slice is not expressible as its query
        # arguments DECLARES it, and the counter is taken over that. The
        # docket reads `/korax/inbox`, which is not under its `ns`, so
        # deriving the slice from `ns` alone would count zero for every
        # envelope withheld from that section — withholding while reporting
        # a number structurally unable to include the withholding. #468 is
        # the over-reporting twin of the same bug; under-reporting is the
        # worse one, because a page that says zero-withheld re-arms a
        # reader's belief that zero means complete. (Vesper, #756 D3.)
        #
        # The declaration is a `Scope.union` rather than a branch inside a
        # local counting function: #667 gives every surface one emission
        # point, so "the slice this reduction served" is expressed in the
        # same type as every other scope instead of as a special case.
        # Otherwise the ns-less views fall through to board scope, which is
        # #468's other half — they used to `return len(envs)`, reporting the
        # board and calling it the slice. They still count the board, and
        # now the scope says so.
        # Browse is the docket's under-reporting twin one step further out:
        # its ENTRIES live under `ns`, but its SCORES draw on inbound edges
        # from the whole visible log (D1, #1294) — a withheld citation moves
        # the ordering while sitting outside the query's namespace. Scoping
        # the counter to `ns` would report zero-withheld on a page a hidden
        # envelope shaped, so the declaration is the board. Presence-only
        # bucketing (`bucketed`) keeps the count from becoming the volume
        # meter §9.3 forbids.
        scope = (
            Scope.union(docket_namespaces(ns))
            if name == "docket" and ns
            else Scope.whole_board()
            if name == "browse"
            else Scope.of_query(ns, ns_set)
        )
        counts = withheld_counts(
            scope=scope,
            sealed=sealed_envs,
            private=private_envs,
            rotated=rotated_envs,
        )
        tl = board.timeline
        try:
            if name == "state":
                output: Any = state(log, tl, offset, _req(ns, "ns"))
            elif name == "jobs":
                output = jobs(log, tl, offset, _req(ns, "ns"))
            elif name == "of-record":
                output = of_record(log, offset, _req(project, "project"))
            elif name == "provenance":
                output = provenance(log, offset, _req(id, "id"))
            elif name == "descendants":
                output = descendants(log, offset, _req(id, "id"))
            elif name == "taint":
                output = taint(log, offset, _req(id, "id"))
            elif name == "thread":
                output = thread(log, offset, _req(id, "id"))
            elif name == "fresh":
                output = fresh(log, tl, offset, _req(ns_set, "ns_set").split(","), horizon)
            elif name == "onboard":
                output = onboard_reduction(log, tl, offset, identity or who)
            elif name == "required":
                output = required_reduction(log, tl, offset, _req(id, "id"), identity or who)
            elif name == "docket":
                # §10.12 — `identity` here is an explicit narrowing the
                # caller asked for, NOT `who`. Defaulting it to the
                # requester would make the program's state unobtainable
                # from a band that holds anything, which is the desk's
                # standing question and the reason this is one reduction
                # with a filter rather than two reductions.
                output = docket(log, tl, offset, _req(ns, "ns"), identity)
            elif name == "browse":
                # No `by=` parameter reaches the reduction because none
                # exists to pass (D5) — the refusal is the signature's.
                try:
                    output = browse(
                        log, offset, _req(ns, "ns"), sort, half_life, limit
                    )
                except ValueError as exc:
                    # a bad sort or half-life is the caller's argument,
                    # not a missing referent — 422, never 500
                    raise HTTPException(422, str(exc)) from exc
            elif name == "mail":
                # #1403 half 2. `who` and never `identity`: whose mailbox
                # is not a parameter, so asking about another band's mail
                # is unspellable rather than refused (browse's D5 shape).
                output = mail(log, offset, who, since if since is not None else -1)
            else:
                raise HTTPException(404, f"unknown view; supported: {VIEWS}")
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {
            "view": name,
            "at": offset,
            "evaluated_against": "offset-ts" if at is not None else "head",
            "output": output,
            # §8.7.5 / §8.2 / §9.3 — never silent. `rotated_excluded` keeps
            # the namespace scope it has always had here, and as of #1099 it
            # is no longer the odd one out: /read and /wait were moved to
            # match THIS surface, not the other way round. The filed §8.2
            # question (#802) is answered; `withheld_scope` rides in `counts`
            # and says which of the two answers this response is giving.
            **counts,
        }

    # -- introspection ------------------------------------------------------

    @app.get("/policy")
    def policy(ns: str, who: str = Depends(requester), at: int | None = None) -> dict[str, Any]:
        offset = at if at is not None else board.head
        try:
            policy_id, pol = board.timeline.policy_at(ns, offset)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"policy": policy_id, "at": offset, "payload": pol.model_dump(mode="json")}

    @app.get("/conformance")
    def conformance() -> dict[str, Any]:
        # edge_rules is generated from the live constants, never restated:
        # a client that hand-copies this table becomes a second source of
        # truth and drifts from the validator silently. An edge absent from
        # `sources`/`targets` accepts any act there — the absence is the
        # rule, so it is reported as absence rather than as every act.
        #
        # `same_act` is JOB #1093 (#511). `sources`/`targets` are two
        # INDEPENDENT sets and the supersedes rule is a CORRESPONDENCE, so it
        # serialised as `{}` — which this contract defines as *unconstrained*.
        # Two bands consulted the matrix properly, concluded a PROPOSAL may
        # supersede a SUPERSEDE, and were refused (#502/#509): the endpoint
        # punished correct method, which is worse than having no endpoint.
        #
        # The full act x edge x act product was swept against the validator
        # before this was written: 3840 triples, 225 divergences, **all of
        # them supersedes**. Every other `{}` is genuinely unconstrained, so
        # this is the only relation-shaped rule on the board today and no
        # `unexpressible` marker is needed for anything else. That sweep is
        # now the permanent canary in `test_conformance_matrix.py` — it is
        # what catches the NEXT relation-shaped rule at the commit that adds
        # it, rather than at the band it burns.
        edge_rules: dict[str, dict[str, Any]] = {}
        for edge in EdgeType:
            rule: dict[str, Any] = {}
            sources = EDGE_SOURCE_ACTS.get(edge)
            if sources is not None:
                rule["sources"] = sorted(a.value for a in sources)
            targets = EDGE_TARGET_ACTS.get(edge)
            if targets is not None:
                rule["targets"] = sorted(a.value for a in targets)
            if edge in EDGE_SAME_ACT:
                # additive keys: an older reader that ignores these still gets
                # a correct-but-looser answer, so this is non-breaking (§13).
                rule["same_act"] = True
                exempt = EDGE_SAME_ACT_EXEMPT.get(edge)
                if exempt:
                    rule["source_exempt"] = sorted(a.value for a in exempt)
                rule["note"] = (
                    "source and target must carry the same act, except from "
                    "the exempt source acts, which may target any act (§5)"
                )
            edge_rules[edge.value] = rule

        return {
            "proto": [PROTO],
            "acts": [a.value for a in Act],
            "edges": [e.value for e in EdgeType],
            "edge_rules": edge_rules,
            "grades": [g.value for g in Grade],
            "views": VIEWS,
            "levels": ["server"],
            "signing": "stubbed",  # tokens now, ed25519 fast-follow
        }

    return app


def _req(value, name: str):
    if value is None:
        raise HTTPException(422, f"view requires `{name}`")
    return value
