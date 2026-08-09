#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "cryptography>=42.0",
#   "pydantic>=2.7",
#   "rfc8785>=0.1.4",
# ]
# ///
"""Sign / verify the Korax conformance fixture (korax-protocol.md §2.1).

The author signature covers the **client-supplied subset only** —
`proto`, `author`, `ns`, `type`, `grade`, `refs`, `payload`, `pointer`,
`ext` — canonicalised as JCS (RFC 8785) and signed ed25519 with the
band's key. Server-assigned fields (`id`, `ts`, `band`) cannot be covered
by it, so the board additionally signs the *complete accepted record*
(everything except `board_sig` itself) as `board_sig`.

Decisions this tool makes, where §2.1 leaves room (all documented in
tools/README.md):

  * **Absent fields are absent.** A member of the signed subset that is
    not present in the envelope is omitted from the signing object rather
    than emitted as `null` — JCS distinguishes the two, and the server's
    own accepted record is built with `exclude_none=True`
    (server/korax/board.py), so omission is the shape that round-trips.
  * **Encoding is `ed25519:<base64>`** — RFC 4648 standard alphabet, with
    padding, over the raw 64-byte signature.
  * **`board_sig` covers `sig`.** The accepted record includes the author
    signature, so the board's countersignature binds it along with the
    ordering fields.

Usage (from the repo root):

    uv run tools/sign_fixture.py keygen     # (re)derive conformance/keys.json
    uv run tools/sign_fixture.py sign       # -> conformance/fixture-01.signed.jsonl
    uv run tools/sign_fixture.py verify     # exits nonzero on any bad signature
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterator, Sequence

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_KEYS: Final[Path] = REPO_ROOT / "conformance" / "keys.json"
DEFAULT_FIXTURE: Final[Path] = REPO_ROOT / "conformance" / "fixture-01.jsonl"
DEFAULT_SIGNED: Final[Path] = REPO_ROOT / "conformance" / "fixture-01.signed.jsonl"

# §2.1 — exactly the client-supplied subset, in spec order. Order is
# cosmetic (JCS sorts keys) but keeps the code readable against the spec.
SIGNED_FIELDS: Final[tuple[str, ...]] = (
    "proto",
    "author",
    "ns",
    "type",
    "grade",
    "refs",
    "payload",
    "pointer",
    "ext",
)

# Fields that must exist on every envelope for signing to mean anything.
REQUIRED_FIELDS: Final[tuple[str, ...]] = ("proto", "author", "ns", "type")

SIG_PREFIX: Final[str] = "ed25519:"
BOARD_SIG_FIELD: Final[str] = "board_sig"
AUTHOR_SIG_FIELD: Final[str] = "sig"

# Deterministic, published seed derivation. These are fixture keys, not
# secrets; anyone can regenerate the file from this one line.
SEED_DOMAIN: Final[str] = "korax-conformance-v1:"

FIXTURE_IDENTITIES: Final[tuple[str, ...]] = (
    "band:human",
    "band:desk1",
    "band:e1",
    "band:e2",
    "band:e3",
)
BOARD_ID: Final[str] = "board:korax-conformance"

KEYS_COMMENT: Final[str] = (
    "Korax conformance test keys. NOT SECRETS — these seeds are published, "
    "deterministic, and exist only so fixture-01 has reproducible signatures. "
    "Never use them for a real board. Each seed is "
    "sha256('" + SEED_DOMAIN + "' + <identity id>) as 32-byte hex; `public` is "
    "the raw ed25519 public key hex. Signatures are emitted as "
    "'ed25519:<standard base64 of the 64-byte signature>'. `identities` signs "
    "the §2.1 client subset as `sig`; `board` signs the complete accepted "
    "record (everything but `board_sig`) as `board_sig`. Regenerate with "
    "`uv run tools/sign_fixture.py keygen`."
)


class SigningError(Exception):
    """Anything the operator can fix: a missing file, a malformed line, an
    envelope authored by an identity with no key."""


# --------------------------------------------------------------------------
# key material
# --------------------------------------------------------------------------


def _hex32(value: str, field: str) -> str:
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not hex: {exc}") from exc
    if len(raw) != 32:
        raise ValueError(f"{field} must be 32 bytes ({len(raw)} given)")
    return value.lower()


class KeyPair(BaseModel):
    """One ed25519 keypair: a 32-byte seed and the public key it implies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: str
    public: str

    @field_validator("seed")
    @classmethod
    def _check_seed(cls, v: str) -> str:
        return _hex32(v, "seed")

    @field_validator("public")
    @classmethod
    def _check_public(cls, v: str) -> str:
        return _hex32(v, "public")

    def private_key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(self.seed))

    def public_key(self) -> Ed25519PublicKey:
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public))

    def assert_consistent(self, name: str) -> None:
        """A seed and a public key that disagree would fail verification in
        a way that looks like a signing bug. Catch it at load time."""
        derived = derive_public_hex(self.seed)
        if derived != self.public:
            raise SigningError(
                f"{name}: `public` does not match `seed` "
                f"(seed implies {derived}, file says {self.public})"
            )


