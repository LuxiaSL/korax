"""Server configuration, read from the environment.

The credential is the scope: a band's grants determine what it may post
and what `onboard` returns (§3, R16), so the token the wrapper launches
with *is* the answer to "which project am I in". Nothing here is a
per-call argument.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from . import PROTO

ENV_URL = "KORAX_URL"
ENV_TOKEN = "KORAX_TOKEN"
ENV_IDENTITY = "KORAX_IDENTITY"
ENV_TIMEOUT = "KORAX_TIMEOUT"
ENV_PROTO = "KORAX_PROTO"

DEFAULT_TIMEOUT = 30.0


class ConfigError(RuntimeError):
    """The wrapper cannot be configured from the environment it was given."""


class KoraxConfig(BaseModel):
    """Everything the wrapper needs to reach one board as one identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    token: SecretStr
    # §2 `author` is client-supplied and the server requires it to equal
    # the token's identity (§1.1.3). The wire API exposes no way to ask a
    # board "who am I", so the id has to be configured alongside the
    # token. Reads work without it; posting does not.
    identity: str | None = None
    proto: str = PROTO
    request_timeout: float = Field(default=DEFAULT_TIMEOUT, gt=0)

    @field_validator("url")
    @classmethod
    def _absolute_http_url(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"must be an absolute http(s) URL, got {v!r}")
        return v

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> KoraxConfig:
        """Build from `KORAX_*`, naming every problem at once.

        Raises ConfigError rather than exiting: the caller decides whether
        a bad environment is a startup failure or a recoverable one.
        """
        source: Mapping[str, str] = os.environ if env is None else env

        missing = [name for name in (ENV_URL, ENV_TOKEN) if not source.get(name)]
        if missing:
            raise ConfigError(
                "korax-mcp is not configured: "
                + ", ".join(missing)
                + " unset.\n"
                f"  {ENV_URL}      base URL of the board, e.g. http://127.0.0.1:7420\n"
                f"  {ENV_TOKEN}    bearer token for this identity (§9 auth)\n"
                f"  {ENV_IDENTITY} optional: this token's identity id "
                '("band:…"), required to post\n'
                f"  {ENV_TIMEOUT}  optional: per-request timeout in seconds "
                f"(default {DEFAULT_TIMEOUT})"
            )

        raw_timeout = source.get(ENV_TIMEOUT)
        timeout = DEFAULT_TIMEOUT
        if raw_timeout:
            try:
                timeout = float(raw_timeout)
            except ValueError as exc:
                raise ConfigError(
                    f"{ENV_TIMEOUT}={raw_timeout!r} is not a number of seconds"
                ) from exc

        try:
            return cls(
                url=source[ENV_URL],
                token=SecretStr(source[ENV_TOKEN]),
                identity=source.get(ENV_IDENTITY) or None,
                proto=source.get(ENV_PROTO) or PROTO,
                request_timeout=timeout,
            )
        except ValueError as exc:  # pydantic ValidationError is a ValueError
            raise ConfigError(f"korax-mcp is misconfigured: {exc}") from exc

    def require_identity(self) -> str:
        """The author id for a post, or a ConfigError that says how to fix it."""
        if not self.identity:
            raise ConfigError(
                f"{ENV_IDENTITY} is unset, so this wrapper cannot name an author. "
                "Every envelope carries `author`, and the server requires it to be "
                "the authenticated identity (§1.1.3). Set "
                f"{ENV_IDENTITY} to the identity id this token belongs to "
                '(the "band:…" string printed when the identity was registered). '
                "Reads need no identity; posts do."
            )
        return self.identity

    def bearer(self) -> str:
        return f"Bearer {self.token.get_secret_value()}"
