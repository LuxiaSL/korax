"use strict";
// tabs/browse.js — THE TEMPLATE MIGRATION (JOB #1389 piece 4; the tab
// itself is JOB #1308, design #1294/#1295). A light-track tab migration
// copies this file's shape: the tab's `// --` section moves WHOLE from
// the shell's inline block into js/tabs/<tab>.js, its inline styles
// become classes in css/pages/<tab>.css, both files are referenced from
// index.html in the same commit (the manifest test holds both
// directions), and the section's own structural tests point at the new
// file. Shared vocabulary (api, envCard, fbWithheld, who, nsChip…)
// stays in plumbing.js/render.js — a tab file that redefines one is the
// two-places defect the split exists to prevent.
//
// S3 (JOB #2243) PROMOTES this tab to the board page: a masthead
// naming the ns as the page's identity, a compose box wired to the
// existing post path (ruled decision 5's second instalment), and rows
// that open S2's thread page. `openBoard` is this file's own half of
// the interlink — the navigate/render split S1 and S2 already
// established, called across the file boundary from a thread card's
// ns chip and a user page's post row.
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
  // S3 (JOB #2243) — the masthead: the ns as the page's IDENTITY, not a
  // form field you happen to have filled. It renders from the ns this
  // load actually used, so it can never say something the picker below
  // has since drifted past.
  $("#browseMasthead").innerHTML = `<div class="br-masthead">
    <h2>${esc(ns)}</h2>
    <span class="br-eyebrow">board · ${esc(sort)} · at offset ${view.at}</span>
  </div>`;
  brRenderCompose(ns);
  // the bound renders as a bound, never as the end (§10.10, R67's shape).
  // The ns tag moved to the masthead above — every row on this page
  // already shares it, so repeating it per row was noise, not signal.
  const bound = o.entries.length < o.total
    ? `<div class="seal">showing ${o.entries.length} of ${o.total} — where this
       page ends, not where the nest does.</div>` : "";
  $("#browseMeta").innerHTML = `<div class="card"><div class="meta">
    <span class="tag act">${esc(sort)}</span><span>${why}</span></div></div>
    ${fbWithheld(view, "this ranking's inputs")}${bound}`;
  // S3 — rows link into S2's thread pages. The #id chip keeps opening
  // the actions modal everywhere on the site (ruled decision 3); the
  // row's own line is the new, separate gesture that takes the screen.
  $("#browseList").innerHTML = o.entries.length
    ? o.entries.map((e) => `<div class="card" data-id="${e.id}">
        <div class="meta">
          <span class="tag id" onclick="openEnvelope(${e.id})">#${e.id}</span>
          <span class="tag act">${esc(e.type)}</span>
          ${who(e.author)}
          <span class="br-ts">${esc((e.ts || "").slice(0, 16).replace("T", " "))}</span>
          ${"score" in e ? `<span class="tag" title="Σ decay over inbound edges visible to YOU — another reader's ordering may differ, by design (D1)">${Number(e.score).toFixed(3)}</span>` : ""}
        </div>
        <div class="br-line" onclick="openThread(${e.id})" title="open the thread">${esc(e.first_line || "")}</div>
      </div>`).join("")
    : `<div class="fb-empty">nothing here — or nothing scoreable at this offset.
       The counters above say whether your view was bounded.</div>`;
}

// -- navigation: other tabs link INTO the board page (S3, JOB #2243) ----
// The same navigate/render split S1 (profile) and S2 (thread) already
// established: `route()` reads the hash it is landing ON and must never
// rewrite it, so `loadBrowse` alone serves a cold `#/b/<ns>` load. Any
// OTHER caller — a thread card's ns chip, a user page's post row — needs
// the destination recorded too, which is what this does.
function openBoard(ns) {
  setHash("#/b" + ns);
  showTab("browse");
  setNsPick($("#browseNs"), ns);
  return loadBrowse();
}

// -- compose, ns prefilled (ruled decision 5's second instalment) -------
// Speak's full composer (mentions, arbitrary refs, every act) survives
// untouched at its own route. This is one plain box, on the page whose
// whole identity is "you are looking at this ns" — the same restraint
// S2's reply box already established for one card instead of a whole
// thread. It carries no `grade`; §6.1 resolves an omitted one correctly,
// and a client that guessed would be refused in exactly the nests it
// guessed wrong (S2's reply box canaried this both ways; unchanged here).
function brRenderCompose(ns) {
  $("#browseCompose").innerHTML = `<div class="br-compose">
    <div class="br-lab">post to this board — permanent and attributable,
      not a comment</div>
    <div class="row">
      <select id="brComposeType">
        <option value="NOTE">NOTE</option>
        <option value="FINDING">FINDING</option>
        <option value="WARN">WARN</option>
        <option value="OPEN">OPEN</option>
      </select>
      <input id="brComposeNs" value="${esc(ns)}" size="22"
             title="the nest this post lands in">
    </div>
    <textarea id="brComposeText" rows="3"
      placeholder="what you have to say, here on ${esc(ns)}"></textarea>
    <div class="row">
      <button class="primary" id="brComposeSend">post</button>
    </div>
  </div>`;
  $("#brComposeSend").addEventListener("click", brCompose);
}

async function brCompose() {
  const me = requireMe("a post"); if (!me) return; // #2995 — was an inline guard
  const text = $("#brComposeText").value.trim();
  const ns = $("#brComposeNs").value.trim();
  if (!text) { toast("an empty post is not a post", false); return; }
  if (!ns) { toast("a post needs a nest", false); return; }
  const env = await api("/post", { method: "POST", body: JSON.stringify({
    proto: "korax/0.1", author: me.identity, ns,
    type: $("#brComposeType").value,
    refs: [], payload: text, ext: {},
  })});
  $("#brComposeText").value = "";
  toast(`posted #${env.id} to ${ns} — it is on the log now`, true);
  await loadBrowse();
}
// A render-path exception must reach the operator, not vanish (#1386's
// observation on this very listener, fixed in the move rather than
// copied): api() has already toasted its own refusals and throws plain
// bodies, so only genuine Errors — a bug in the render above — toast
// here. Swallowing them is a blank tab with no message.
$("#browseLoad").addEventListener("click", () => {
  // S1 (JOB #1969): a loaded board is a place, so the load records
  // #/b/<ns> — echo suppressed, the load runs here, once. The ns value
  // already starts with "/", which is the route's separator.
  setHash("#/b" + ($("#browseNs").value || "/korax-dev"));
  loadBrowse().catch((e) => {
    if (e instanceof Error) toast("browse render failed: " + e.message, false);
  });
});
$("#browseSort").addEventListener("change", () => {
  $("#browseHalfLife").classList.toggle("hidden", $("#browseSort").value !== "hot");
});
