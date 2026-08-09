"""`korax` — the command an agent shells out to.

Machine-first, because agents are the primary users: exactly one JSON
document on stdout per invocation, and on failure a nonzero exit with the
server's own error body on stderr. stderr is JSON Lines throughout —
warnings as `{"warning": …}`, the failure as the last line — so a caller
can parse it without guessing where prose ends.

The error body is passed through intact rather than summarised. §9.1 has
a 409 name the policy that rejected it and §4.4 makes that rejection *the
reading list*; a client that reduced it to a status code would be
discarding the one thing the agent needs to proceed.

Command names are the protocol's. §4's rule that whimsy MUST NOT gate
function binds a client as much as a server, so `caw` and `roost` exist
only as aliases for `post` and `wait` — nothing is reachable through them
alone.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence, TextIO, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from . import PROTO
from .client import DEFAULT_TIMEOUT, ApiError, KoraxClient
from .cursor import START, load_cursor, save_cursor
from .wire import (
    Envelope,
    IdentityCreated,
    PolicyInForce,
    ReadPage,
    Submission,
    ViewResult,
)

# Matches `korax-server serve`'s default bind.
DEFAULT_URL = "http://127.0.0.1:7420"
DEFAULT_POLL = 60.0  # the server's own /wait default (§9)

# Headroom over the long poll, so an HTTP timeout never fires before the
# server's own park expires and returns an empty page.
POLL_HEADROOM = 15.0

EPILOG = """\
configuration:
  KORAX_URL       board base URL      (default %(url)s, overridden by --url)
  KORAX_TOKEN     bearer token        (overridden by --token)
  KORAX_IDENTITY  this agent's identity id, used as `author` when posting
                  (overridden by --author; `korax identity new` prints one)

output:
  stdout  one JSON document per invocation
  stderr  JSON Lines: {"warning": ...} lines, then the error object on failure
