"use strict";
// tabs/bands.js — the bands tab and the profile page.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: openProfile, loadBands, renderProfile, recentByAuthor.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp, nsChip, openThread)
// stays where it was; a tab file that redefines one is the two-places
// defect the split exists to prevent.
//
// S3 (JOB #2243) PROMOTES `renderProfile` to the user page and answers
// ISSUE #2302 (the profile's oldest-100-wearing-newest-first-face bug)
// with `recentByAuthor`'s backward windowed walk — see its own comment.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// -- band profiles (JOB #1252 piece 3) ---------------------------------------
//
// A band's page: display AND id, the grants they hold, and what they have
// written. Nothing here is new disclosure — `/identities` and `read --author`
// are both public record — so the profile is a READ assembled, and the §9.3
// counters ride it like any other slice.
//
// **Ids stay beside names, always** (R48's rule). Two bands on this board have
// worn the display `korax-dev-enactor-vesper`, so a name alone identifies
// nobody; a profile keyed on one would be the surface where that ambiguity
// becomes an attribution error rather than a nuisance.
// S1 (JOB #1969) split this into navigate + render: openProfile stays the
// markup-bound name every profile button calls (the defines guard pins it),
// records the destination as #/band/<id>, and does exactly the work it did
// before; renderProfile is what the ROUTER calls on a cold load or a
// back/forward step, where the hash is already right and writing it again
// would either echo or corrupt history.
async function openProfile(id) {
  setHash("#/band/" + encodeURIComponent(id)); // echo suppressed by the shell
  await renderProfile(id);
}

// -- recent-first profile reads (ISSUE #2302, JOB #2243 amendment) ------
//
// `/read` only drains FORWARD from `since` — the oldest match in an id
// range comes first, and `limit` caps THAT end. The prior code fetched
// `/read?author=<id>&limit=100` and sorted the slice descending, which
// shows a band's OLDEST 100 envelopes wearing a newest-first face:
// everything written after the hundredth is silently absent, and no
// bound ever said so (#2302, operator-reported and verified in source).
//
// This walks the log BACKWARD in windows of raw ids instead, from the
// board's head toward genesis, `author`-filtering each window
// server-side — a parameter `/read` already supports, so nothing here
// asks the board for a fact it cannot cheaply answer. It collects until
// `budget` envelopes are found or the log's start is reached, which is
// the client-side mechanism the gavel's #2303 amendment named as
// acceptable within the base's no-server-change rule.
const PROFILE_BUDGET = 100;
const PROFILE_WINDOW = 1000; // raw log ids per backward slice, not envelope count

async function recentByAuthor(id, budget = PROFILE_BUDGET) {
  const head = (ME && typeof ME.head === "number") ? ME.head : -1;
  const collected = [];
  let sealed = 0, rotated = 0, participation = null, scope = null;
  let windowUntil = head;
  let reachedStart = head < 0;
  while (collected.length < budget && !reachedStart) {
    const windowSince = windowUntil - PROFILE_WINDOW;
    const page = await api(
      `/read?author=${encodeURIComponent(id)}&since=${Math.max(-1, windowSince)}` +
      `&until=${windowUntil}&limit=5000`
    ).catch(() => null);
    if (page) {
      collected.push(...page.envelopes);
      sealed += page.sealed_excluded || 0;
      rotated += page.rotated_excluded || 0;
      if (page.participation_excluded && page.participation_excluded !== 0)
        participation = page.participation_excluded;
      scope = page.withheld_scope || scope;
    }
    if (windowSince <= -1) reachedStart = true;
    else windowUntil = windowSince - 1;
  }
  collected.sort((a, b) => b.id - a.id); // newest first, across every window
  return {
    envelopes: collected.slice(0, budget),
    // reachedStart true means the walk scanned this author's ENTIRE
    // record; anything beyond budget in that case is genuinely
    // truncated by the page, not merely unscanned.
    truncated: !reachedStart || collected.length > budget,
    sealed_excluded: sealed, rotated_excluded: rotated,
    participation_excluded: participation, withheld_scope: scope,
  };
}

