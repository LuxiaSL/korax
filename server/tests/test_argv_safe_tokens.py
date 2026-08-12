"""Every credential `store.py` mints survives being typed as a flag value.

ISSUE #2114, the second branch of the gavel's #2019 ruling. luka fixed
`create_invite` (0118b56) after CI caught the 1-in-64 on R112's push;
`create_identity` and `rotate_token` drew the same `token_urlsafe(32)`
unguarded, and bearer tokens travel argv too — `korax auth save <name>
--token <TOKEN>` is the documented way to put a credential into a profile.
Measured at #2113: a dash-leading token exits 2 at the parser with both
streams otherwise empty, while the same token with an ordinary leading
character reaches the network and fails properly.

WHAT THIS SUITE IS FOR, beyond the two sites. luka's tests pin
`create_invite`; these pin the other two AND the invariant that keeps a
fourth mint from arriving unguarded — because the defect was never "one
call site is wrong", it was "the rule lived in a docstring next to one of
three identical draws" (#1912: a count is a contract nobody declares).

Every draw count here is 500 for luka's reason, stated once: at 1/64,
P(no dash in 500 draws | bug present) = (63/64)^500 ≈ 4e-4. A
three-draw test passes on the broken build, which is how this reached
main in the first place.
"""

from __future__ import annotations

import re
from pathlib import Path

from korax.store import Store, _argv_safe_token

DRAWS = 500


def _store() -> Store:
    return Store(":memory:")


# -- the helper itself ------------------------------------------------------

def test_the_helper_never_leads_with_a_dash() -> None:
    tokens = [_argv_safe_token() for _ in range(DRAWS)]
    offenders = [t for t in tokens if t.startswith("-")]
    assert not offenders, f"{len(offenders)}/{DRAWS} tokens lead with '-'"


def test_the_helper_still_mints_a_real_credential() -> None:
    """THE CONTROL, and it is the one that matters (#1009, #921).

    A helper that returned `"x"` — or the same token every time, or a
    truncated one — would pass every dash assertion in this file while
    destroying the thing it guards. Rejection sampling must reject, not
    repair: the guard's whole justification is that MANGLING the
    character would let two distinct draws collide on one hash, so this
    asserts the draws stay full-width, full-alphabet and unique.
    """
    tokens = [_argv_safe_token() for _ in range(DRAWS)]

    assert len(set(tokens)) == DRAWS, "tokens are not unique"
    # token_urlsafe(32) is 32 bytes base64url-encoded, unpadded: 43 chars.
    assert {len(t) for t in tokens} == {43}, (
        f"widths are {sorted({len(t) for t in tokens})}, not 43 — something "
        "is trimming rather than redrawing"
    )
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", t) for t in tokens)

    # and the alphabet is not silently narrowed: '-' must still appear
    # INSIDE tokens. A guard implemented as "redraw until no dash
    # anywhere" would pass every other assertion here while throwing away
    # a character of entropy at every position.
    assert any("-" in t[1:] for t in tokens), (
        "no token contains '-' after the first character in "
        f"{DRAWS} draws — the guard is rejecting more than it must"
    )


# -- the three call sites ---------------------------------------------------

def test_a_band_bearer_token_never_leads_with_a_dash() -> None:
    """`create_identity`, store.py:145. The victim types it into
    `korax auth save <name> --token <TOKEN>` (#2113)."""
    store = _store()
    tokens = [store.create_identity(f"band-{i}")[1] for i in range(DRAWS)]
    offenders = [t for t in tokens if t.startswith("-")]
    assert not offenders, f"{len(offenders)}/{DRAWS} bearer tokens lead with '-'"
    assert len(set(tokens)) == DRAWS


def test_a_rotated_token_never_leads_with_a_dash() -> None:
    """`rotate_token`, store.py:185 — **the instance worth naming.** A
    rotate happens when a credential is already lost (rake #90), so the
    new one is typed back by hand at the one moment nobody can afford a
    parser mystery."""
    store = _store()
    band, _ = store.create_identity("rotating-band")
    tokens = [store.rotate_token(band) for _ in range(DRAWS)]
    assert all(t is not None for t in tokens)
    offenders = [t for t in tokens if t.startswith("-")]
    assert not offenders, f"{len(offenders)}/{DRAWS} rotated tokens lead with '-'"


def test_rotation_still_replaces_the_token_it_rotates() -> None:
    """CONTROL for the rotate case: a `rotate_token` that stopped
    rotating would satisfy every assertion above by returning one safe
    token forever."""
    store = _store()
    band, first = store.create_identity("rotating-band")
    second = store.rotate_token(band)
    assert second is not None and second != first
    assert store.rotate_token("band:nobody") is None


# -- the invariant, which is the actual fix ---------------------------------

def test_store_draws_tokens_only_through_the_helper() -> None:
    """THE ONE THAT PREVENTS THE NEXT INSTANCE rather than fixing the
    last one.

    The bug was not that a call site was wrong. It was that three
    identical draws sat in three methods and the rule lived in a
    docstring beside one of them, so the fix for the site CI caught left
    the other two exactly as they were. Pinning the call sites by name
    would repeat that mistake one generation later: a fourth mint added
    next month passes every test above by not being mentioned in any of
    them.

    So this asserts the SOURCE property instead — `token_urlsafe` appears
    in `store.py` exactly once, inside `_argv_safe_token`. It is a
    grep-shaped test and I would rather have a runtime one, but no
    runtime check can see a call site that does not exist yet.
    """
    source = (Path(__file__).resolve().parents[1]
              / "korax" / "store.py").read_text(encoding="utf-8")

    calls = [
        i for i, line in enumerate(source.splitlines(), 1)
        if "token_urlsafe(" in line and not line.lstrip().startswith("#")
    ]
    assert len(calls) == 1, (
        f"token_urlsafe is called at lines {calls}; every credential mint "
        "must go through _argv_safe_token, or the next one repeats #2114"
    )

    helper = source[source.index("def _argv_safe_token"):]
    helper = helper[:helper.index("\nclass ")]
    assert "token_urlsafe(" in helper, (
        "the one remaining call is not the helper's own — the guard moved "
        "and this test is now pinning the wrong line"
    )


def test_the_invariant_test_can_fail() -> None:
    """CANARY for the guard above: its counting rule must actually
    discriminate. If the line filter were wrong — counting comments, or
    missing calls — the assertion would pass over a broken file.
    """
    fake = (
        "import secrets\n"
        "# token_urlsafe( in a comment must not count\n"
        "def a():\n"
        "    return secrets.token_urlsafe(32)\n"
        "def b():\n"
        "    return secrets.token_urlsafe(32)\n"
    )
    calls = [
        i for i, line in enumerate(fake.splitlines(), 1)
        if "token_urlsafe(" in line and not line.lstrip().startswith("#")
    ]
    assert calls == [4, 6], f"the counting rule is wrong: {calls}"
