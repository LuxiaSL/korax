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
                 "loadInboxMessages"):
        assert re.search(rf"\bfunction {name}\s*\(", bundle) or re.search(
            rf"\b(const|let)\s+{name}\s*=", bundle
        ), f"{name}() is called but never defined — the R82-split class"


def test_the_canary_direction() -> None:
    # the guard must be able to fail: a name nobody defines is absent.
    bundle = _bundle()
    assert not re.search(r"\bfunction definitelyNotDefinedAnywhere\s*\(", bundle)
