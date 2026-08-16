"""The shell must DEFINE what it calls — the R82-split regression class.

`node --check` (test_perch_script_parses) proves the script PARSES; it
cannot see a missing definition, because an undefined identifier is a
RUNTIME ReferenceError, not a syntax error. The R82 split moved 21
sections whole and dropped a 4-line helper that sat between two of
them (`postNsValue`, old perch.html:488) — the parser guard stayed
green while the operator's Speak tab threw on open (reported live,
2026-08-11, with the console trace).

A full undefined-reference sweep needs a DOM runtime and is filed as
its own issue; this test pins the seam that actually broke: every
form-helper the shell's inline handlers call by name must be defined
in the shell or a shipped js file.
"""

from __future__ import annotations

import re
from pathlib import Path

PERCH = Path(__file__).resolve().parents[1] / "korax" / "perch"


def _bundle() -> str:
    parts = [(PERCH / "index.html").read_text(encoding="utf-8")]
    for js in sorted(PERCH.glob("js/**/*.js")):
        parts.append(js.read_text(encoding="utf-8"))
    assert len(parts) > 1, "glob found no js files — the guard went vacuous"
    return "\n".join(parts)


def test_every_helper_the_shell_invokes_is_defined() -> None:
    bundle = _bundle()
    # helpers invoked from the shell's inline script by bare name;
    # extend this list when a new form helper appears.
    for name in ("postNsValue", "renderMentions", "fillNsPicks",
                 "toggleThreadNode", "envelopeCached",
                 "toggleSave", "loadSaves", "loadSaved", "refreshSaveButtons",
                 "loadInboxMessages",
                 # JOB #1842 — the grant console's handlers are invoked from
                 # rendered onclick attributes by bare name; a missing one is
                 # a runtime ReferenceError on the operator's approve click.
                 "requestBlock", "composeGrantSuccessor", "renderGrantDiff",
                 "reviewGrant", "postGrantApproval", "declineGrant",
                 "postGrantDecline",
                 # JOB #1927 — THE MARKUP-ONLY CLASS (#1941). Each of these
                 # is referenced ONLY from an onclick= inside a template
                 # literal, so it has zero lexical callers: a parser, a
                 # linter and `node --check` all see an unused function, and
                 # the extraction that stranded one would look clean in
                 # every static check this repo owns. `openEnvelope` alone
                 # is reached from eleven different render sites and called
                 # from nowhere in code.
                 "openEnvelope", "stamp", "ackAll", "closeOpen",
                 "inboxDisposition", "openProfile", "selectGraphNode",
                 "fbHopLabel", "drawGraph", "mayStamp", "contextBlock",
                 "referentStamps", "stampBlock", "mentionRefusal",
                 # and every loader the split moved, by name: the tab
                 # dispatcher looks them up at click time, so a module that
                 # failed to ship is a dead tab and nothing else.
                 "loadBands", "loadConversation", "loadEnvelope",
                 "loadFlight", "loadGraph", "loadInbox", "loadLedger",
                 "loadOnboard", "loadRatifications", "loadSpeak",
                 # JOB #1969 (S1) — the router's own seams: renderProfile is
                 # called from the shell's route() ACROSS the file boundary
                 # (it lives in bands.js), and setHash is called from three
                 # modules back into the shell. Same distance-break class.
                 "renderProfile", "setHash", "route", "parseRoute",
                 "showTab", "routeFor", "setNsPick",
                 # JOB #2199 (S2) — the thread page. Every one of these is
                 # reached from a rendered onclick and from nowhere in code,
                 # which is the markup-only class above: `thJump` is bound
                 # from two chip kinds, `thToggle` from every card, and the
                 # modal's three actions from the shell's <dialog>. The
                 # router calls `loadThread` across the file boundary and
                 # conversation.js calls `openThread` across another.
                 "loadThread", "openThread", "thToggle", "thExpandAll",
                 "thJump", "thReply", "thRenderReply", "thBacklinks",
                 "thOrder", "thCard", "thQuoteChip", "thBackChip",
                 "thPayloadHtml", "thModalGo", "thModalReply", "thModalPeek",
                 # JOB #2243 (S3) — the board page. `openBoard` is reached
                 # from a thread card's ns chip and a user page's post
                 # row, both rendered onclicks in files other than the
                 # browse.js it is defined in — the same cross-file-by-
                 # markup class `renderProfile`/`openThread` already
                 # established.
                 "openBoard"):
        assert re.search(rf"\bfunction {name}\s*\(", bundle) or re.search(
            rf"\b(const|let)\s+{name}\s*=", bundle
        ), f"{name}() is called but never defined — the R82-split class"


def test_the_canary_direction() -> None:
    # the guard must be able to fail: a name nobody defines is absent.
    bundle = _bundle()
    assert not re.search(r"\bfunction definitelyNotDefinedAnywhere\s*\(", bundle)


def test_no_perch_source_carries_a_raw_nul() -> None:
    """#1896 — a literal NUL byte in JS source parses and runs, and git
    then classifies the file as BINARY: no textual diff ever again, grep
    silently exits 1 over real matches, and the next merge conflict is
    hand-pick-a-whole-version. Found live in the grant console's key
    delimiter, written as the raw byte instead of the `\\u0000` escape —
    identical semantics, opposite reviewability. Every review instrument
    this board trusts assumes text; this pins that assumption."""
    offenders = []
    for path in [PERCH / "index.html", *PERCH.glob("js/**/*.js"),
                 *PERCH.glob("css/**/*.css")]:
        if b"\x00" in path.read_bytes():
            offenders.append(str(path.relative_to(PERCH)))
    assert offenders == [], (
        f"raw NUL bytes in {offenders} — write the \\u0000 escape instead; "
        "a NUL in source turns the file binary for git and silent for grep "
        "(#1896)"
    )
