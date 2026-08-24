"""THE EXHIBIT: a floors row's recorded number is reproduced from the pair
the row itself names (JOB #3239, acceptance ruled at #3255 §1).

WHAT THIS PROVES, AND WHAT IT DELIBERATELY DOES NOT. It proves the
seventh field earns itself INSIDE the delivery that adds it: the two
shas on a row are sufficient to recompute that row's floor, end to end,
with no information from outside the file. It is an exhibit for ONE row.

It is NOT the standing refusal check — "a row whose floor disagrees with
what its shas reproduce is REFUSED" — which is a follow-on claimable item
(#3255 §1). That check cannot live in the `floors` leg: reproduction
means merge-tree plus a materialisation plus a collect, and putting that
inside the battery's one DECIDED leg converts it to a sampled one — the
leg that exists so every other leg's calibration is known-good before
anything runs. The decided property outranks in-run verification.

MARKED OUT OF THE DEFAULT BATTERY (`reproduce`). It builds a tree and
runs a real collect in it; every other delivery pays nothing for it, the
same bargain the `browser` marker already strikes. Run it with
`pytest -m reproduce`.

`korax: needs-git-history` — it asks the real repository about two real
shas, and at depth 1 neither resolves. Declared per #2831; the shallow
leg decides what to do with it, which is the leg's job and not this
file's prediction.

WHY IT READS THE OID AND NOT THE EXIT STATUS (#3252 §2). `merge-tree`
exits non-zero for ANY conflict, and for a real delivery there is always
one: every delivery appends a `## R-NEXT` entry at the ledger tail and
main's tail has moved, so `docs/korax-revisions.md` conflicts by
construction. The exhibit pair does exactly this — exit 1, live conflict
markers in the written tree — and still collects the recorded count.

AND WHY IT CHECKS THE CONFLICTED PATHS ANYWAY (#3256, quill). "Read the
oid, never the exit code" is safe only while the conflict cannot affect
collection. A conflict landing in a file collection reads does not fail
loudly: the markers are a SyntaxError, pytest reports
`977/985 tests collected ... 1 error`, and `collect_selected` greps that
line and takes 977 — an ordinary, parseable count, silently low. The
failure mode is a false REFUSAL blaming an honest row, so the bound is
asserted here rather than trusted.

THE PREDICATE IS AN ALLOWLIST, AND THAT IS THE WHOLE POINT (#3332).
Two denylists were tried and both leaked:

    "inside server/tests"   missed server/korax/**, which conftest
                            imports (#3324)
    "any .py"               missed server/pyproject.toml, whose
                            addopts/testpaths/markers decide what is
                            collected and deselected at all (#3332)

Each was a true description of a danger and neither was the whole set.
So this does not enumerate what is dangerous — it enumerates what is
INERT (docs/**, *.md) and refuses everything else. It fails closed on a
file type nobody thought about, which is the property both denylists
lacked, and it is exactly as cheap: the same list, a different predicate.

THE DOCSTRING STATES THE PREDICATE, NOT THE INTENTION, for the reason
the two misses share: "disjoint from what collection reads" and "outside
the Python import graph" are both TRUE descriptions that permit a wrong
implementation. Writing the intention where the predicate belongs is how
both holes got in.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FLOORS = REPO / "tools" / "gate-floors.txt"

# The row this exhibit reproduces, and the tree path its count comes from.
EXHIBIT_LEG = "suite-server"
EXHIBIT_PATH = "server/tests"

pytestmark = pytest.mark.reproduce


def _row(leg: str) -> list[str]:
    for line in FLOORS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if fields and fields[0] == leg:
            return fields
    raise AssertionError(f"no {leg} row in {FLOORS}")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False,
    )


def test_the_exhibit_row_reproduces_from_the_pair_it_names(tmp_path: Path) -> None:
    fields = _row(EXHIBIT_LEG)
    assert len(fields) == 7, f"row is not in the seven-field shape: {fields}"
    _, floor, base, delivery, _revision, _band, _date = fields

    for name, sha in (("base", base), ("delivery", delivery)):
        probe = _git("cat-file", "-e", f"{sha}^{{commit}}")
        if probe.returncode != 0:
            pytest.skip(
                f"{name} sha {sha} does not resolve here (shallow clone or "
                "pruned history) — the row cannot be reproduced, which the "
                "shallow leg is entitled to observe rather than this test "
                "asserting against it"
            )

    merged = _git("merge-tree", "--write-tree", base, delivery)
    # THE OID, NOT THE EXIT STATUS. Non-zero is expected here.
    lines = merged.stdout.splitlines()
    assert lines, f"merge-tree produced no stdout at all: {merged.stderr!r}"
    tree = lines[0].strip()
    assert len(tree) == 40 and all(c in "0123456789abcdef" for c in tree), (
        f"first stdout line is not a tree oid: {tree!r}"
    )

    # QUILL'S BOUND (#3256), ASSERTED RATHER THAN ASSUMED. merge-tree names
    # the conflicted paths in the same output the oid came from. If any of
    # them is inside the path we are about to collect, the count would be
    # ordinary, parseable and WRONG — so the reproduction is invalid and
    # this test must say that, not blame the row.
    conflicted = [
        line.split("Merge conflict in", 1)[1].strip()
        for line in merged.stdout.splitlines() + merged.stderr.splitlines()
        if "Merge conflict in" in line
    ]
    # ALLOWLIST, NOT DENYLIST (#3332). Two denylists were tried and both
    # had holes: "inside server/tests" missed `server/korax/**`, which
    # conftest imports (#3324); "any .py" missed `server/pyproject.toml`,
    # whose `addopts`/`testpaths`/`markers` decide what is collected and
    # deselected at all. Enumerating what is DANGEROUS was wrong twice,
    # so enumerate what is INERT instead and refuse everything else.
    # This fails closed on a file type nobody thought about, which is the
    # property both denylists lacked. The real case passes trivially: the
    # ledger conflict is `docs/korax-revisions.md`.
    collides = [
        p for p in conflicted
        if not (p.startswith("docs/") or p.endswith(".md"))
    ]
    assert not collides, (
        "the reproduction is INVALID, not the row: merge-tree conflicted "
        "outside the known-inert set (docs/**, *.md), so the collected "
        "count may be silently wrong — markers are a SyntaxError and a "
        "changed pyproject changes the selection, both of which still "
        f"print an ordinary count (#3256/#3324/#3332). Conflicted: {collides}"
    )

    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH; the reproduction needs a resolved env")

    work = tmp_path / "tree"
    work.mkdir()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", tree],
        cwd=REPO, capture_output=True, check=False,
    )
    assert archive.returncode == 0, (
        f"could not archive the reproduced tree: {archive.stderr!r}"
    )
    untar = subprocess.run(
        ["tar", "-x", "-C", str(work)], input=archive.stdout,
        capture_output=True, check=False,
    )
    assert untar.returncode == 0, f"could not extract the tree: {untar.stderr!r}"

    collect = subprocess.run(
        ["uv", "run", "--project", str(work), "pytest", "-q", "--collect-only",
         EXHIBIT_PATH],
        cwd=work, capture_output=True, text=True, check=False, timeout=900,
    )
    # `--collect-only` ONLY. A second -q would make the leg's own -q into
    # -qq and suppress the count line entirely (the R165 trap, guarded
    # structurally in test_gate_sh.py).
    counted = [
        line for line in collect.stdout.splitlines() if "tests collected" in line
    ]
    assert counted, (
        "no collected-count line — the reproduction produced nothing to "
        f"compare, so this is unreadable rather than wrong: {collect.stdout[-2000:]!r}"
    )
    selected = int(counted[-1].split("/")[0].split()[-1])

    assert selected == int(floor), (
        f"{EXHIBIT_LEG}: the row records floor {floor}, but the pair it "
        f"names ({base}+{delivery}) reproduces {selected}. Either the row is "
        "wrong or the procedure in the floors-file header no longer "
        "describes how the number was taken."
    )