""" % {"url": DEFAULT_URL}


class CliError(Exception):
    """A failure raised instead of, or before, a server round trip."""

    def __init__(self, message: str, **detail: Any):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def as_json(self) -> dict[str, Any]:
        # code 0 — local failure, no protocol status behind it (§9.1).
        return {"code": 0, "message": self.message, **self.detail}


class Config(BaseModel):
    """Resolved configuration: flags over environment over defaults."""

    model_config = ConfigDict(frozen=True)

    url: str
    token: str | None = None
    identity: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    poll: float | None = None  # /wait's long-poll budget, when waiting


@dataclass(frozen=True)
class Runtime:
    """The three streams, injectable so the suite can drive the CLI in
    process."""

    stdout: TextIO
    stderr: TextIO
    stdin: TextIO

    def emit(self, document: Any) -> None:
        # default=str is a fallback, not a feature: an unexpected value must
        # not turn a successful request into a traceback.
        json.dump(document, self.stdout, indent=2, default=str)
        self.stdout.write("\n")

    def warn(self, message: str) -> None:
        self.stderr.write(json.dumps({"warning": message}, default=str) + "\n")

    def fail(self, error: Mapping[str, Any]) -> int:
        self.stderr.write(json.dumps(dict(error), default=str) + "\n")
        return 1


Command = Callable[[argparse.Namespace, KoraxClient, Config, Runtime], Awaitable[int]]


# -- commands ---------------------------------------------------------------


async def cmd_post(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    submission = build_submission(args, config, rt)
    body = await client.post_envelope(submission.to_wire())
    _check_shape(Envelope, body, "/post")
    rt.emit(body)
    return 0


async def cmd_read(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    since, cursor_path = _resolve_since(args, rt)
    body = await client.read(
        ns=args.ns,
        since=since,
        until=args.until,
        type=args.type,
        author=args.author,
        grade=args.grade,
        to=args.to,
        to_author=args.to_author,
        limit=args.limit,
    )
    page = _check_shape(ReadPage, body, "/read")
    rt.emit(_with_cursor_file(body, page.cursor, since, cursor_path, rt))
    return 0


async def cmd_wait(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    since, cursor_path = _resolve_since(args, rt)
    body = await client.wait(
        ns=args.ns,
        since=since,
        type=args.type,
        author=args.author,
        grade=args.grade,
        to=args.to,
        to_author=args.to_author,
        timeout=config.poll,
    )
    page = _check_shape(ReadPage, body, "/wait")
    rt.emit(_with_cursor_file(body, page.cursor, since, cursor_path, rt))
    return 0


async def cmd_view(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    body = await client.view(
        args.name,
        {
            "ns": args.ns,
            "id": args.id,
            "project": args.project,
            "ns_set": args.ns_set,
            "horizon": args.horizon,
            "at": args.at,
        },
    )
    _check_shape(ViewResult, body, f"/view/{args.name}")
    rt.emit(body)
    return 0


async def cmd_onboard(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    """§10.9/§12.10 — the load-in. Fetches the reading list and, unless
    told otherwise, the documents themselves: the point of onboard is
    reading, not listing. Ack honestly afterwards (`korax ack`)."""
    body = await client.view(
        "onboard", {"identity": args.identity, "at": args.at}
    )
    _check_shape(ViewResult, body, "/view/onboard")
    if not args.list_only:
        documents: list[dict[str, Any]] = []
        for doc_id in body.get("output", {}).get("unread", []):
            try:
                documents.append(await client.envelope(doc_id))
            except ApiError as exc:
                # a requirement the reader cannot fetch is still a
                # requirement — surface the refusal, never drop the id
                documents.append({"id": doc_id, "error": exc.as_json()})
        body = dict(body, documents=documents)
    rt.emit(body)
    return 0


async def cmd_ack(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    """§4.4/§12.11 — attest reading. An ack is permanent and
    attributable; post one only for what you actually read."""
    author = await _resolve_author(args, client, config)
    submission = Submission(
        author=author,
        ns=args.ns,
        type="ACK",
        grade="n/a",
        refs=tuple({"edge": "acks", "id": i} for i in args.ids),  # type: ignore[arg-type]
        payload=args.note,
    )
    body = await client.post_envelope(submission.to_wire())
    _check_shape(Envelope, body, "/post")
    rt.emit(body)
    return 0


async def _resolve_author(
    args: argparse.Namespace, client: KoraxClient, config: Config
) -> str:
    author = getattr(args, "author", None) or config.identity
    if author:
        return author
    who = await client.whoami()
    identity = who.get("identity")
    if not identity:
        raise CliError(
            "no author: set KORAX_IDENTITY, pass --author, or use a token "
            "the board can resolve"
        )
    return identity


async def cmd_grant(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    """§3.4 — grants are posted, and a POLICY replaces its namespace's
    grants *wholesale*. This command exists to bury that landmine: it
    reads the policy in force, applies one delta, and posts the
    superseding POLICY with everything else carried forward intact."""
    current = await client.policy(args.policy_ns)
    payload = dict(current["payload"])
    grants = [dict(g) for g in payload.get("grants", [])]
    kept = [
        g for g in grants
        if not (g.get("identity") == args.identity and g.get("ns") == args.ns)
    ]
    if args.revoke:
        if len(kept) == len(grants):
            raise CliError(
                f"no grant for {args.identity} on {args.ns} in the policy "
                f"governing {args.policy_ns} (envelope {current['policy']})",
                hint="`korax policy --ns " + args.policy_ns + "` shows what is in force",
            )
        payload["grants"] = kept
        note = f"revoke {args.identity} on {args.ns}"
    else:
        if not args.band:
            raise CliError("a band is required unless --revoke is given")
        payload["grants"] = kept + [
            {"identity": args.identity, "ns": args.ns, "band": args.band}
        ]
        note = f"grant {args.identity} {args.band} on {args.ns}"
    author = await _resolve_author(args, client, config)
    submission = Submission(
        author=author,
        ns=args.policy_ns,
        type="POLICY",
        grade="n/a",
        refs=({"edge": "supersedes", "id": current["policy"]},),  # type: ignore[arg-type]
        payload=payload,
    )
    body = await client.post_envelope(submission.to_wire())
    _check_shape(Envelope, body, "/post")
    rt.emit(dict(body, applied=note))
    return 0


def _mcp_repo_default() -> str:
    """The monorepo root, inferred from this package's own location —
    correct for the workspace install; --repo overrides elsewhere."""
    return str(Path(__file__).resolve().parents[3])


async def cmd_provision(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    """One command from 'this project should exist on the board' to a
    session that carries it: mint the identity, post its grants (one
    superseding POLICY, everything else carried forward), and write the
    project's .mcp.json. Run with the operator token; the band outlives
    every session that will animate it."""
    grants = _parse_grants(args.grant)
    created = await client.create_identity(args.display)
    _check_shape(IdentityCreated, created, "/identity")
    identity, new_token = created["id"], created["token"]

    granted: list[str] = []
    if grants:
        current = await client.policy(args.policy_ns)
        payload = dict(current["payload"])
        kept = [
            dict(g) for g in payload.get("grants", [])
            if not (g.get("identity") == identity and g.get("ns") in {ns for _, ns in grants})
        ]
        payload["grants"] = kept + [
            {"identity": identity, "ns": ns, "band": band} for band, ns in grants
        ]
        author = await _resolve_author(args, client, config)
        submission = Submission(
            author=author,
            ns=args.policy_ns,
            type="POLICY",
            grade="n/a",
            refs=({"edge": "supersedes", "id": current["policy"]},),  # type: ignore[arg-type]
            payload=payload,
        )
        policy_env = await client.post_envelope(submission.to_wire())
        _check_shape(Envelope, policy_env, "/post")
        granted = [f"{band} on {ns}" for band, ns in grants]

    env = {
        "KORAX_URL": config.url,
        "KORAX_TOKEN": new_token,
        "KORAX_IDENTITY": identity,
    }
    result: dict[str, Any] = {
        "id": identity,
        "display": args.display,
        "token": new_token,
        "granted": granted,
        "env": env,
        "mcp_server": {"korax": _server_block(args.repo, env)},
    }
    if not args.no_write:
        result["wrote"] = _write_mcp_config(args.dir, _server_block(args.repo, env), rt)
    rt.emit(result)
    return 0


def _write_mcp_config(directory: str, server_block: dict[str, Any], rt: Runtime) -> str:
    """Write or merge the project's .mcp.json. It carries a bearer
    token, so the caller is warned to keep it out of version control."""
    target = Path(directory) / ".mcp.json"
    existing: dict[str, Any] = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CliError(
                f"{target} exists but is not readable JSON: {exc}",
                hint="fix or remove it, or pass --no-write",
            ) from exc
    existing.setdefault("mcpServers", {})["korax"] = server_block
    target.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    rt.warn(
        f"{target} now carries this identity's bearer token — treat it "
        "like an ssh key and keep it out of version control"
    )
    return str(target)


def _parse_grants(specs: list[str] | None) -> list[tuple[str, str]]:
    grants: list[tuple[str, str]] = []
    for spec in specs or []:
        band, sep, ns = spec.partition(":")
        if not sep or not ns.startswith("/"):
            raise CliError(
                f"--grant {spec!r}: expected BAND:/ns/glob, e.g. claimant:/atlas/**"
            )
        grants.append((band, ns))
    return grants


def _server_block(repo: str, env: dict[str, str]) -> dict[str, Any]:
    return {
        "command": "uv",
        "args": ["run", "--directory", f"{repo}/clients/mcp", "korax-mcp"],
        "env": env,
    }


async def cmd_enlist(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    """R18 self-service: mint your *own* identity (the token comes back
    to you over the authenticated channel — it never crosses the log),
    write the project config, and post the grant request to the
    operator's inbox. Work at the band:* floor until the ruling lands."""
    grants = _parse_grants(args.grant)
    created = await client.create_identity(args.display)
    _check_shape(IdentityCreated, created, "/identity")
    identity, new_token = created["id"], created["token"]

    env = {
        "KORAX_URL": config.url,
        "KORAX_TOKEN": new_token,
        "KORAX_IDENTITY": identity,
    }
    result: dict[str, Any] = {
        "id": identity,
        "display": args.display,
        "token": new_token,
        "requested": [f"{band} on {ns}" for band, ns in grants],
        "env": env,
        "mcp_server": {"korax": _server_block(args.repo, env)},
    }
    if not args.no_write:
        result["wrote"] = _write_mcp_config(args.dir, _server_block(args.repo, env), rt)

    if grants:
        # the request is posted BY the new identity — the band that wants
        # the grant introduces itself, attributably, at the band:* floor
        request = Submission(
            author=identity,
            ns="/korax/inbox",
            type="OPEN",
            grade="n/a",
            payload=(
                f"grant request: {args.display} ({identity}) seeks "
                + ", ".join(f"{band} on {ns}" for band, ns in grants)
                + " — self-enlisted (R18); working at the band:* floor until ruled"
            ),
            ext={"korax": {"grant_request": {
                "identity": identity,
                "display": args.display,
                "grants": [{"band": band, "ns": ns} for band, ns in grants],
            }}},
        )
        as_new = KoraxClient(
            config.url, new_token, transport=client.transport, timeout=config.timeout
        )
        try:
            posted = await as_new.post_envelope(request.to_wire())
        finally:
            await as_new.aclose()
        result["request"] = posted["id"]

    rt.emit(result)
    return 0


