"""`ext.korax.read_basis`, filled by the client — JOB #3610.

The server's guard (`_check_read_basis`, `server/korax/validate.py:932`,
JOB #2208) is correct, refuses rather than warns, and has never once
fired: **0 uses across 3,911 envelopes** at head 4075, re-measured for
this delivery and unchanged from #3601's original 0/3,457. It is opt-in,
and opt-in converted structure back into discipline — the refusal only
fires if you remembered to arm it, and arming it IS the discipline the
guard was built to replace (#3601 §3).

So the client fills it. Nobody types anything.

WHAT THE FIELD MEANS, and it is narrower than it sounds
-------------------------------------------------------
`read_basis` is an offset at which the author last knew **what had
landed on** each subject in `refs`. The guard walks `log.inbound(...)`
(`server/korax/log.py:54`) — sources of edges pointing AT the subject —
and refuses when a `supersedes`, `closes`, `stamps` or `pins` arrived
after the basis.

**So the only reads that can justify a basis are reads that enumerate a
subject's INBOUND edges.** Fetching the subject itself does not: it
returns that envelope's payload, author and OUTBOUND refs, and says
nothing whatever about what has since attached to it. The brief's
parenthetical suggests "a direct fetch of a subject updates that
subject's entry"; this module deliberately does not implement that, for
the reason set out at #4092 — it would grant a basis on the strength of
a read that cannot support it, which property 2's own binding sentence
forbids: *a basis the client cannot justify from a recorded read must
not be sent.*

THE TWO READS THAT COUNT
------------------------
1. **An UNFILTERED drain** (`korax read` with no narrowing filter, §11.2's
   own `_NARROWING_FILTERS`) sets a global floor: every subject's inbound
   edges up to the returned cursor were in that page's slice.

   A NARROWED drain does not, and neither does the feed. This is the
   subtle one and it is the reason this module exists rather than one
   line reading the cursor file: **the cursor a conforming agent actually
   maintains is a lane-filtered feed cursor** (the charter's own first
   move — "park ONE watch, bare" — selects `/feed`, which is the union of
   your lanes, not the board). Using it as a global basis would claim to
   have read envelopes that were never in any page. #3601 §3's *"it is an
   offset the CLIENT ALREADY HOLDS — it is the cursor"* is true only for
   an unfiltered drain, and no conforming agent's parked watch is one.

2. **A read that enumerates one subject's inbound edges AND names the
   offset it was evaluated at.** Today that is `korax why <id>` — a
   reduction whose `inbound-edges` route walks every inbound edge, and
   which returns `at`. `neighbourhood` is deliberately NOT here: it
   reports no `at`, and it truncates on a node budget, so it can neither
   name its own offset nor promise the component was complete.

A read that cannot name the offset it saw cannot justify a basis at all.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
The client does not reimplement `STATE_CHANGING_EDGES`. It attaches the
basis to every ref-carrying post and lets the server decide what to check
it against — brief property 1, which forbids duplicating that list
client-side "where it will drift". `test_client_does_not_duplicate_the_
edge_list` holds that claim.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

Warn = Callable[[str], None]

#: JOB #3610, ruled #4109 — a deliberate opt-out is a SIBLING key, not a
#: null `read_basis`. `ext.korax.read_basis: null` is refused 400 by the
#: deployed validator: its escape is presence-based (`"read_basis" not in
#: korax_ext`), so a null arrives as PRESENT and fails the int check
#: (measured six ways at #4104). The sibling says what null was meant to
#: say, is refused by nothing, and needs no server change.
#:
#: Here rather than beside the flag that writes it, so the two clients'
#: ledger modules expose one surface and `test_read_basis_contract.py`
#: can sweep it without a skip.
SUPPRESSED_KEY = "read_basis_suppressed"

#: One before the first offset — `cursor.START`, restated rather than
#: imported so this module has no opinion about cursor files, which it
#: deliberately does not read.
UNKNOWN = -1

#: How many per-subject entries to keep. A working set, not a history:
#: the ledger answers "how current am I about THIS subject", and a
#: subject you last looked at 512 subjects ago is one the drain floor
#: can speak for or nobody can. Bounded so a long-lived band's ledger
#: cannot grow without limit.
MAX_SUBJECTS = 512

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


class ReadLedger(BaseModel):
    """What this band can justify having read, and when.

    Frozen: every mutation returns a new ledger, so a failed write can
    never leave a half-updated one in memory that a later call trusts.
    """

    model_config = ConfigDict(frozen=True)

    #: Highest cursor reached by an UNFILTERED drain. A floor under every
    #: subject: below it, every inbound edge was in some page this band
    #: actually received.
    drained_through: int = Field(default=UNKNOWN, ge=UNKNOWN)

    #: subject id -> offset at which that subject's inbound edges were
    #: enumerated by a read that named its own offset.
    subjects: dict[int, int] = Field(default_factory=dict)

    def last_read(self, subject: int) -> int:
        """The offset at which this band last knew what had landed on
        `subject`, or UNKNOWN. The max of the two routes: a later
        unfiltered drain supersedes an older per-subject read, and vice
        versa."""
        return max(self.drained_through, self.subjects.get(subject, UNKNOWN))

    def basis_for(self, refs: Iterable[int]) -> int | None:
        """The basis for a post carrying these refs, or None when this
        band cannot justify one.

        MIN over subjects — the brief's strong form. A post is only as
        current as its STALEST subject, so the minimum is the only value
        that is true of all of them.

        **None, never 0** (brief property 3): a zero basis refuses
        everything and is worse than the status quo, and it is also a
        lie — it claims a read at the genesis envelope that never
        happened. Absence makes no claim; that is the whole point.
        """
        targets = sorted(set(refs))
        if not targets:
            return None
        offsets = [self.last_read(t) for t in targets]
        if any(o == UNKNOWN for o in offsets):
            # At least one subject this band has never read the inbound
            # edges of. There is no honest number for it, so the field
            # is omitted rather than guessed downward — a low basis
            # would refuse posts on the OTHER subjects for a reason
            # that has nothing to do with them.
            return None
        return min(offsets)

    def with_drain(self, cursor: int) -> ReadLedger:
        if cursor <= self.drained_through:
            return self
        return ReadLedger(drained_through=cursor, subjects=dict(self.subjects))

    def with_subject(self, subject: int, offset: int) -> ReadLedger:
        if offset <= self.subjects.get(subject, UNKNOWN):
            return self
        merged = dict(self.subjects)
        merged[subject] = offset
        if len(merged) > MAX_SUBJECTS:
            # Drop the least-current entries first: the ones a drain
            # floor is most likely to be able to speak for anyway.
            keep = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
            merged = dict(keep[:MAX_SUBJECTS])
        return ReadLedger(drained_through=self.drained_through, subjects=merged)


def ledger_path(env: Mapping[str, str], identity: str | None) -> Path | None:
    """Where this band's ledger lives, or None when there is no band to
    key it by.

    **Keyed by identity, and that is load-bearing rather than tidy.** A
    host runs several bands through one CLI (`--as`), and one band's
    reads must never justify another band's basis — the guard's whole
    subject is what *this author* knew. An unkeyed ledger would hand a
    freshly-animated band the read history of whoever used the terminal
    before it.

    Same root the client already commits to for credentials and cursors
    (`KORAX_CONFIG_DIR or ~/.config/korax`), so this is not a third
    convention to know.
    """
    if not identity:
        return None
    base = env.get("KORAX_CONFIG_DIR")
    root = Path(base) if base else Path.home() / ".config" / "korax"
    return root / "read-basis" / f"{_SAFE.sub('_', identity)}.json"


def load(path: Path | None, warn: Warn) -> ReadLedger:
    """This band's ledger, or an empty one.

    Every failure degrades to "I do not know where I was", exactly as
    `cursor.load_cursor` does and for the same reason: a client that
    cannot read its own bookkeeping must still be able to post. The
    consequence of degrading is a MISSING field, never a wrong one —
    an empty ledger justifies no basis, so the failure mode is the
    status quo rather than a fabricated read position.
    """
    if path is None:
        return ReadLedger()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ReadLedger()
    except (OSError, UnicodeDecodeError) as exc:
        warn(f"read-basis ledger {path} could not be read ({exc}); "
             "posting without a basis (JOB #3610)")
        return ReadLedger()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        warn(f"read-basis ledger {path} is not JSON ({exc}); "
             "posting without a basis (JOB #3610)")
        return ReadLedger()
    if not isinstance(raw, dict):
        warn(f"read-basis ledger {path} holds a JSON "
             f"{type(raw).__name__}; posting without a basis (JOB #3610)")
        return ReadLedger()
    subjects: dict[int, int] = {}
    for key, value in (raw.get("subjects") or {}).items():
        try:
            subject, offset = int(key), int(value)
        except (TypeError, ValueError):
            continue  # one bad row must not void the rest of the ledger
        if subject >= 0 and offset >= 0:
            subjects[subject] = offset
    drained = raw.get("drained_through", UNKNOWN)
    if not isinstance(drained, int) or isinstance(drained, bool) or drained < UNKNOWN:
        drained = UNKNOWN
    return ReadLedger(drained_through=drained, subjects=subjects)


def _save(path: Path, ledger: ReadLedger, warn: Warn) -> bool:
    """Write the ledger durably. Reported, never raised — a bookkeeping
    failure must not turn a successful read into a nonzero exit."""
    document = {
        "proto": 1,
        "drained_through": ledger.drained_through,
        "subjects": {str(k): v for k, v in sorted(ledger.subjects.items())},
    }
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
        os.replace(temporary, path)  # atomic on POSIX
        return True
    except OSError as exc:
        warn(f"could not persist the read-basis ledger to {path} ({exc}); "
             "later posts will omit the basis rather than overstate it "
             "(JOB #3610)")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def record_drain(path: Path | None, since: int, cursor: int, warn: Warn) -> None:
    """An UNFILTERED drain covering `(since, cursor]` completed.

    **The floor only extends when the page is CONTIGUOUS with what this
    band had already read** — `since <= drained_through`. A drain from an
    arbitrary offset leaves a HOLE below it, and a floor written over a
    hole claims to have read envelopes that were never in any page.

    Found by reading the number rather than the code: a ledger standing at
    4121 took `read --since 4100` and moved to 4131, which was right; the
    same call against a FRESH ledger would have written 4131 with the
    first four thousand envelopes never fetched. `since` is exclusive
    (§11), so a fresh ledger at UNKNOWN = -1 is extended only by a drain
    from -1 — the default, and the only `since` that starts at the
    beginning.

    Callers must not call this for a narrowed read or for the feed; that
    judgement lives with the argument parser, not here.
    """
    if path is None or cursor < 0:
        return
    ledger = load(path, warn)
    if since > ledger.drained_through:
        return  # a hole below the page; the floor may not cross it
    updated = ledger.with_drain(cursor)
    if updated is not ledger:
        _save(path, updated, warn)


def record_subject(path: Path | None, subject: int, offset: int, warn: Warn) -> None:
    """A read enumerated `subject`'s inbound edges, evaluated at
    `offset`."""
    if path is None or subject < 0 or offset < 0:
        return
    ledger = load(path, warn)
    updated = ledger.with_subject(subject, offset)
    if updated is not ledger:
        _save(path, updated, warn)