class BoardKey(KeyPair):
    """The board's countersigning key. `id` is informational."""

    id: str = Field(min_length=1)


class KeyFile(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    comment: str = Field(alias="_comment", default="")
    identities: dict[str, KeyPair]
    board: BoardKey

    def assert_consistent(self) -> None:
        for name, pair in self.identities.items():
            pair.assert_consistent(name)
        self.board.assert_consistent("board")

    def key_for(self, author: str) -> KeyPair:
        pair = self.identities.get(author)
        if pair is None:
            known = ", ".join(sorted(self.identities)) or "<none>"
            raise SigningError(
                f"unknown author {author!r}: no key in the key file (known: {known})"
            )
        return pair


def derive_seed_hex(identity: str) -> str:
    return hashlib.sha256((SEED_DOMAIN + identity).encode("utf-8")).hexdigest()


def derive_public_hex(seed_hex: str) -> str:
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))
    return key.public_key().public_bytes_raw().hex()


def load_keys(path: Path) -> KeyFile:
    if not path.exists():
        raise SigningError(
            f"no key file at {path}. Generate the fixture keys with "
            f"`uv run tools/sign_fixture.py keygen`."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SigningError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SigningError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SigningError(f"{path}: expected a JSON object at the top level")
    try:
        keys = KeyFile.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "<root>"
        raise SigningError(f"{path}: malformed key file at `{loc}`: {first['msg']}") from exc
    keys.assert_consistent()
    return keys


# --------------------------------------------------------------------------
# fixture I/O
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Line:
    """One physical line of a .jsonl fixture."""

    lineno: int
    obj: dict[str, Any]

    @property
    def is_comment(self) -> bool:
        """The fixture's first line is a bare `_comment` header, not an
        envelope. Anything with no `type` and no `id` is metadata."""
        return "type" not in self.obj and "id" not in self.obj

    @property
    def label(self) -> str:
        ident = self.obj.get("id")
        return f"id={ident}" if ident is not None else f"line {self.lineno}"


def read_jsonl(path: Path) -> list[Line]:
    if not path.exists():
        raise SigningError(f"no fixture at {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SigningError(f"cannot read {path}: {exc}") from exc

    lines: list[Line] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SigningError(f"{path}:{lineno}: malformed JSON: {exc.msg}") from exc
        if not isinstance(obj, dict):
            raise SigningError(
                f"{path}:{lineno}: expected a JSON object, got {type(obj).__name__}"
            )
        lines.append(Line(lineno=lineno, obj=obj))
    if not lines:
        raise SigningError(f"{path}: no records")
    return lines


def envelopes(lines: Sequence[Line]) -> Iterator[Line]:
    for line in lines:
        if not line.is_comment:
            yield line


def dump_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
    body = "".join(
        json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n" for rec in records
    )
    try:
        path.write_text(body, encoding="utf-8")
    except OSError as exc:
        raise SigningError(f"cannot write {path}: {exc}") from exc


# --------------------------------------------------------------------------
# §2.1 canonicalisation and signing
# --------------------------------------------------------------------------


def canonicalise(obj: dict[str, Any], what: str) -> bytes:
    """RFC 8785 JCS, delegated to the `rfc8785` package.

    The fixture contains only objects, arrays, strings, integers, booleans
    and null — no floats — so the interesting half of JCS (ES6 number
    formatting) is exercised only on integers here."""
    try:
        return rfc8785.dumps(obj)
    except (TypeError, ValueError) as exc:
        raise SigningError(f"{what}: not canonicalisable per RFC 8785: {exc}") from exc


def author_signing_input(line: Line) -> dict[str, Any]:
    """The §2.1 client-supplied subset. Absent members stay absent."""
    missing = [f for f in REQUIRED_FIELDS if f not in line.obj]
    if missing:
        raise SigningError(
            f"{line.label}: envelope is missing required field(s): {', '.join(missing)}"
        )
    return {field: line.obj[field] for field in SIGNED_FIELDS if field in line.obj}


def board_signing_input(record: dict[str, Any]) -> dict[str, Any]:
    """The complete accepted record — every field except `board_sig`,
    which necessarily includes the server-assigned `id`, `ts`, `band` and
    the author's `sig`."""
    return {k: v for k, v in record.items() if k != BOARD_SIG_FIELD}


def encode_sig(raw: bytes) -> str:
    return SIG_PREFIX + base64.b64encode(raw).decode("ascii")


def decode_sig(value: object, what: str) -> bytes:
    if not isinstance(value, str):
        raise SigningError(f"{what}: signature must be a string, got {type(value).__name__}")
    if not value.startswith(SIG_PREFIX):
        raise SigningError(f"{what}: signature must start with {SIG_PREFIX!r}")
    try:
        raw = base64.b64decode(value[len(SIG_PREFIX) :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SigningError(f"{what}: signature is not valid base64: {exc}") from exc
    if len(raw) != 64:
        raise SigningError(f"{what}: ed25519 signature must be 64 bytes ({len(raw)} given)")
    return raw


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def cmd_keygen(args: argparse.Namespace) -> int:
    keys_path: Path = args.keys
    identities = {
        identity: {"seed": (seed := derive_seed_hex(identity)), "public": derive_public_hex(seed)}
        for identity in FIXTURE_IDENTITIES
    }
    board_seed = derive_seed_hex(BOARD_ID)
    document = {
        "_comment": KEYS_COMMENT,
        "identities": identities,
        "board": {
            "id": BOARD_ID,
            "seed": board_seed,
            "public": derive_public_hex(board_seed),
        },
    }
    if keys_path.exists() and not args.force:
        # Regeneration is deterministic, so an identical rewrite is a no-op;
        # a differing one means someone hand-edited the file.
        try:
            existing = json.loads(keys_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SigningError(
                f"{keys_path} exists but could not be read for comparison ({exc}); "
                f"pass --force to overwrite it"
            ) from exc
        if existing != document:
            raise SigningError(
                f"{keys_path} exists and differs from the derived key set; "
                f"pass --force to overwrite it"
            )
        print(f"keygen: {keys_path} already up to date")
        return 0
    try:
        keys_path.parent.mkdir(parents=True, exist_ok=True)
        keys_path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise SigningError(f"cannot write {keys_path}: {exc}") from exc
    print(f"keygen: wrote {len(identities)} identities + board key -> {keys_path}")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    keys = load_keys(args.keys)
    lines = read_jsonl(args.fixture)
    board_key = keys.board.private_key()

    out: list[dict[str, Any]] = []
    signed = 0
    for line in lines:
        if line.is_comment:
            out.append(line.obj)
            continue

        author = line.obj.get("author")
        if not isinstance(author, str) or not author:
            raise SigningError(f"{line.label}: missing or non-string `author`")
        pair = keys.key_for(author)

        # Rebuild without any pre-existing signatures so re-signing is
        # idempotent and the two sig fields land last, in spec order.
        record = {
            k: v for k, v in line.obj.items() if k not in (AUTHOR_SIG_FIELD, BOARD_SIG_FIELD)
        }
        payload = canonicalise(author_signing_input(line), f"{line.label} author subset")
        record[AUTHOR_SIG_FIELD] = encode_sig(pair.private_key().sign(payload))

        accepted = canonicalise(board_signing_input(record), f"{line.label} accepted record")
        record[BOARD_SIG_FIELD] = encode_sig(board_key.sign(accepted))

        out.append(record)
        signed += 1

    dump_jsonl(args.out, out)
    print(f"sign: {signed} envelopes signed with {args.keys.name} -> {args.out}")
    print(f"sign: board key {keys.board.id} ({keys.board.public})")
    return 0


@dataclass(frozen=True, slots=True)
class VerifyResult:
    label: str
    author: str
    sig_ok: bool
    board_ok: bool
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.sig_ok and self.board_ok

    def render(self) -> str:
        mark = "ok  " if self.ok else "FAIL"
        line = (
            f"  {mark} {self.label:<9} {self.author:<12} "
            f"sig={'ok' if self.sig_ok else 'BAD'} "
            f"{BOARD_SIG_FIELD}={'ok' if self.board_ok else 'BAD'}"
        )
        return line + (f"  -- {self.detail}" if self.detail else "")


def _verify_one(line: Line, keys: KeyFile) -> VerifyResult:
    author = line.obj.get("author")
    label = line.label
    if not isinstance(author, str) or not author:
        return VerifyResult(label, "<none>", False, False, "missing or non-string `author`")
    try:
        pair = keys.key_for(author)
    except SigningError as exc:
        return VerifyResult(label, author, False, False, str(exc))

    sig_ok = False
    board_ok = False
    details: list[str] = []

    if AUTHOR_SIG_FIELD not in line.obj:
        details.append("no `sig` on the envelope")
    else:
        try:
            raw = decode_sig(line.obj[AUTHOR_SIG_FIELD], f"{label} sig")
            pair.public_key().verify(
                raw, canonicalise(author_signing_input(line), f"{label} author subset")
            )
            sig_ok = True
        except InvalidSignature:
            details.append(f"author signature does not verify under {author}'s key")
        except SigningError as exc:
            details.append(str(exc))

    if BOARD_SIG_FIELD not in line.obj:
        details.append("no `board_sig` on the envelope")
    else:
        try:
            raw = decode_sig(line.obj[BOARD_SIG_FIELD], f"{label} {BOARD_SIG_FIELD}")
            keys.board.public_key().verify(
                raw, canonicalise(board_signing_input(line.obj), f"{label} accepted record")
            )
            board_ok = True
        except InvalidSignature:
            details.append(f"board signature does not verify under {keys.board.id}")
        except SigningError as exc:
            details.append(str(exc))

    return VerifyResult(label, author, sig_ok, board_ok, "; ".join(details))


def cmd_verify(args: argparse.Namespace) -> int:
    keys = load_keys(args.keys)
    lines = read_jsonl(args.input)

    results = [_verify_one(line, keys) for line in envelopes(lines)]
    if not results:
        raise SigningError(f"{args.input}: no envelopes to verify")

    failures = [r for r in results if not r.ok]
    print(f"verify: {args.input} against {args.keys.name} ({len(results)} envelopes)")
    for result in results:
        if args.report_all or not result.ok:
            print(result.render())

    if failures:
        print(f"verify: FAILED — {len(failures)}/{len(results)} envelopes bad")
        return 1
    print(f"verify: OK — {len(results)}/{len(results)} envelopes verify "
          f"(sig + {BOARD_SIG_FIELD})")
    return 0


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sign_fixture.py",
        description="Sign and verify Korax conformance fixtures (korax-protocol.md §2.1).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="derive conformance/keys.json deterministically")
    keygen.add_argument("--keys", type=Path, default=DEFAULT_KEYS)
    keygen.add_argument("--force", action="store_true", help="overwrite a hand-edited key file")
    keygen.set_defaults(func=cmd_keygen)

    sign = sub.add_parser("sign", help="sign an unsigned fixture")
    sign.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    sign.add_argument("--keys", type=Path, default=DEFAULT_KEYS)
    sign.add_argument("--out", type=Path, default=DEFAULT_SIGNED)
    sign.set_defaults(func=cmd_sign)

    verify = sub.add_parser("verify", help="verify every sig and board_sig in a signed fixture")
    verify.add_argument("--input", type=Path, default=DEFAULT_SIGNED)
    verify.add_argument("--keys", type=Path, default=DEFAULT_KEYS)
    verify.add_argument(
        "--report-all",
        action="store_true",
        help="print a line per envelope even when everything verifies",
    )
    verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except SigningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
