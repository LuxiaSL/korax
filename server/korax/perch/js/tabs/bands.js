"use strict";
// tabs/bands.js — the bands tab and the profile page.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: openProfile, loadBands.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
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

async function renderProfile(id) {
  showTab("bands");
  await registry();
  const band = REG[id];
  const page = await api(`/read?author=${encodeURIComponent(id)}&limit=100`)
    .catch(() => null);
  const envs = (page?.envelopes || []).slice().sort((a, b) => b.id - a.id);
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
    <div class="card">
      <div class="meta">
        <b>${esc(band?.display || "(unknown to the registry)")}</b>
        <span class="tag id">${esc(id)}</span>
        ${band?.created ? `<span>since ${esc(band.created.slice(0, 10))}</span>` : ""}
      </div>
      <div style="font-size:13px">${grants}</div>
    </div>
    <h3 style="margin:16px 0 6px">what they have written
      <span class="tag">${envs.length}</span></h3>
    ${fbWithheld(page, "this band's envelopes")}
    ${envs.length
      ? envs.map((e) => `<div class="card">
          <div class="meta">
            <span class="tag id" onclick="openEnvelope(${e.id})">#${e.id}</span>
            <span class="tag act">${esc(e.type)}</span>
            <span class="tag">${esc(e.ns)}</span>
            <span style="color:var(--dim)">${esc((e.ts || "").slice(0, 16).replace("T", " "))}</span>
          </div>
          <div style="font-size:13px">${esc(
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
