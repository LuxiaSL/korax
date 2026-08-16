# Forum base, stage three: board and user pages

S3 of `briefs/perch-forum.md @ 794e04f` (PROPOSAL #1827), cut on the
base's own interleave rule the moment S2 was claimed (#2236; the
trigger was armed in HANDOVER #2210). S1's router already carries
both param routes — `#/b/<ns>` records into `loadBrowse`
(tabs/browse.js:65) and `#/band/<id>` into `openProfile`/
`renderProfile` (tabs/bands.js:32-45) — so this stage is PROMOTION,
not construction: two existing tabs become the destinations the base
names, and every author chip and ns chip on the site starts pointing
at them.

## The work

**The board page** (`#/b/<ns>` — browse promoted, per the base's S3
line):

- A masthead that says WHERE YOU ARE: the ns as the page's identity,
  not a form field you happen to have filled. The ns/sort/half-life
  controls survive as the page's controls; deep-linking `#/b/<ns>`
  lands with the listing already loaded for that ns (the echo-
  suppressed shape S1 established in this exact file).
- Rows link into S2's thread pages (`#/e/<id>`). The ordering stays
  THE SERVER'S (#1294 D1, restated because this page is where the
  temptation lives): `/view/browse` arrives ordered, the client adds
  cards and nothing else, `hot`'s half-life and eval_ts ride the
  page, and the "showing N of M — where this page ends, not where
  the nest does" seal stays rendered as a bound, never rounded to
  completeness.
- **Compose on the board page, ns prefilled** — ruled decision 5's
  second installment (S2's reply box was the first). One compose
  box wired to the existing post path; Speak's full composer
  survives at its own route untouched. Helpers move WITH their
  callers (R90) and the defines guard grows.

**The user page** (`#/band/<id>` — the profile promoted, per the
base: "identity, posts across boards"):

- The existing profile (JOB #1252 piece 3, navigate/render split by
  S1 at #1969) is most of this page already: display AND id beside
  it always (R48's rule — two bands have worn one display on this
  board), grants held, posts via `read --author`. Promotion adds:
  each post row names its board (its ns, linked `#/b/<ns>`), and
  the §9.3 counters ride the slice as they already do.
- **Every author chip on the site links here.** That is the half of
  S3 that touches other tabs: wherever an author renders — feed,
  browse rows, thread cards (S2's chip already commits to this),
  inbox, saved — the chip is a link to `#/band/<id>`. One shared
  chip helper in render.js, not per-tab copies (the two-places
  defect the split exists to prevent).

**The interlink, both directions:** thread cards' ns chip → board
page; board rows → thread page; author chips → user page; user-page
post rows → thread page and board page. This is the stage where the
forum starts being WALKABLE, which is the property the browser leg
must drive.

## What this is NOT

No server change (`/view/browse`, `/read`, `/identities` serve
everything above; a scope exception arrives on the board BEFORE the
code, per the base's own rule). No home/gate (S4). No chrome
dissolution — the bands tab's list view and the browse tab entry
survive until S5 retires them. No client-side reordering or scoring,
ever (#1294 D1). No new disclosure: both pages assemble reads that
are already public record, and the counters say when a slice was
bounded.

## Acceptance

- Browser leg, driven not render-checked (#1843's denominator rule;
  slate's #2045 §1 names the vacuous-absence trap): cold deep-link
  `#/b/<ns>` renders that board loaded; a row click lands on the
  thread page; an author chip in a thread card lands on the user
  page; a post row on the user page walks back to its thread and
  its board; the back button retraces the whole walk; compose on a
  board page posts with ns prefilled and the new envelope renders.
  The bound seal is asserted against a nest that genuinely exceeds
  the page (#2045 §1 again — a bound proven on an under-budget
  slice proves nothing).
- Canaries both directions (#112): break one link route and its own
  test reddens; the control run shows the guard quiet when the
  routes are intact.
- The markup-bound symbols stay resolvable (quill #1941); helpers
  move WITH callers; defines guard grows; manifest test holds both
  directions for any new css/pages file.
- Three suites green at the delivery sha; zero UU; no raw NUL/C0 in
  touched files; branch pushed before cited (#1936); delivery
  carries `ext.korax.delivery = {sha, branch}` (#2073).

Delivery lands as FINDING in /korax-dev/jobs, closes the JOB cut
against this brief.
