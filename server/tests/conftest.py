from __future__ import annotations

import json
from pathlib import Path

import pytest

from korax.log import Log
from korax.models import Envelope
from korax.policy import PolicyTimeline

CONFORMANCE = Path(__file__).resolve().parents[2] / "conformance"

# ── cross-tree import guard (ISSUE #2286, ruled light-track at #2287) ──
# A suite must test the tree it was collected from. From a worktree with
# the shared checkout's venv active, `python -m pytest` collects THESE
# files and imports the packages from THAT checkout — the run is a hybrid
# of two revisions and nothing says so. The implementation is shared in
# `tools/tree_guard.py` and loaded BY PATH, because loading it by name
# would resolve it through the very import system under suspicion.
_TREE = Path(__file__).resolve().parents[2]
#: Only the server's own package. Naming a client one here would trip
#: `test_no_server_test_imports_a_client_package` (#1548) — which is the
#: same family of defect as this guard and stays the server's own rule.
_PACKAGES = ("korax",)


def _tree_guard():
    import importlib.util  # noqa: PLC0415
    import sys  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location(
        "korax_tree_guard", _TREE / "tools" / "tree_guard.py")
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec_module: a module loaded this way is absent
    # from sys.modules while it executes, which makes deferred annotation
    # resolution fail opaquely (the mill's #2232 §3, applied not cited).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pytest_configure(config: pytest.Config) -> None:
    guard = _tree_guard()
    try:
        guard.enforce(_TREE, _PACKAGES)
    except guard.CrossTreeImport as exc:
        raise pytest.UsageError(str(exc)) from None


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """State which tree was measured, on every run (#2290's addition).

    Here rather than in `pytest_report_header` (silent under `-q`, the
    invocation this floor uses) or in `pytest_configure` (global capture
    is active that early, so the line is written into a discarded
    buffer). Terminal summary runs after capture is released and puts
    the paths beside the counts a delivery is about to quote.
    """
    _tree_guard().announce(terminalreporter, _TREE, _PACKAGES)
    _announce_browser_instrument(terminalreporter)


def _announce_browser_instrument(terminalreporter) -> None:
    """State the live-feed rig's own parameters, on the runs where it ran.

    JOB #2966 property 4: a red should never require the reader to open the
    driver to learn how it was watched. The parameters ride the SAME hook as
    the tree line for the same measured reason — `pytest_report_header` is
    silent at negative verbosity and CI runs `-q`
    (`tools/tree_guard.py:188-210`, where both broken alternatives are
    recorded).

    Reads the module out of `sys.modules` rather than importing it: importing
    a browser test from conftest would execute its collection-time Chrome and
    node lookups on every unrelated run, and the dict is only populated when
    the test actually ran. **Silent by construction when it did not** — an
    empty dict prints nothing, so a `pytest -q server/tests` with no browser
    marker is byte-identical to before this landed.
    """
    if terminalreporter is None:
        return
    import sys  # noqa: PLC0415

    module = sys.modules.get("test_perch_live_feed_browser")
    instrument = getattr(module, "INSTRUMENT", None) if module else None
    if not instrument:
        return
    terminalreporter.write_line("live-feed instrument:")
    for key in sorted(instrument):
        terminalreporter.write_line(f"  {key}: {instrument[key]}")


def load_envelopes() -> list[Envelope]:
    envelopes = []
    with open(CONFORMANCE / "fixture-01.jsonl", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if "_comment" in record:
                continue
            envelopes.append(Envelope.model_validate(record))
    return envelopes


def load_jsonl(name: str) -> list[dict]:
    out = []
    with open(CONFORMANCE / name, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if "_comment" in record:
                continue
            out.append(record)
    return out


@pytest.fixture(scope="session")
def full_log() -> Log:
    return Log(load_envelopes())


@pytest.fixture(scope="session")
def timeline(full_log: Log) -> PolicyTimeline:
    return PolicyTimeline(full_log)


def truncated(log: Log, offset: int) -> tuple[Log, PolicyTimeline]:
    sub = Log(log.upto(offset))
    return sub, PolicyTimeline(sub)


class FakeRegistry:
    """The band registry as `mention_refusal` sees it (JOB #1079).

    **Deliberately NOT permissive.** The obvious test double answers "yes,
    that band exists" to everything, which would restore precisely the state
    this job abolished — a mention check that runs and cannot refuse. It
    knows the bands it was told about and nothing else, so a test that wants
    a mention to pass has to say who exists, and a test that forgets gets the
    refusal rather than a silent pass.
    """

    def __init__(self, bands: dict[str, str] | None = None) -> None:
        #: band id -> display name
        self.bands = dict(bands or {})

    def identity_display(self, identity_id: str) -> str | None:
        return self.bands.get(identity_id)

    def identities_with_display(self, display: str) -> list[str]:
        return sorted(i for i, d in self.bands.items() if d == display)

    def list_identities(self) -> list[dict[str, str | None]]:
        return [{"id": i, "display": d} for i, d in sorted(self.bands.items())]


# ── the browser rig (ISSUE #2608) ─────────────────────────────────────
# Six browser tests each carried their own spawn-and-kill, and every copy
# reaped Chrome's ROOT while its ~14 descendants survived — 8 orphaned
# trees and 9.0 GB on the shared host by the time it was measured
# (#2601, #2633). The rig lives in `perch_rig.py`; this fixture is what
# guarantees `reap()` runs, so a test can no longer forget it and a
# SEVENTH browser test inherits the reaping instead of copying the sixth.
@pytest.fixture()
def perch_rig():
    # Imported as a top-level module, not relatively: `server/tests/` has
    # no `__init__.py` and every sibling helper is reached this way
    # (`from perch_source import ...`).
    from perch_rig import PerchRig

    rig = PerchRig()
    try:
        yield rig
    finally:
        rig.reap()
