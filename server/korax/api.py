"""The wire API — korax-protocol.md §9.

Thin by design: auth resolves a token to an identity, every rule lives
in the engine, and reductions are served canonically so `view=state`
means one thing across the colony (§9.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import PROTO
from .access import filter_log, verdict
from .board import Board
from .civic import onboard as onboard_reduction, required as required_reduction
from .models import Act, Band, EdgeType, Envelope, Grade
from .nsglob import in_subtree, ns_matches
from .reductions import (
    descendants,
    fresh,
    jobs,
    of_record,
    provenance,
    state,
    taint,
    thread,
)
from .validate import PostError

VIEWS = [
    "state", "thread", "provenance", "descendants", "taint", "fresh",
    "jobs", "of-record", "onboard", "required",
]


class IdentityRequest(BaseModel):
    display: str


def create_app(board: Board) -> FastAPI:
    app = FastAPI(title="korax", version=PROTO)

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

    def visible_log(who: str):
        return filter_log(board.log, board.timeline, who, board.head)

    def matches(env: Envelope, ns: str | None, type_: str | None, author: str | None,
                grade: str | None, since: int, until: int | None,
                to_env: int | None = None, to_targets: set[int] | None = None,
                worked_targets: set[int] | None = None) -> bool:
        if env.id <= since or (until is not None and env.id > until):
            return False
        if ns and not in_subtree(ns, env.ns):
            return False
        if type_ and env.type.value != type_:
            return False
        if author and env.author != author:
            return False
        if grade and env.grade.value != grade:
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

    @app.get("/", include_in_schema=False)
    def perch() -> HTMLResponse:
        """One self-contained page, no build step, no external assets.
        The page itself is public shell; every data call it makes rides
        the same bearer token as any client (§9)."""
        return HTMLResponse(
            (Path(__file__).with_name("perch.html")).read_text(encoding="utf-8")
        )

    # -- write ------------------------------------------------------------

    @app.post("/post")
    async def post(request: Request, who: str = Depends(requester)) -> dict[str, Any]:
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
        """Token -> identity, display, and effective grants. Exists so a
        client never has to carry the identity as separate configuration."""
        grants = [
            {"ns": pattern, "band": band.value}
            for grantee, pattern, band in board.timeline.grants_at(board.head)
            if grantee in (who, "band:*")
        ]
        return {
            "identity": who,
            "display": board.store.identity_display(who),
            "grants": sorted(grants, key=lambda g: (g["ns"], g["band"])),
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
        to: int | None = None,
        to_author: str | None = None,
        to_worked: str | None = None,
        limit: int = Query(default=500, le=5000),
    ) -> dict[str, Any]:
        log, sealed_envs = visible_log(who)
        targets = authored_by(log, to_author) if to_author else None
        worked = worked_by(log, to_worked) if to_worked else None
        out = [
            dump(e) for e in log.envelopes
            if matches(e, ns, type, author, grade, since, until, to, targets, worked)
        ][:limit]
        cursor = out[-1]["id"] if out else since
        sealed = sum(
            1 for e in sealed_envs
            if matches(e, ns, type, author, grade, since, until, to, targets, worked)
        )
        return {"envelopes": out, "cursor": cursor, "sealed_excluded": sealed}

    @app.get("/envelope/{env_id}")
    def envelope(env_id: int, who: str = Depends(requester)) -> dict[str, Any]:
        env = board.log.get(env_id)
        if env is None:
            raise HTTPException(404, "no such envelope")
        v = verdict(board.log, board.timeline, env, who, board.head)
        if v == "denied":
            raise HTTPException(404, "no such envelope")  # unreadable is absence
        if v == "sealed":
            raise HTTPException(
                403, "sealed at post time; a covering UNSEAL is required (§8.7)"
            )
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
        timeout: float = Query(default=60.0, le=600.0),
    ) -> dict[str, Any]:
        def pending() -> bool:
            log, _sealed = visible_log(who)
            targets = authored_by(log, to_author) if to_author else None
            worked = worked_by(log, to_worked) if to_worked else None
            return any(
                matches(e, ns, type, author, grade, since, None, to, targets, worked)
                for e in log.envelopes
            )

        if not pending():
            await board.wait_for(pending, timeout)
        log, sealed_envs = visible_log(who)
        targets = authored_by(log, to_author) if to_author else None
        worked = worked_by(log, to_worked) if to_worked else None
        out = [
            dump(e) for e in log.envelopes
            if matches(e, ns, type, author, grade, since, None, to, targets, worked)
        ]
        cursor = out[-1]["id"] if out else since
        sealed = sum(
            1 for e in sealed_envs
            if matches(e, ns, type, author, grade, since, None, to, targets, worked)
        )
        return {"envelopes": out, "cursor": cursor, "sealed_excluded": sealed}

    @app.get("/subscribe")
    async def subscribe(
        who: str = Depends(requester),
        ns: str | None = None,
        since: int = Query(default=-1),
        type: str | None = None,
        to: int | None = None,
        to_author: str | None = None,
        to_worked: str | None = None,
    ) -> StreamingResponse:
        async def stream():
            cursor = since
            while True:
                log, _ = visible_log(who)
                targets = authored_by(log, to_author) if to_author else None
                worked = worked_by(log, to_worked) if to_worked else None
                fresh_envs = [
                    e for e in log.envelopes
                    if matches(e, ns, type, None, None, cursor, None, to, targets, worked)
                ]
                for env in fresh_envs:
                    cursor = env.id
                    yield f"data: {env.model_dump_json(exclude_none=True)}\n\n"
                got_new = await board.wait_for(
                    lambda: board.head > cursor, timeout=25.0
                )
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
    ) -> dict[str, Any]:
        log, sealed_envs = visible_log(who)
        offset = at if at is not None else (log.envelopes[-1].id if len(log) else 0)
        if ns is not None:
            sealed = sum(1 for e in sealed_envs if in_subtree(ns, e.ns))
        elif ns_set is not None:
            globs = ns_set.split(",")
            sealed = sum(1 for e in sealed_envs if any(ns_matches(g, e.ns) for g in globs))
        else:
            sealed = len(sealed_envs)
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
            else:
                raise HTTPException(404, f"unknown view; supported: {VIEWS}")
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {
            "view": name,
            "at": offset,
            "evaluated_against": "offset-ts" if at is not None else "head",
            "output": output,
            "sealed_excluded": sealed,  # §8.7.5 — never silent
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
        return {
            "proto": [PROTO],
            "acts": [a.value for a in Act],
            "edges": [e.value for e in EdgeType],
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
