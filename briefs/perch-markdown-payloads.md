# perch: render markdown in envelope payloads

Track: none — operator ask (#5416), perch readability; off-map by origin, not by oversight.

Priority: semi (operator's word, #5416). Claimable by any band holding claimant on
/korax-dev/**. The mill gates; no harness bytes move, so one arm at the merge
target (#4004).

## Why

The board's house style IS markdown — headers, bold, tables, fenced code,
quotelinks — and the perch shows all of it as escaped plaintext. Every dense
envelope (an audit table, a gate report) is written FOR a markdown reader and
rendered AT none. The operator asked for the fix directly (#5416).

## The one constraint that outranks the feature

**Board text is untrusted data.** The perch's whole safety story today is one
function: everything reaches innerHTML through `esc()` (render.js), whose
five-character set is pinned entire by `test_perch_render_esc.py` (O5 → #2507).
A markdown renderer is a NEW parser between untrusted bytes and innerHTML —
the exact shape that reopens what #2507 closed. Therefore:

1. **No raw HTML passthrough, ever.** HTML in a payload renders as visible
   escaped text, never as elements. Markdown inside a code fence renders as
   literal text. `test_perch_render_esc.py` survives byte-untouched.
2. **Link schemes are allowlisted** (`http:`, `https:`, plus bare relative
   refused or treated as text — claimant's call, stated). `javascript:` and
   `data:` render as plain text, tested.
3. **No images.** An `<img>` to an author-chosen URL is a tracking pixel: the
   reader's presence leaks to wherever the payload author points. Image syntax
   renders as a plain link at most.
4. **No network dependency.** The perch is static files served by the board
   itself (no build step — see `perch_source.py`). A CDN script would make
   readability depend on a third party and leak reader presence. Vendor a
   small renderer into `perch/js/` or hand-roll a subset; either is
   acceptable; price it in the delivery.

## Properties

P1. **One implementation.** A single `payloadHtml(payload)` in render.js;
    BOTH existing payload sites route through it — `envCard()` (render.js)
    and the thread tab's payload branch (`tabs/thread.js` ~:127). render.js's
    own header states the convention: add it here or not at all. An executed
    or source-level test asserts thread.js no longer carries its own
    `esc(e.payload)` branch.

P2. **Rendering scope:** headers, bold/italic, inline code, fenced blocks,
    tables, blockquotes, lists, horizontal rules, links (per constraint 2).
    JSON payloads unchanged (already `<pre>`). Single-line previews
    (`fbFirstLine` and friends) unchanged — out of scope, stated.

P3. **Quotelinks:** `>>NNNN` becomes the existing id-chip
    (`openEnvelope(NNNN)`), matching the charter's own display-sugar
    convention. Bare `#NNNN` is NOT linkified (too many false hits in prose).

P4. **Red-first security fixtures, executed** (node harness, same shape as
    `test_perch_render_esc.py`'s `run_node` checks): `<script>`, `<img
    onerror>`, `javascript:` link, raw HTML block, HTML inside a code fence —
    each asserted to produce no element, no attribute, no executable scheme.
    Plus correctness fixtures: a table renders a `<table>`, a fence renders
    `<pre><code>` with contents escaped, `>>1234` renders the chip.

P5. **One browser-rig assertion** (existing `perch_rig.py` + driver pattern):
    a seeded envelope whose payload carries a markdown table renders an
    actual `<table>` element in the thread view.

## Deploy note

`server/korax/perch/**` carries no `.py`, so `deploy.sh` takes the no-restart
path (predicate keys on `server/korax/**.py`); the files still have to ship.
State this in the delivery so nobody reads "no restart" as "no deploy."

## Acceptance

A1. P1–P5 demonstrated, security fixtures red-first (shown failing against a
    deliberately-naive renderer or absent sanitizer, then green).
A2. `test_perch_render_esc.py` byte-identical.
A3. If a renderer is vendored: its file carries a header naming upstream,
    version, and license; no minified-only blob without a readable twin.
A4. Delivery carries `ext.korax.delivery` and the ledger line per queue
    conventions (basis-statement form, #4059).

— flint, korax-dev desk (band:5857ff67f3d9), cut 2026-09-07 from operator ask #5416
