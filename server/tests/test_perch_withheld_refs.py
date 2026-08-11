"""The perch renders a ref it cannot follow as WITHHELD, never as an error.

Issue #841, found in production by the operator in their own inbox: a
legitimate OPEN in `/korax/inbox` carried `derives-from` to a DM, the index
followed the ref to render it, R14's privacy seam answered 403, and `api()`
toasted the refusal — so the console threw an error banner on every reload.
**The 403 was correct; making the request the user's problem was not.**

The post side is settled as deliberately-not-built by the operator's STAMP
at #1097; this is the read half only.

WHAT THESE GUARDS ARE WORTH — the same honest split #962 established, and
the same limits. `followRef` touches only `fetch` and `token`, so it can be
lifted out and RUN with both stubbed: those tests assert behaviour. The
rendering path is checked structurally over the served page, which catches
deletion and rename but not correctness.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PERCH = Path(__file__).resolve().parents[1] / "korax" / "perch.html"
NODE = shutil.which("node")


def page() -> str:
    return PERCH.read_text(encoding="utf-8")


def script() -> str:
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", page(), re.S)
    assert blocks, "the perch serves no script block"
    return "\n".join(blocks)


def run_follow(status: int, body: object = None) -> object:
    """Run the page's own `followRef` against a stubbed fetch of `status`.

    Everything it touches is stubbed rather than reimplemented — the point
    is to execute the shipped source, not a paraphrase of it.
    """
    source = script()
    fn = re.search(r"(async function followRef\(id\) \{.*?\n\})", source, re.S)
    assert fn, (
        "`followRef` is no longer extractable — the ref-follow path was "
        "restructured, and these tests are now asserting nothing. Re-point "
        "them; do not delete them to go green."
    )
    stubs = f"""
      let TOASTED = false, MODAL = false;
      const token = () => "t";
      const toast = () => {{ TOASTED = true; }};
      const $ = () => ({{ showModal: () => {{ MODAL = true; }} }});
      globalThis.fetch = async () => ({{
        status: {status}, ok: {str(200 <= status < 300).lower()},
        json: async () => ({json.dumps(body if body is not None else {})}),
      }});
    """
    program = stubs + fn.group(1) + """
      followRef(799)
        .then((r) => process.stdout.write(JSON.stringify(
            {ok: true, value: r, toasted: TOASTED, modal: MODAL})))
        .catch((e) => process.stdout.write(JSON.stringify(
            {ok: false, error: e, toasted: TOASTED, modal: MODAL})));
    """
    result = subprocess.run([NODE, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# -- executed: the behaviour that caused the incident --------------------------


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_forbidden_ref_is_withheld_and_does_not_toast() -> None:
    """THE incident, in one assertion. #799 was a DM; the operator's inbox
    404'd its own console over it twice per reload."""
    out = run_follow(403)
    assert out["ok"] is True, "a 403 on a ref must not throw"
    assert out["value"]["withheld"] is True
    assert out["toasted"] is False, (
        "the error banner is the whole defect — swallowing the exception "
        "while still toasting would fix nothing the operator can see"
    )


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_missing_ref_is_withheld_too_and_the_fusion_is_deliberate() -> None:
    """403 and 404 are NOT distinguished, on purpose. The board fuses absence
    and denial (§8.3) — `/envelope/<sealed>` answers 404 exactly as an absent
    id does — so a client rendering "sealed" versus "gone" would be claiming
    a distinction the server spent effort destroying."""
    out = run_follow(404)
    assert out["value"]["withheld"] is True
    assert out["toasted"] is False


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_real_failure_still_toasts_and_still_throws() -> None:
    """**The control, and the reason this is not a blanket `.catch()`.**

    A 500, a dead board or a network drop are real failures. Laundering them
    into "withheld" would destroy the absent-vs-withheld distinction this
    board spent R28 and §9.3 building — the client would report a broken
    board as a privacy boundary, which is the same lie one layer up.
    """
    out = run_follow(500, {"message": "boom"})
    assert out["ok"] is False, "a 500 must still throw"
    assert out["toasted"] is True, "a real failure must still be visible"


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_an_expired_token_still_opens_the_dialog() -> None:
    """401 is neither withheld nor a toast — it is the one failure with a
    remedy the user can act on, and the ref path must not swallow it."""
    out = run_follow(401)
    assert out["ok"] is False
    assert out["modal"] is True, "a 401 must still prompt for a token"


@pytest.mark.skipif(NODE is None, reason="node absent; the executed half cannot run")
def test_a_readable_ref_returns_the_envelope_unchanged() -> None:
    """The other control. Every assertion above passes against a `followRef`
    that returns `{withheld: true}` for everything."""
    out = run_follow(200, {"id": 799, "type": "NOTE"})
    assert out["ok"] is True
    assert out["value"]["id"] == 799
    assert "withheld" not in out["value"]
    assert out["toasted"] is False


# -- structural: the render path -----------------------------------------------


def test_both_ref_following_sites_use_followRef() -> None:
    """The fix is worthless if one site still routes through `api()`. Named
    explicitly because the incident came from the site nobody was looking
    at — a background fetch on page load, not a click."""
    source = script()
    assert "const target = await followRef(id);" in source, (
        "referentStamps no longer follows refs through followRef"
    )
    assert "const e = await followRef(id);" in source, (
        "the onboard unread path no longer follows refs through followRef"
    )
    assert 'api("/envelope/" + id).catch(() => null)' not in source, (
        "a ref-follow is still swallowing errors through api(), which toasts "
        "before it throws — the exception is caught and the banner remains"
    )


def test_the_withheld_affordance_is_rendered_not_merely_skipped() -> None:
    """**The trap named when claiming this.** Returning "" for a withheld ref
    passes any test that only checks the page stops erroring — and renders a
    stamp request with no visible target at all, which is a different bug
    wearing the same green. The reader must be told the ref exists."""
    source = script()
    assert "function withheldChip(" in source
    assert "an envelope you cannot read" in source, (
        "the withheld vocabulary must reach the reader, not just the code"
    )
    # EACH SITE, not "the string appears somewhere". The first version of
    # this test asserted `"withheldChip(id," in source` and a mutation that
    # silently skipped the withheld ref at ONE of the two sites passed it —
    # because the other site still carried the call. A global substring
    # check over a file with two call sites cannot see one of them regress.
    assert 'if (target.withheld) return withheldChip(' in source, (
        "referentStamps renders nothing for a withheld referent — a stamp "
        "request with no visible target, which is the bug this fix replaces "
        "rather than the one it removes"
    )
    assert "e.withheld\n      ? withheldChip(" in source.replace("\r\n", "\n"), (
        "the onboard unread path drops a withheld required document instead "
        "of telling the reader it is required and unreachable"
    )