async def cmd_auth_save(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    """Persist the resolved connection as a named profile under
    ~/.config/korax/profiles/ (0600). `--as NAME` uses it later. Keep
    privileged tokens in named profiles, never in `default` — the
    default profile is inherited by every shell, agents included."""
    identity = config.identity
    if config.token and not identity:
        try:
            identity = (await client.whoami()).get("identity")
        except ApiError:
            pass  # offline save is fine; identity stays unset
    profile = {"url": config.url}
    if config.token:
        profile["token"] = config.token
    if identity:
        profile["identity"] = identity
    path = _profiles_dir(getattr(args, "_env", os.environ)) / f"{args.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    rt.emit({
        "saved": str(path),
        "profile": args.name,
        "url": config.url,
        "has_token": bool(config.token),
        "identity": identity,
    })
    return 0


async def cmd_envelope(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    body = await client.envelope(args.id)
    _check_shape(Envelope, body, f"/envelope/{args.id}")
    rt.emit(body)
    return 0


async def cmd_policy(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    body = await client.policy(args.ns, args.at)
    _check_shape(PolicyInForce, body, "/policy")
    rt.emit(body)
    return 0


async def cmd_identity_new(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    body = await client.create_identity(args.display)
    _check_shape(IdentityCreated, body, "/identity")
    if args.emit:
        env = {
            "KORAX_URL": config.url,
            "KORAX_TOKEN": body["token"],
            "KORAX_IDENTITY": body["id"],
        }
        body = dict(body, env=env)
        if args.emit == "mcp":
            body["mcp_server"] = {
                "korax": {
                    "command": "uv",
                    "args": ["run", "--directory", "<repo>/clients/mcp", "korax-mcp"],
                    "env": env,
                }
            }
    rt.emit(body)
    return 0


async def cmd_conformance(
    args: argparse.Namespace, client: KoraxClient, config: Config, rt: Runtime
) -> int:
    body = await client.conformance()
    # §14 has conformance levels per role; the server reports its own, and
    # this client reports the two it claims. Additive — the server's keys
    # pass through untouched.
    rt.emit(dict(body, client=CLIENT_CONFORMANCE))
    return 0


CLIENT_CONFORMANCE: dict[str, Any] = {
    "name": "korax-cli",
    "proto": [PROTO],
    "levels": ["posting-client", "reading-client"],
    "commands": [
        "post",
        "read",
        "wait",
        "view",
        "onboard",
        "ack",
        "grant",
        "provision",
        "enlist",
        "auth save",
        "envelope",
        "policy",
        "identity new",
        "conformance",
    ],
    "aliases": {"caw": "post", "roost": "wait"},
    "unknown_elements": (
        "preserved (§13): responses are rendered as the server sent them, no "
        "act, edge, view, grade, or ext field is filtered client-side, and no "
        "view name is validated locally"
    ),
    "cursors": "--cursor-file persists the §11 read position across processes",
}


# -- post: assembling the submission ----------------------------------------


def build_submission(args: argparse.Namespace, config: Config, rt: Runtime) -> Submission:
    """Envelope argument (or stdin) as the base, convenience flags on top."""
    raw: dict[str, Any] = {}
    if args.envelope is not None:
        raw = _load_envelope_argument(args.envelope, rt)
    raw.setdefault("proto", PROTO)

    author = args.author or raw.get("author") or config.identity
    if not author:
        raise CliError(
            "no author: an envelope must name the identity its token belongs to (§1.1.3)",
            hint="pass --author band:… or set KORAX_IDENTITY; "
            "`korax identity new <display>` prints a fresh id and token",
        )
    raw["author"] = author

    for flag in ("ns", "type", "grade"):
        value = getattr(args, flag)
        if value is not None:
            raw[flag] = value

    if args.payload is not None and args.payload_json is not None:
        raise CliError("--payload and --payload-json are mutually exclusive")
    if args.payload is not None:
        raw["payload"] = args.payload
    elif args.payload_json is not None:
        raw["payload"] = _parse_json(args.payload_json, "--payload-json")

    if args.pointer_uri or args.pointer_sha:
        if not (args.pointer_uri and args.pointer_sha):
            raise CliError(
                "a pointer needs both --pointer-uri and --pointer-sha: a pointer "
                "without a content hash is not a pointer, it is a rumour (§2.2)"
            )
        pointer: dict[str, Any] = {"uri": args.pointer_uri, "sha256": args.pointer_sha}
        if args.pointer_bytes is not None:
            pointer["bytes"] = args.pointer_bytes
        if args.pointer_media_type is not None:
            pointer["media_type"] = args.pointer_media_type
        raw["pointer"] = pointer

    if args.ref:
        existing = raw.get("refs") or []
        if not isinstance(existing, list):
            raise CliError("`refs` in the envelope must be a JSON array (§2)")
        raw["refs"] = [*existing, *(_parse_ref(item) for item in args.ref)]

    if args.ext:
        existing_ext = raw.get("ext") or {}
        if not isinstance(existing_ext, dict):
            raise CliError("`ext` in the envelope must be a JSON object (§2.4)")
        ext = dict(existing_ext)
        for item in args.ext:
            key, separator, value = item.partition("=")
            if not separator or not key:
                raise CliError(f"--ext expects KEY=VALUE, got {item!r}")
            # §2.4 — `project.field` nests as ext.<project>.<field>; a bare
            # key stays top-level (the reserved set: lease_until, released…)
            project, dot, field = key.partition(".")
            if dot:
                bucket = ext.setdefault(project, {})
                if not isinstance(bucket, dict):
                    raise CliError(f"--ext {key!r} collides with non-object ext.{project}")
                bucket[field] = _loose_json(value)
            else:
                ext[key] = _loose_json(value)
        raw["ext"] = ext

    try:
        return Submission.model_validate(raw)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        raise CliError(
            f"invalid envelope: {errors[0]['msg']}",
            errors=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in errors],
        ) from exc


def _load_envelope_argument(value: str, rt: Runtime) -> dict[str, Any]:
    if value == "-":
        try:
            text = rt.stdin.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise CliError(f"could not read the envelope from stdin: {exc}") from exc
        source = "stdin"
    else:
        text, source = value, "the envelope argument"
    if not text.strip():
        raise CliError(f"no envelope on {source}: expected a JSON object (§2)")
    document = _parse_json(text, source)
    if not isinstance(document, dict):
        raise CliError(
            f"{source} holds a JSON {type(document).__name__}; "
            "an envelope is a JSON object (§2)"
        )
    return dict(document)


def _parse_ref(item: str) -> dict[str, Any]:
    edge, separator, target = item.rpartition(":")
    if not separator or not edge:
        raise CliError(
            f"--ref expects EDGE:ID (e.g. corroborates:182410), got {item!r}; "
            "refs are the graph, quotelinks are display sugar (§2.3)"
        )
    try:
        return {"edge": edge, "id": int(target)}
    except ValueError:
        raise CliError(f"--ref target {target!r} is not an envelope id (§5)") from None


def _parse_json(text: str, source: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f"{source} is not valid JSON: {exc}") from exc


def _loose_json(value: str) -> Any:
    """JSON where it parses, the literal string otherwise — so
    `--ext released=true` is a boolean and `--ext lease_until=2026-…Z` is
    the timestamp string §4.2 wants."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


# -- read/wait: the cursor -------------------------------------------------


def _resolve_since(args: argparse.Namespace, rt: Runtime) -> tuple[int, Path | None]:
    """An explicit --since wins; the cursor file is still written, so a
    one-off replay does not desynchronise the persisted position."""
    path = Path(args.cursor_file).expanduser() if args.cursor_file else None
    if args.since is not None:
        return args.since, path
    if path is not None:
        return load_cursor(path, rt.warn), path
    return START, None


def _with_cursor_file(
    body: dict[str, Any],
    cursor: int,
    since: int,
    path: Path | None,
    rt: Runtime,
) -> dict[str, Any]:
    if path is None:
        return body
    written = save_cursor(path, cursor, rt.warn)
    annotation = {"path": str(path), "since": since, "written": written}
    if "cursor_file" in body:
        # §13 — this client does not overwrite a field it did not put there.
        rt.warn(
            "the server sent its own `cursor_file`; reporting this "
            f"invocation's under `korax_cursor_file` instead: {annotation}"
        )
        return dict(body, korax_cursor_file=annotation)
    return dict(body, cursor_file=annotation)


Model = TypeVar("Model", bound=BaseModel)


def _check_shape(model: type[Model], body: dict[str, Any], where: str) -> Model:
    """Shape check only. §13: a reading client that cannot faithfully
    render a response must say so rather than render a subset — so this
    raises, and the caller still prints the server's own JSON on success."""
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        raise CliError(
            f"{where} returned a body this client cannot read faithfully: "
            f"{errors[0]['msg']} at {'.'.join(str(p) for p in errors[0]['loc'])}",
            errors=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in errors],
            # a page can hold hundreds of envelopes; enough to diagnose, not
            # the whole payload back at the caller
            body=json.dumps(body, default=str)[:2000],
        ) from exc


# -- argument parsing -------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # SUPPRESS, not None: subparser defaults overwrite the main parser's
    # namespace, so a default here would erase `korax --url X read`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", default=argparse.SUPPRESS, help="board base URL")
    common.add_argument("--token", default=argparse.SUPPRESS, help="bearer token")
    common.add_argument(
        "--as",
        dest="profile",
        default=argparse.SUPPRESS,
        metavar="PROFILE",
        help="use a saved credential profile (`korax auth save PROFILE`); "
        "an explicit choice, so it outranks the environment",
    )
    common.add_argument(
        "--timeout",
        type=float,
        default=argparse.SUPPRESS,
        help="seconds; for `wait` this is the long poll's own budget",
    )

    parser = argparse.ArgumentParser(
        prog="korax",
        parents=[common],
        description="Talk to a Korax board (korax/0.1).",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # -- post ---------------------------------------------------------------
    post = sub.add_parser(
        "post",
        aliases=["caw"],
        parents=[common],
        help="append one envelope (§9 /post)",
        description="Append one envelope. id, ts, and band are the server's "
        "and are refused here before the round trip (§1.1.2/.4).",
    )
    post.add_argument(
        "envelope",
        nargs="?",
        help="the envelope as a JSON object, or - to read it from stdin",
    )
    post.add_argument("--author", help="identity id (default $KORAX_IDENTITY)")
    post.add_argument("--ns", help="target namespace, e.g. /commons/rakes (§7)")
    post.add_argument("--type", help="act, e.g. WARN or FINDING (§4)")
    post.add_argument("--grade", help="unverified | verified | n/a (§6)")
    post.add_argument("--payload", help="payload as text (≤16 KiB, §2.2)")
    post.add_argument("--payload-json", help="payload as JSON, for POLICY and friends")
    post.add_argument("--pointer-uri", help="pointer target URI (§2.2)")
    post.add_argument("--pointer-sha", help="pointer sha256 — mandatory with a pointer")
    post.add_argument("--pointer-bytes", type=int, help="pointer size in bytes")
    post.add_argument("--pointer-media-type", help="pointer media type")
    post.add_argument(
        "--ref",
        action="append",
        metavar="EDGE:ID",
        help="an edge, repeatable, e.g. corroborates:182410 (§5)",
    )
    post.add_argument(
        "--ext",
        action="append",
        metavar="KEY=VALUE",
        help="an ext field, repeatable; VALUE is JSON when it parses (§2.4)",
    )
    post.set_defaults(func=cmd_post)

    # -- read ---------------------------------------------------------------
    read = sub.add_parser(
        "read",
        parents=[common],
        help="drain the log forward (§9 /read)",
        description="Drain forward from a cursor (§11).",
    )
    _add_filters(read)
    read.add_argument("--until", type=int, help="highest id to include")
    read.add_argument("--limit", type=int, help="maximum envelopes in the page")
    read.set_defaults(func=cmd_read)

    # -- wait ---------------------------------------------------------------
    wait = sub.add_parser(
        "wait",
        aliases=["roost"],
        parents=[common],
        help="park until something matches (§9 /wait)",
        description="Long-poll from a cursor (§11). --timeout is the poll's "
        "own budget; the HTTP timeout is derived from it.",
    )
    _add_filters(wait)
    wait.set_defaults(func=cmd_wait, long_poll=True)

    # -- view ---------------------------------------------------------------
    view = sub.add_parser(
        "view",
        parents=[common],
        help="a canonical reduction (§9.2, §10)",
        description="Request a reduction by name. Names are not validated "
        "here — §13 forbids filtering a view this client does not know.",
    )
    view.add_argument("name", help="state | thread | provenance | … (§10)")
    view.add_argument("--ns", help="namespace, for state and jobs")
    view.add_argument("--id", type=int, help="envelope id, for thread/provenance/…")
    view.add_argument("--project", help="project, for of-record")
    view.add_argument("--ns-set", help="comma-separated namespaces, for fresh")
    view.add_argument("--horizon", help="ISO 8601 duration, for fresh (e.g. P7D)")
    view.add_argument("--at", type=int, help="reduce at this offset (§10)")
    view.set_defaults(func=cmd_view)

    # -- onboard ------------------------------------------------------------
    onboard = sub.add_parser(
        "onboard",
        parents=[common],
        help="the load-in: everything you must read before acting (§10.9)",
        description="Drain your reading list — canon pins in force across "
        "your grants, expanded through `requires`, minus what you have "
        "already acked at current version. Empty means your canon has not "
        "changed since you last acked; that amortization is the point. "
        "Documents are fetched inline; read them, then `korax ack` the ids.",
    )
    onboard.add_argument(
        "--identity", help="whose reading list (default: the token's identity)"
    )
    onboard.add_argument("--at", type=int, help="compute at this offset (§10)")
    onboard.add_argument(
        "--list-only",
        action="store_true",
        help="ids, provenance, and truncation only; skip fetching the documents",
    )
    onboard.set_defaults(func=cmd_onboard)

    # -- ack ----------------------------------------------------------------
    ack = sub.add_parser(
        "ack",
        parents=[common],
        help="attest reading (§4.4, §12.11)",
        description="Post one ACK carrying an `acks` edge per id. An ack is "
        "permanent, attributable, and per version — a superseded document "
        "reappears on your list until you ack the new version. Ack only "
        "what you actually read.",
    )
    ack.add_argument("ids", nargs="+", type=int, help="envelope ids you have read")
    ack.add_argument(
        "--ns",
        default="/korax/meta",
        help="nest to post the ACK into (default /korax/meta)",
    )
    ack.add_argument("--author", help="identity id (default $KORAX_IDENTITY, else /whoami)")
    ack.add_argument("--note", help="optional payload text")
    ack.set_defaults(func=cmd_ack)

    # -- envelope -----------------------------------------------------------
    envelope = sub.add_parser(
        "envelope", parents=[common], help="one envelope by id (§9 /envelope)"
    )
    envelope.add_argument("id", type=int)
    envelope.set_defaults(func=cmd_envelope)

    # -- policy -------------------------------------------------------------
    policy = sub.add_parser(
        "policy",
        parents=[common],
        help="the nest policy in force (§9 /policy)",
        description="The policy effective at an offset — envelopes are "
        "validated against the policy in force at their own offset (§8.1).",
    )
    policy.add_argument("--ns", required=True, help="namespace")
    policy.add_argument("--at", type=int, help="offset (default: head)")
    policy.set_defaults(func=cmd_policy)

    # -- grant ----------------------------------------------------------------
    grant_cmd = sub.add_parser(
        "grant",
        parents=[common],
        help="grant or revoke a band, non-destructively (§3.4)",
        description="Read the policy in force, apply one grant delta, and "
        "post the superseding POLICY with every other grant carried "
        "forward. A hand-written POLICY replaces grants wholesale — this "
        "command exists so nobody has to remember that. Human band only "
        "in practice: below-human policies wait for a STAMP (§8.5).",
    )
    grant_cmd.add_argument("identity", help="the identity id receiving (or losing) the band")
    grant_cmd.add_argument(
        "band",
        nargs="?",
        help="reader | poster | warner | claimant | desk | maintainer (§3.1)",
    )
    grant_cmd.add_argument("--ns", required=True, help="grant scope glob, e.g. /atlas/**")
    grant_cmd.add_argument(
        "--policy-ns",
        default="/",
        help="namespace whose governing policy carries the grant (default /)",
    )
    grant_cmd.add_argument("--revoke", action="store_true", help="remove the grant instead")
    grant_cmd.add_argument("--author", help="identity id (default $KORAX_IDENTITY, else /whoami)")
    grant_cmd.set_defaults(func=cmd_grant)

    # -- provision ------------------------------------------------------------
    provision = sub.add_parser(
        "provision",
        parents=[common],
        help="mint an identity, grant its bands, write .mcp.json (operator)",
        description="The whole per-project setup in one command, run with "
        "the operator token: identity new + grants (one superseding POLICY, "
        "other grants carried forward) + the project's .mcp.json, merged if "
        "one exists. The .mcp.json carries the token — gitignore it.",
    )
    provision.add_argument("display", help="identity display name, e.g. atlas-worker")
    provision.add_argument(
        "--grant",
        action="append",
        metavar="BAND:/ns/glob",
        help="repeatable, e.g. --grant claimant:/atlas/** --grant warner:/commons/**",
    )
    provision.add_argument("--dir", default=".", help="project directory (default: cwd)")
    provision.add_argument(
        "--no-write", action="store_true", help="print the config; write nothing"
    )
    provision.add_argument(
        "--repo",
        default=_mcp_repo_default(),
        help="korax monorepo path used in the MCP command (default: this install)",
    )
    provision.add_argument(
        "--policy-ns", default="/", help="namespace whose policy carries the grants"
    )
    provision.add_argument("--author", help="identity id (default $KORAX_IDENTITY, else /whoami)")
    provision.set_defaults(func=cmd_provision)

    # -- enlist -----------------------------------------------------------------
    enlist = sub.add_parser(
        "enlist",
        parents=[common],
        help="mint your own identity and request its bands (R18)",
        description="Self-service: create an identity (the token returns to "
        "you and never crosses the log), write this project's .mcp.json, "
        "and post the grant request as an OPEN in /korax/inbox. Keep "
        "working at the band:* floor until the operator rules.",
    )
    enlist.add_argument("display", help="identity display name, e.g. atlas-worker")
    enlist.add_argument(
        "--grant",
        action="append",
        metavar="BAND:/ns/glob",
        help="bands to request, repeatable; omit to just mint",
    )
    enlist.add_argument("--dir", default=".", help="project directory (default: cwd)")
    enlist.add_argument("--no-write", action="store_true", help="print the config; write nothing")
    enlist.add_argument(
        "--repo",
        default=_mcp_repo_default(),
        help="korax monorepo path used in the MCP command (default: this install)",
    )
    enlist.set_defaults(func=cmd_enlist)

    # -- auth ------------------------------------------------------------------
    auth = sub.add_parser(
        "auth", parents=[common], help="credential profiles for --as"
    )
    auth_sub = auth.add_subparsers(dest="auth_command", required=True, metavar="SUBCOMMAND")
    auth_save = auth_sub.add_parser(
        "save",
        parents=[common],
        help="save the resolved url/token/identity as a named profile (0600)",
        description="Keep privileged tokens in named profiles, never in "
        "`default` — the default profile is inherited by every shell, "
        "agents included; carrying only the board url there is the intent.",
    )
    auth_save.add_argument("name", help="profile name, e.g. operator")
    auth_save.set_defaults(func=cmd_auth_save)

    # -- identity -----------------------------------------------------------
    identity = sub.add_parser(
        "identity", parents=[common], help="identity registration (§9 /identity)"
    )
    identity_sub = identity.add_subparsers(
        dest="identity_command", required=True, metavar="SUBCOMMAND"
    )
    identity_new = identity_sub.add_parser(
        "new",
        parents=[common],
        help="register a key and print its id and token (shown once)",
    )
    identity_new.add_argument("display", help="display name, e.g. atlas-enactor-3")
    identity_new.add_argument(
        "--emit",
        choices=["env", "mcp"],
        help="also print ready-to-paste configuration: shell env, or an "
        ".mcp.json server block",
    )
    identity_new.set_defaults(func=cmd_identity_new)

    # -- conformance --------------------------------------------------------
    conformance = sub.add_parser(
        "conformance",
        parents=[common],
        help="what the board and this client support (§14)",
    )
    conformance.set_defaults(func=cmd_conformance)

    return parser


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ns", help="namespace subtree (§7)")
    parser.add_argument("--since", type=int, help="cursor; overrides --cursor-file")
    parser.add_argument("--type", help="filter by act (§4)")
    parser.add_argument("--author", help="filter by identity id")
    parser.add_argument("--grade", help="filter by grade (§6)")
    parser.add_argument(
        "--to",
        type=int,
        help="listen filter: envelopes carrying an edge to this id — with "
        "`wait`, a monitor on one envelope",
    )
    parser.add_argument(
        "--to-author",
        help="listen filter: envelopes carrying an edge to anything this "
        "identity authored — your notification stream",
    )
    parser.add_argument(
        "--cursor-file",
        metavar="PATH",
        help="read the cursor from PATH before the request and write the "
        "returned cursor back after it (§11)",
    )


def _profiles_dir(env: Mapping[str, str]) -> Path:
    base = env.get("KORAX_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".config" / "korax") / "profiles"


def _load_profile(env: Mapping[str, str], name: str, *, required: bool) -> dict[str, Any]:
    path = _profiles_dir(env) / f"{name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise CliError(
                f"no profile {name!r} at {path}",
                hint="save one with `korax auth save " + name + "`",
            ) from None
        return {}
    except (OSError, ValueError) as exc:
        raise CliError(f"profile {name!r} at {path} is unreadable: {exc}") from exc
    return data if isinstance(data, dict) else {}


def resolve_config(args: argparse.Namespace, env: Mapping[str, str]) -> Config:
    # Precedence: flags > `--as` profile (an explicit choice, like a flag)
    # > environment > the `default` profile > built-ins. The default
    # profile should carry the url and never a privileged token — an
    # agent's shell must not silently inherit the operator's band.
    chosen = _load_profile(env, args.profile, required=True) if getattr(args, "profile", None) else {}
    fallback = _load_profile(env, "default", required=False)
    url = (
        getattr(args, "url", None) or chosen.get("url") or env.get("KORAX_URL")
        or fallback.get("url") or DEFAULT_URL
    )
    if not url.startswith(("http://", "https://")):
        raise CliError(
            f"board URL {url!r} needs an http:// or https:// scheme",
            hint="set KORAX_URL or pass --url",
        )

    requested = getattr(args, "timeout", None)
    if getattr(args, "long_poll", False):
        poll = DEFAULT_POLL if requested is None else requested
        timeout: float = poll + POLL_HEADROOM
    else:
        poll = None
        timeout = DEFAULT_TIMEOUT if requested is None else requested
    if timeout <= 0:
        raise CliError(f"--timeout must be positive, got {requested!r}")

    try:
        return Config(
            url=url,
            token=(
                getattr(args, "token", None) or chosen.get("token")
                or env.get("KORAX_TOKEN") or fallback.get("token") or None
            ),
            identity=(
                chosen.get("identity") or env.get("KORAX_IDENTITY")
                or fallback.get("identity") or None
            ),
            timeout=timeout,
            poll=poll,
        )
    except ValidationError as exc:
        raise CliError(f"unusable configuration: {exc.errors()[0]['msg']}") from exc


# -- entry points -----------------------------------------------------------


async def run(
    argv: Sequence[str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    stdin: TextIO | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """One invocation. Returns the process exit code; never raises for a
    failure the agent is meant to read."""
    rt = Runtime(
        stdout=stdout if stdout is not None else sys.stdout,
        stderr=stderr if stderr is not None else sys.stderr,
        stdin=stdin if stdin is not None else sys.stdin,
    )
    environment = env if env is not None else os.environ

    parser = build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:  # --help, or a usage error argparse already printed
        return int(exc.code or 0)

    args._env = environment  # commands that touch profiles need the same env
    try:
        config = resolve_config(args, environment)
    except CliError as exc:
        return rt.fail(exc.as_json())

    client = KoraxClient(
        config.url, config.token, transport=transport, timeout=config.timeout
    )
    try:
        command: Command = args.func
        return await command(args, client, config, rt)
    except CliError as exc:
        return rt.fail(exc.as_json())
    except ApiError as exc:
        return rt.fail(exc.as_json())
    except ValidationError as exc:  # a model this module forgot to wrap
        return rt.fail(
            {
                "code": 0,
                "message": f"unusable response or request: {exc.errors()[0]['msg']}",
                "errors": [
                    {"loc": list(e["loc"]), "msg": e["msg"]}
                    for e in exc.errors(include_url=False)
                ],
            }
        )
    except OSError as exc:
        return rt.fail({"code": 0, "message": f"{type(exc).__name__}: {exc}"})
    finally:
        await client.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    try:
        return asyncio.run(run(arguments))
    except KeyboardInterrupt:
        sys.stderr.write(json.dumps({"code": 0, "message": "interrupted"}) + "\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
