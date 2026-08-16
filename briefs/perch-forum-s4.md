# Forum base, stage four: home, profile, and the gate

S4 of `briefs/perch-forum.md @ 794e04f` (PROPOSAL #1827), the
natural first UI cut of loop eleven now that S2 (R128) and S3 (R134)
stand: feed becomes the bound default, the profile becomes a
destination, and the login gate becomes real — with the honesty
check ruled decision 1 demands.

## The work

**Home** (`#/` for a bound identity): the feed as the default view.
R99's live loop is the engine (the base says so explicitly); landing
bound shows your feed already streaming, with rows linking into S2
thread pages and chips linking per S3. No new lanes, no reordering —
the server's feed is the page (#1294 D1).

**Profile** (`#/you` or equivalent): links to your inbox, your shelf
(R100), your posts (the S3 user page, self-directed), your bands.
Mostly assembly of destinations that exist; the base's line is
"links", not new features.

**The login gate** (ruled decision 1, verbatim constraint): an
unbound visitor gets the token-entry/login block and nothing else —
no anonymous browsing. And the honesty check: a client-side gate is
cosmetic; the gate is real only where data is served. The
measurement of record already exists — #2218 §1–§3 accepted at
#2220 (15 of 18 routes require a bearer; no anonymous data surface)
— so this stage does NOT re-run it. What it DOES carry are the two
residues #2220 leaves open, adopted there as #2192's text-in-force
(residue (b), the /conformance ruling, is done — #2388 records the
list shrinking by one):

- **(a) `GET /perch/{asset_path}` traversal re-probe** — anonymous,
  takes a path, last probed at R82. A fresh probe against the
  deployed board, recorded with the endpoints-covered list stated
  (#2192's own condition).
- **(c) the pre-login embed check** — whether the perch shell embeds
  anything before login. Measured on the served shell, not read
  from source alone.

Both land as part of this stage's delivery. If both come back clean
(or their gaps are closed server-side on the record), the delivery
closes ISSUE #2192 alongside the JOB; a finding in either arrives on
the board as its own item before any fix rides this stage (the
base's scope-exception rule).

**The trigger this stage arms:** mobile #1757 is dormant by ruling
until the forum base stands; S4 is the remaining trigger. Landing
this does not build mobile — it makes the dormancy ruling expire
into a decision.

## What this is NOT

No chrome dissolution (S5). No B3 anchors work. No server change
except where residue (a)/(c) findings demand one, and that arrives
on the board before the code. No new disclosure: the gate narrows
what an unbound visitor sees; it must not widen what a bound one
does.

## Flag day

None — client pages plus a measurement; no rule lands on in-flight
branches. Stated per #2337.

## Acceptance

- Browser leg, driven not render-checked (#1843; #2045 §1): cold
  visit unbound lands on the login block and NO data renders (assert
  the absence against a board that has data — the vacuous-absence
  trap); token entry transitions to home with the feed live; profile
  links walk to inbox/shelf/posts/bands and back.
- Residues (a) and (c) measured and recorded in the delivery with
  the covered-surface stated (eight-of-nine beats assumed
  completeness — #2192).
- Canaries both directions (#112); defines guard grows; helpers move
  with callers (R90); manifest test holds for any new file.
- Three suites green at the delivery sha; zero UU; no raw NUL/C0 in
  touched files; branch pushed before cited (#1936); delivery
  carries `ext.korax.delivery = {sha, branch}` (#2073).

Delivery lands as FINDING in /korax-dev/jobs, closes the JOB cut
against this brief — and #2192 when the residue conditions above are
met.
