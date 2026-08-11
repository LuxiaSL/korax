"use strict";
// tabs/browse.js — THE TEMPLATE MIGRATION (JOB #1389 piece 4; the tab
// itself is JOB #1308, design #1294/#1295). A light-track tab migration
// copies this file's shape: the tab's `// --` section moves WHOLE from
// the shell's inline block into js/tabs/<tab>.js, its inline styles
// become classes in css/pages/<tab>.css, both files are referenced from
// index.html in the same commit (the manifest test holds both
// directions), and the section's own structural tests point at the new
// file. Shared vocabulary (api, envCard, fbWithheld…) stays in
// plumbing.js/render.js — a tab file that redefines one is the
// two-places defect the split exists to prevent.
//
// THE ORDERING IS THE SERVER'S, NEVER RECOMPUTED HERE. A client scoring
// by the edges it can see ranks its own blind spot (#1294 D1: the page
// it reads is already filtered, and the counter says only THAT it was
// bounded, never by how much) — so this tab renders `/view/browse` in
// the order it arrives and adds nothing but cards. `hot` decays against
// eval_ts at the offset — log time is the board's clock, wall clock
// never appears (D3) — and the half-life that shaped the ordering rides
// the page, the same legibility rule `withheld_scope` follows. The
// score chip says whose slice it sums: yours; another reader's page may
// order differently, by design.
async function loadBrowse() {
  const ns = $("#browseNs").value || "/korax-dev";
  const sort = $("#browseSort").value;
  const q = new URLSearchParams({ ns, sort, limit: "100" });
  if (sort === "hot") q.set("half_life", $("#browseHalfLife").value.trim() || "P7D");
  const view = await api("/view/browse?" + q);
  const o = view.output;
  await registry();
  const why = sort === "hot"
    ? `half-life ${esc(o.half_life || "?")} against log time ${esc(o.eval_ts || "(no anchor)")}`
    : sort === "top" ? "undecayed citation sum, all time"
    : "id-descending, unscored";
  // the bound renders as a bound, never as the end (§10.10, R67's shape)
  const bound = o.entries.length < o.total
    ? `<div class="seal">showing ${o.entries.length} of ${o.total} — where this
       page ends, not where the nest does.</div>` : "";
  $("#browseMeta").innerHTML = `<div class="card"><div class="meta">
    <span class="tag">${esc(ns)}</span><span class="tag act">${esc(sort)}</span>
    <span>at offset ${view.at}</span><span>${why}</span></div></div>
    ${fbWithheld(view, "this ranking's inputs")}${bound}`;
  $("#browseList").innerHTML = o.entries.length
    ? o.entries.map((e) => `<div class="card">
        <div class="meta">
          <span class="tag id" onclick="openEnvelope(${e.id})">#${e.id}</span>
          <span class="tag act">${esc(e.type)}</span>
          <span class="tag">${esc(e.ns)}</span>
          ${who(e.author)}
          <span class="br-ts">${esc((e.ts || "").slice(0, 16).replace("T", " "))}</span>
          ${"score" in e ? `<span class="tag" title="Σ decay over inbound edges visible to YOU — another reader's ordering may differ, by design (D1)">${Number(e.score).toFixed(3)}</span>` : ""}
        </div>
        <div class="br-line">${esc(e.first_line || "")}</div>
      </div>`).join("")
    : `<div class="fb-empty">nothing here — or nothing scoreable at this offset.
       The counters above say whether your view was bounded.</div>`;
}
// A render-path exception must reach the operator, not vanish (#1386's
// observation on this very listener, fixed in the move rather than
// copied): api() has already toasted its own refusals and throws plain
// bodies, so only genuine Errors — a bug in the render above — toast
// here. Swallowing them is a blank tab with no message.
$("#browseLoad").addEventListener("click", () => loadBrowse().catch((e) => {
  if (e instanceof Error) toast("browse render failed: " + e.message, false);
}));
$("#browseSort").addEventListener("change", () => {
  $("#browseHalfLife").classList.toggle("hidden", $("#browseSort").value !== "hot");
});
