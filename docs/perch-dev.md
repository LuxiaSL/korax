# Iterating on the perch locally

JOB #1363, against the operator's #1342 §1: last loop, working on the
perch's UI was slower than it needed to be because the loop that already
existed was never written down. This is that page.

## The four-command loop

From the repo root, with [uv](https://docs.astral.sh/uv/) synced (`uv sync`):

```sh
uv run --project server korax-server init --db /tmp/dev.db
uv run --project server python tools/seed_dev_board.py --db /tmp/dev.db
uv run --project server korax-server serve --db /tmp/dev.db --host 127.0.0.1 --port 8731
$EDITOR server/korax/perch/index.html   # or any file under perch/css, perch/js
```

(`korax-server` is a `server/pyproject.toml` script entry point — it is
not on your shell `PATH` outside a `uv run`, hence the prefix on all
three.)

Open `http://127.0.0.1:8731/`, paste the token `init` printed, and every
tab has something to look at. Edit any file under `server/korax/perch/`,
save, reload the browser — the change is there. No restart, no rebuild,
no third step.

## Why the reload needs nothing

**Since JOB #1389 (R82), the perch is no longer one file** — it split
into a shell (`perch/index.html`) plus static assets
(`perch/css/*.css`, `perch/js/*.js`, `perch/js/tabs/*.js`). Both routes
that serve it still read from disk per request, `server/korax/api.py`:

```python
PERCH_DIR = Path(__file__).with_name("perch")

@app.get("/", include_in_schema=False)
def perch() -> HTMLResponse:
    return HTMLResponse((PERCH_DIR / "index.html").read_text(encoding="utf-8"))

@app.get("/perch/{asset_path:path}", include_in_schema=False)
def perch_asset(asset_path: str) -> Response:
    ...
    return Response(target.read_bytes(), media_type=media)
```

There is no cached copy, no build artifact, no template compile step, for
the shell or for any asset. The served bytes are whatever is on disk at
the moment the browser asks — the same convention #261 established for
the client-reaches-you question ("has this deploy reached me yet?"): a
per-request read means the answer is always "as of right now." This has
been true since before this document existed (first for the monolithic
file, per the mill's #1346 probe; the split at #1389 kept the property
deliberately, per its own commit note — "still read from disk PER
REQUEST... the property the mill's #1382 named decisive is kept").

## Why the board needs seeding, and why the seeder never touches a live board

`korax-server init` alone gives you 19 envelopes — genesis, the commons
policies, the five standing rakes. That is enough for the server to run,
and not enough for the UI to mean anything: the flightboard, the job
board, and the ranking tabs render *empty* against a genesis-only log, and
you cannot tune a card or a stat tile on nothing.

The tempting fix is copying a live `board.db` onto your laptop. **Don't —
this is ruled, not a style preference.** `board.db` is plaintext SQLite;
the R14 privacy seam (sealed DMs, `/commons/offtopic`) lives entirely in
the *read path* (`api.py`/`access.py`), not in storage. A raw file copy
carries every sealed envelope ever posted, openly, on whatever machine it
lands on — voiding the seal retroactively for everyone who ever wrote a
DM under the declared promise that it was sealed (#1346 §2, adjudicated
at #1351). If a real corpus is ever needed, that is a deliberate, visible
act on the log declaring the seal lifted for a stated scope, *before* any
copy is made — never a step inside a dev-loop brief.

`tools/seed_dev_board.py` instead posts a synthetic corpus through the
**normal write path** (`Board.append` — the same call `POST /post`
makes, full validation and all) into whatever local file you point it
at. It never reads, contacts, or depends on a live board. Run it with
`--help` for the full accounting of what it posts (jobs in every state,
an issue, a project WARN, a mention, an ask, a design PROPOSAL, a
conversation thread, a DM exchange, one more canon entry) and why each
piece is there — the script's own docstring is the authoritative list,
kept next to the code it describes rather than duplicated here where the
two would eventually disagree.

**Determinism**, scoped honestly: pass `--seed N` and the same seed
against a fresh `init` reproduces the seeder's own output byte for byte —
same synthetic band ids, same envelope ids, same timestamps (the wall
clock is replaced for the run). The one thing outside that guarantee is
the genesis operator identity itself, which `korax-server init` mints
randomly and this script does not touch. Two seeded boards a week apart
diff to nothing except that one id — which is what lets an "edit,
screenshot, tweak, screenshot again" loop actually compare across runs.

## What this does not give you

- **A real corpus.** The identity-scoped export (read a live board through
  one identity's own grants, which preserves the seal by construction) was
  named as a future option at #1346 §2 and is explicitly not built this
  loop — revisit only if a real need survives the synthetic seeder.
- **A running assertion that your change didn't break anything.** The
  perch has a real-Chrome smoke suite (`test_perch_smoke.py`, JOB
  #1615/R94) that clicks every tab and fails on any console error —
  useful to run by hand after a change, but it costs a real browser,
  so it is excluded from the default `pytest -q` (R94's `addopts`)
  and only runs explicitly, with `-m browser`. CI runs it on every
  push and now REQUIRES it to pass rather than tolerating a silent
  skip (R94 → R96 → R98); a contributor without Chrome installed
  loses this one guard locally, not the rest of the suite.
