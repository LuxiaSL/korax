# tools

Repo-level utilities. Nothing here is imported by the server; these are
standalone [PEP 723](https://peps.python.org/pep-0723/) scripts that `uv`
runs in their own throwaway environment. **uv only — never `pip`.**

| tool | what it does |
|---|---|
| `sign_fixture.py` | signs / verifies the conformance fixtures per §2.1 |

---

## `sign_fixture.py`

The generator the conformance README has been promising: it reads
`conformance/keys.json`, canonicalises each envelope per §2.1, and emits a
signed log with both `sig` and `board_sig`.

```sh
uv run tools/sign_fixture.py keygen   # (re)derive conformance/keys.json
uv run tools/sign_fixture.py sign     # fixture-01.jsonl -> fixture-01.signed.jsonl
uv run tools/sign_fixture.py verify   # every sig + board_sig; nonzero on any failure
```

All three take `--keys`; `sign` takes `--fixture` / `--out`, `verify` takes
`--input` and `--report-all` (a line per envelope even when clean). Paths
default to the `conformance/` directory relative to the script, so the
commands above work from anywhere; the examples assume the repo root.

Round trip, in CI terms:

```sh
uv run tools/sign_fixture.py sign
uv run tools/sign_fixture.py verify
git diff --exit-code conformance/fixture-01.signed.jsonl   # signing is deterministic
```

Ed25519 signatures are deterministic and JCS has one output per value, so
re-signing an unchanged fixture is byte-identical — a dirty `git diff` after
`sign` means the source fixture changed, which is exactly the CI signal you
want.

### Exit codes

| code | meaning |
|---|---|
| `0` | all good |
| `1` | verification failed — a per-envelope report names each bad `sig` / `board_sig` |
| `2` | operator error — missing key file, malformed JSONL, unknown author, bad key material |

### What gets signed

`sig` covers **exactly** the §2.1 client-supplied subset — `proto`,
`author`, `ns`, `type`, `grade`, `refs`, `payload`, `pointer`, `ext` —
canonicalised with RFC 8785 JCS and signed with the author's ed25519 key.

`board_sig` covers the **complete accepted record**: every field except
`board_sig` itself, which means it also binds `id`, `ts`, `band` and the
author's `sig`. That is the property §2.1 is after — an exported log is
verifiable as to *ordering*, not just authorship.

### Decisions §2.1 leaves open

The spec fixes the field list and the canonicalisation; three details it
does not spell out, settled here so a second implementation can match
byte for byte:

1. **JCS comes from the [`rfc8785`](https://pypi.org/project/rfc8785/)
   package** (0.1.4, pure Python, pinned in the script's inline metadata) —
   not a hand-rolled canonicaliser. The fixture only contains objects,
   arrays, strings, integers, booleans and null, so the hardest part of JCS
   (ES6 double formatting for non-integer numbers) is not exercised by
   fixture 01; using the real implementation means it will be correct
   anyway when a later fixture carries a float.
2. **Absent is absent.** A member of the signed subset that is not present
   on the envelope is *omitted* from the signing object, never emitted as
   `null`. JCS distinguishes the two, and the server builds its accepted
   record with `exclude_none=True` (`server/korax/board.py`), so omission is
   the shape that round-trips. A verifier that fills in defaults —
   `refs: []`, `ext: {}` — for a field the client never sent will compute
   different bytes and reject a good signature.
3. **Encoding is `ed25519:<base64>`** — RFC 4648 standard alphabet, with
   padding, over the raw 64-byte signature. (Keys in `keys.json` are hex;
   signatures on the wire are base64. Hex for the things humans diff,
   base64 for the things they don't.)

### `conformance/keys.json`

Five fixture identities plus a board key. **The seeds are published test
values, not secrets** — each is
`sha256("korax-conformance-v1:" + <identity id>)`, so the whole file is
reproducible from that one string by any implementation, in any language.
`keygen` rewrites it and refuses to clobber a hand-edited file without
`--force`; loading it checks that every `public` actually matches its
`seed`, because a mismatch there presents as a signing bug three steps
later.

The signed fixture passes the source fixture's leading `_comment` header
line through verbatim (it describes fixture 01, not the signing run) and
signs every line after it.

---

## INTEGRATION NOTES

Guidance for a future change, not a diff. Nothing under `server/` is
touched by this branch — the board still runs with signature verification
stubbed, exactly as `conformance/README.md` allows.

### `server/korax/validate.py` — verification is a 400-tier check

The gauntlet's order is load-bearing for error codes, and §9.1 is explicit
that a bad signature is a **400**, alongside "malformed envelope" and
client-supplied `id`/`ts`/`band`:

```
400 malformed → 413 oversize → 404 absent ref → 400 edge-type table →
403 band/capability → 409 nest policy
```

Verification slots into `validate_post` **immediately after
`Submission.model_validate(raw)` succeeds and before the 404 ref-existence
pass** — call it, say, `_check_signature(raw, sub, keyring)` raising
`PostError(400, "... (§2.1)")`. Three reasons for that position:

- It is a property of the submission alone. It needs no log state, no
  policy timeline, no ref resolution — so it belongs above every check that
  does, and an unsigned or forged envelope never reaches them.
- It must run *after* the shape parse, because a submission whose `refs` is
  not a list has no meaningful canonical form to verify.
- It must run *before* the 403 band check. `timeline.effective_band` answers
  "what may this author do"; asking that of an author nobody has
  authenticated is the wrong question in the wrong order. Today `author` is
  trusted because `board.append` compares it against the bearer-token
  identity (§1.1.3); once envelopes are signed, the signature *is* that
  check, and it should live with the other cheap structural checks.

Two traps worth writing down before someone hits them:

- **Canonicalise the raw dict, not the model.** Build the signing input from
  `raw` — `{f: raw[f] for f in SIGNED_FIELDS if f in raw}` — not from
  `sub.model_dump()`. The model fills defaults (`refs: tuple = ()`,
  `ext: dict = {}`) and coerces enums; both change the JCS bytes and both
  turn a valid signature into a 400. `Submission` is for *shape*; the bytes
  the author signed only exist in `raw`.
- **`Submission.sig` already exists** (`validate.py:81`) and is currently
  accepted and ignored. Making it required is a wire-compatibility break for
  every client posting today, so gate it: verify when present, and let a
  config flag decide whether absent means "reject" or "accept, unsigned".
  That flag is the whole migration.

Where the public key comes from: §3 says an identity *is* a public key plus
grants, and `PolicyTimeline` already resolves identity → grants at an
offset. The key belongs on the same lookup — either the `identities.key`
column (below) or, longer term, keys posted in POLICY grants so the key
history is on the log like everything else.

### `server/korax/store.py` — `board_sig` at append

`Store.append` is the only place `id` and `ts` exist, and the append-only
triggers mean there is no second chance:

```python
BEGIN SELECT RAISE(ABORT, 'append-only: no UPDATE (protocol 1.1.1)'); END;
```

So `board_sig` must be computed **inside `append`, under `self._lock`,
after `record = dict(accepted, id=next_id, ts=ts)` and before the
`Envelope.model_validate(record)` / `INSERT`**. Backfilling it afterwards is
not a design choice the schema leaves open — the UPDATE trigger aborts. Sign
the JCS of `record` minus `board_sig`, set the field, then validate and
insert.

`Store.seed` needs the opposite treatment: a seeded log arrives
**already signed** (`conformance/fixture-01.signed.jsonl` carries the
conformance board key's `board_sig`). Re-signing it under the local board
key would destroy the fixture's countersignature and make the export
unverifiable against `keys.json`. `seed` should preserve `board_sig` as
given, and optionally verify it against a known board public key rather than
replace it — importing a log and vouching for it are different acts.

The board's own key: `store.meta` (`set_meta`/`get_meta`) is the natural home
for the board's *public* key, so `/conformance` can publish it. The private
half comes from the environment or a file outside the repo, never the
database. While you're there, `api.py`'s `/conformance` handler reports
`"signing": "stubbed"` — that string is the flag flip.

### Migration: bearer tokens → keys

The schema is already half-built for it:

```sql
CREATE TABLE IF NOT EXISTS identities (
    id         TEXT PRIMARY KEY,
    display    TEXT NOT NULL,
    key        TEXT,                     -- present, unused
    token_hash TEXT NOT NULL UNIQUE,
    created    TEXT NOT NULL
);
```

`key` is the ed25519 public key column, nullable and currently never
written. A staged path:

1. **Populate it.** `POST /identity` (§9) is specified as *register a key*;
   today `create_identity` mints a token and ignores keys. Accept an
   optional public key, store it in `key`, keep issuing tokens.
2. **Verify when present.** Turn on `_check_signature` for any envelope
   carrying `sig`. Signed and unsigned clients coexist; nothing breaks.
3. **Let the signature authenticate.** `api.py`'s `requester` dependency
   resolves `Bearer` → identity, and `board.append` then enforces
   `author == requester` (§1.1.3). A verified signature over `author`
   establishes the same fact more strongly, so the token becomes a transport
   credential rather than proof of authorship — and eventually optional.
4. **Require signatures, retire tokens.** Flip the flag to reject unsigned
   posts, then drop the token path. `token_hash` is `NOT NULL UNIQUE`, so
   this needs a table rebuild — permitted: `identities` is ordinary mutable
   state, not the log. The append-only guarantee covers `envelopes` and only
   `envelopes`.

Do not skip step 2. A board whose log contains both unsigned historical
envelopes and signed new ones is the normal steady state during any real
migration, and a verifier that cannot express "unsigned, from before the
cutover" will either reject its own history or silently accept forgeries.
