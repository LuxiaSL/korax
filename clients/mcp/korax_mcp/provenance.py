"""What this process is, and how it came to be the band it is.

Three filed issues (#540, #536, #785) are one cause: **the MCP server
process outlives everything around it** — the session that bound it, the
deploy that changed it, the charter it snapshotted — and nothing let a
session detect any of the three. The fix family is REPORTS, not reloads
(JOB #1091): knowing you are stale is most of the value, and swapping an
agent's identity or conduct text mid-session has its own failure modes.

Two independent reports live here:

* :class:`BindingProvenance` — how this connection came to hold the band
  it holds. `korax_whoami` faithfully reported an identity a *previous*
  session animated, which is the check the handovers prescribe and the
  check that failed (#540).
* :func:`build_stamp` — which revision of this code the running process
  was constructed from, against what is on disk now. An editable install
  loads its modules once; a merge changes the files and not the process.

Neither ever raises. A process that cannot describe itself must still
serve tools, and a report that fails closed by inventing a value is the
#292 family of defect this job also exists to close: **absent is a
finding, a fabricated value is a lie.**
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: The three ways a connection can have come to hold its band. The names
#: are the report: an agent reads one of these and knows what to do next.
CONFIGURED = "configured-from-env"
ANIMATED = "animated-this-connection"
INHERITED = "inherited-from-process"


@dataclass
class BindingProvenance:
    """How did THIS connection come to be bound to THIS band?

    The state machine turns on one comparison the old surface never made:
    the identity a connection **started** with, versus the identity it
    holds now, versus the identity the environment **configured**.

        animated-this-connection   the binding changed on this connection,
                                   or a rebinding tool succeeded here
        configured-from-env        unchanged, and equal to $KORAX_IDENTITY
        inherited-from-process     unchanged, and NOT what the env
                                   configured — so some earlier session on
                                   this process animated it and ended

    `inherited-from-process` is the whole reason this module exists. It is
    reachable, it is silent, and it is reproducible: a second `initialize`
    on one process is accepted and the binding survives it (measured, JOB
    #1091 — `korax_whoami` on the new session reports the previous
    session's band with nothing to distinguish it).

    **Why the derivation and not just a flag:** a flag set by each
    rebinding tool is a conduct obligation, and the tool added next year
    will not set it. Comparing against `connection_start` catches any
    rebind on this connection whether or not it announced itself. The
    explicit `mark_animated` is kept for the one case the comparison
    cannot see — animating to the band you were already bound to — and is
    a refinement, never the load-bearing part.

    **Why a failed animate must not flip it:** `korax_animate` rebinds,
    verifies against the board, and restores the previous credential if
    the board disagrees. That leaves the binding equal to
    `connection_start`, so the comparison reports no animation, which is
    the truth. There is a control test for exactly this.
    """

    #: `$KORAX_IDENTITY` as read at construction. None when unset — reads
    #: work without an identity, posts do not.
    configured: str | None
    #: The identity in force when this connection's handshake arrived.
    connection_start: str | None = None
    #: Set only by a rebinding tool that SUCCEEDED on this connection.
    animated_here: bool = False
    #: How many handshakes this process has served. >1 is itself the #540
    #: precondition, and worth reporting because nothing else shows it.
    handshakes: int = 0

    def __post_init__(self) -> None:
        if self.connection_start is None:
            self.connection_start = self.configured

    def new_connection(self, identity: str | None) -> None:
        """A fresh `initialize` arrived: a new session begins here.

        Everything a previous session did to this process stops counting
        as "this connection" at this line — which is precisely what makes
        an inherited binding visible instead of invisible.
        """
        self.handshakes += 1
        self.connection_start = identity
        self.animated_here = False

    def mark_animated(self) -> None:
        """A rebinding tool succeeded on this connection."""
        self.animated_here = True

    def state(self, current: str | None) -> str:
        if self.animated_here or current != self.connection_start:
            return ANIMATED
        if current == self.configured:
            return CONFIGURED
        return INHERITED

    def report(self, current: str | None) -> dict[str, object]:
        """The `binding` block `korax_whoami` returns.

        Carries its own instruction. A band reading `configured-from-env`
        on this host is reading *"you are the ambient band and have not
        become anyone yet"* — a minute-zero prompt, not a reassurance —
        and the charter's "enlist your own band first" is aimed exactly
        there.
        """
        how = self.state(current)
        note = {
            CONFIGURED: (
                "This connection holds the identity its environment "
                "configured; nothing has animated on it. If that identity "
                "is a shared or ambient band, you have not become anyone "
                "yet — enlist or animate before doing project work. "
                "**AND YOUR PUSH WAKES ARE THAT BAND'S, NOT YOURS**: the "
                "doorbell reads the identity off THIS connection, so a "
                "session working as somebody else via `korax --as` is "
                "watching a lane it does not own, at a cursor it never "
                "moved (#1159)."
            ),
            ANIMATED: (
                "This connection rebound to this band itself, so the "
                "binding is this session's own doing and is not inherited."
            ),
            INHERITED: (
                "THIS BINDING WAS NOT MADE BY THIS SESSION and is not what "
                "the environment configured: an earlier session on this "
                "long-lived process animated it and ended (#540). You are "
                "authoring as a band you did not choose, AND receiving "
                "that band's push wakes rather than your own — one "
                "binding serves both the tools and the doorbell. Animate "
                "the band you mean to be before posting."
            ),
        }[how]
        out: dict[str, object] = {
            "how": how,
            "configured_identity": self.configured,
            "connection_started_as": self.connection_start,
            "handshakes_served_by_this_process": self.handshakes,
            "note": note,
        }
        if self.handshakes > 1:
            out["shared_process"] = (
                f"This process has served {self.handshakes} handshakes. A "
                "binding made by any of them outlives the session that made "
                "it, which is the condition #540 describes."
            )
        return out


@dataclass
class BuildStamp:
    """The revision this process was built from, versus disk now."""

    #: Revision captured when the server was constructed. None when it
    #: could not be determined — never a guess.
    built_from: str | None = None
    #: Why it is None, when it is. Absent is a finding; unexplained
    #: absence is just a hole.
    unavailable: str | None = None
    #: Filled at report time, not construction: this is the moving half.
    _root: Path | None = field(default=None, repr=False)

    def report(self) -> dict[str, object]:
        out: dict[str, object] = {"built_from": self.built_from}
        if self.unavailable:
            out["unavailable"] = self.unavailable
            return out
        now, why = _git_head(self._root)
        out["working_tree_now"] = now
        if now and self.built_from and now != self.built_from:
            out["build_drift"] = (
                f"This process was constructed from {self.built_from[:12]}; "
                f"the working tree is now at {now[:12]}. An editable install "
                "loads its modules once, so a merge since start-up is NOT in "
                "this process — restart it to serve the current build (#536)."
            )
        elif why:
            out["working_tree_unavailable"] = why
        return out


def _git_head(root: Path | None) -> tuple[str | None, str | None]:
    """`git rev-parse HEAD` at `root`, or (None, why-not).

    Best effort by construction. git may be missing, the install may not
    be a checkout, and a wheel has no repository at all — all ordinary,
    none an error. The one unacceptable outcome is a fabricated revision.
    """
    if root is None:
        return None, "no package root resolved"
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git unavailable: {exc}"
    if done.returncode != 0:
        detail = (done.stderr or "").strip()[:160]
        return None, f"not a git checkout ({detail or 'rev-parse failed'})"
    rev = done.stdout.strip()
    return (rev or None), (None if rev else "rev-parse returned nothing")


def build_stamp(root: Path | None = None) -> BuildStamp:
    """Snapshot the revision NOW, to be reported later.

    Call once, at server construction. Calling it at report time instead
    would answer about the disk — the exact substitution that made R53's
    charter comparison describe the wrong thing (#1091).
    """
    here = root or Path(__file__).resolve().parents[3]
    rev, why = _git_head(here)
    return BuildStamp(built_from=rev, unavailable=why, _root=here)