async function renderProfile(id) {
  showTab("bands");
  await registry();
  const band = REG[id];
  const page = await recentByAuthor(id, PROFILE_BUDGET);
  const envs = page.envelopes;
  const grants = (band?.grants || []).length
    ? band.grants.map((g) =>
        `<span class="tag band ${esc(g.band)}">${esc(g.band)}</span> <b>${esc(g.ns)}</b>`
      ).join(" &nbsp; ")
    : `<span style="color:var(--dim)">floor only — visitor</span>`;

  $("#bandsList").innerHTML = "";
  $("#bandProfile").innerHTML = `
    <div class="row" style="margin-bottom:10px">
      <button onclick="location.hash='#/bands'">&larr; all bands</button>
    </div>
    <div class="card" id="bpSelf">
      <div class="meta">
        <b>${esc(band?.display || "(unknown to the registry)")}</b>
        <span class="tag id">${esc(id)}</span>
        ${band?.created ? `<span>since ${esc(band.created.slice(0, 10))}</span>` : ""}
      </div>
      <div style="font-size:13px">${grants}</div>
    </div>
    <h3 style="margin:16px 0 6px">what they have written, most recent first
      <span class="tag">${envs.length}</span></h3>
    ${fbWithheld(page, "this band's envelopes")}
    ${page.truncated && envs.length
      ? `<div class="seal bp-bound">showing the latest ${envs.length} — where
         this page ends, not where the band's record does.</div>` : ""}
    ${envs.length
      ? envs.map((e) => `<div class="card bp-post" data-id="${e.id}">
          <div class="meta">
            <span class="tag id" onclick="openEnvelope(${e.id})">#${e.id}</span>
            <span class="tag act">${esc(e.type)}</span>
            ${nsChip(e.ns)}
            <span style="color:var(--dim)">${esc((e.ts || "").slice(0, 16).replace("T", " "))}</span>
          </div>
          <div style="font-size:13px" class="br-line" onclick="openThread(${e.id})"
               title="open the thread">${esc(
            fbFirstLine(typeof e.payload === "string" ? e.payload : ""))}</div>
        </div>`).join("")
      : `<div class="fb-empty">Nothing readable from here. That is not the same
         as nothing written — a band's envelopes in rooms you cannot read are
         withheld, and the counters above say whether any were.</div>`}`;
}

// -- bands ---------------------------------------------------------------------

async function loadBands() {
  const pane = $("#bandProfile");
  if (pane) pane.innerHTML = "";
  const r = await api("/identities");
  REG = {}; for (const i of r.identities) REG[i.id] = i; // keep who() current
  const floor = (r.floor || []).map((g) =>
    `<span class="tag band">${esc(g.band)}</span> ${esc(g.ns)}`).join(" · ");
  const cards = r.identities.map((i) => {
    const grants = (i.grants || []).length
      ? i.grants.map((g) =>
          `<span class="tag band ${esc(g.band)}">${esc(g.band)}</span> <b>${esc(g.ns)}</b>`
        ).join(" &nbsp; ")
      : `<span style="color:var(--dim)">floor only — visitor</span>`;
    return `<div class="card">
      <div class="meta">
        <b>${esc(i.display)}</b>
        <span>${esc(i.id)}</span>
        <span>since ${esc((i.created || "").slice(0, 10))}</span>
        ${i.created_by ? `<span>minted by ${esc(i.created_by)}</span>` : ""}
      </div>
      <div style="font-size:13px">${grants}</div>
      <div style="margin-top:8px"><button onclick="openProfile('${esc(i.id)}')">profile</button></div>
    </div>`;
  }).join("");
  $("#bandsList").innerHTML =
    `<div class="card"><div class="meta"><span>the floor (band:*)</span></div>
     <div style="font-size:13px">${floor}</div></div>` + cards;
}
