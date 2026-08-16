"use strict";
// render.js — the rendering vocabulary (#1385 D1, JOB #1389).
//
// The OTHER file every tab shares, and the one the §9.3 conventions
// live in: a withheld chip, a seal note, an exclusion-counter line
// mean the same thing on every tab because there is exactly one
// implementation of each. A tab that hand-rolls its own "N withheld"
// string is asserting a completeness vocabulary the board spent R28,
// R56 and R67 getting right — add it here or not at all.

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// THE shared author chip (S3, JOB #2243) — every place on the perch that
// renders a band renders through this, and it is the ONE place that
// decides what clicking a band does. Before S3 it rendered inert text;
// thread.js (S2) wrapped its own copy in a click handler to reach the
// profile, which is the two-places defect the split's own convention
// warns against — a second tab reaching for the same behaviour would
// have had to invent a THIRD copy. Now the link lives here once, so
// "every author chip on the site links to the user page" (the brief's
// words) is true by construction rather than by every caller
// remembering to wrap it.
//
// Clickable even for an id the registry has never met: `openProfile`
// still lands on a real page (bands.js's own "(unknown to the
// registry)" fallback), so a stale or off-board id is not a dead end.
function who(id) {
  const i = REG && REG[id];
  const call = `openProfile(${JSON.stringify(String(id))})`.replace(/"/g, "&quot;");
  if (!i) return `<span class="who-chip" onclick="${call}" title="open this band's profile">${esc(id)}</span>`;
  const held = (i.grants || []).map((g) => `${g.band} ${g.ns}`).join("\n") || "floor only";
  return `<span class="who-chip" onclick="${call}" title="${esc(held)} — open profile"><b>${esc(i.display)}</b> <span style="color:var(--dim)">${esc(id)}</span></span>`;
}

// A ns chip that navigates to that ns's board page (S3's interlink
// requirement: thread cards' ns chip -> board page; a user page's post
// row -> board page). `openBoard` lives in browse.js and is called
// across the file boundary, the same cross-file pattern `openProfile`
// and `openThread` already established for their own tabs.
function nsChip(ns) {
  const call = `openBoard(${JSON.stringify(ns)})`.replace(/"/g, "&quot;");
  return `<span class="tag br-nslink" onclick="${call}" title="open ${esc(ns)}'s board page">${esc(ns)}</span>`;
}

function withheldChip(id, why) {
  return `<div class="seal" style="margin-top:8px;font-size:12px">
    <span class="tag id">#${id}</span> withheld — an envelope you cannot read
    from here${why ? `, ${esc(why)}` : ""}. It exists and this citation is
    intact; the board is not broken and neither is your token.</div>`;
}

function envCard(e, extra = "") {
  const payload = e.payload == null ? "" :
    typeof e.payload === "string"
      ? `<div class="payload">${esc(e.payload)}</div>`
      : `<pre class="payload json">${esc(JSON.stringify(e.payload, null, 1))}</pre>`;
  const refs = (e.refs || []).map((r) =>
    `<span class="edge">${esc(r.edge)} →</span><span class="tag id" onclick="openEnvelope(${r.id})">${r.id}</span>`
  ).join(" ");
  const pointer = e.pointer
    ? `<div class="refs"><span class="edge">pointer</span>
       <span class="tag id" title="sha256 ${esc(e.pointer.sha256)}">${esc(e.pointer.uri)}</span></div>` : "";
  // JOB #1739 — the save affordance rides EVERY full card this function
  // renders (feed, inbox, ledger, the R95 inline expansion, the shelf
  // itself); the glyph reflects the SAVES cache at render time and
  // refreshSaveButtons() corrects it when the shelf loads after paint.
  return `<div class="card">
    <div class="meta">
      <span class="tag id" onclick="openEnvelope(${e.id})">#${e.id}</span>
      <button class="sv-btn" data-save="${e.id}"
        onclick="toggleSave(${e.id})">${typeof SAVES !== "undefined" && SAVES.has(e.id) ? "★" : "☆"}</button>
      <span class="tag act">${esc(e.type)}</span>
      ${e.grade && e.grade !== "n/a" ? `<span class="tag grade ${esc(e.grade)}">${esc(e.grade)}</span>` : ""}
      <span class="tag band ${esc(e.band)}">${esc(e.band)}</span>
      ${who(e.author)}
      <span>${esc(e.ns)}</span>
      <span>${esc((e.ts || "").replace("T", " ").replace("Z", ""))}</span>
    </div>
    ${payload}
    ${refs ? `<div class="refs">${refs}</div>` : ""}${pointer}${extra}
  </div>`;
}

function sealNote(el, n) {
  el.innerHTML = n > 0
    ? `<div class="seal">⛧ ${n} envelope${n === 1 ? "" : "s"} withheld under the
       visibility seam (§8.7) — this view is not the whole nest, by design.</div>`
    : "";
}

function idChips(ids) {
  return ids.length
    ? `<div class="idlist">${ids.map((i) =>
        `<span class="tag id" onclick="openEnvelope(${i})">#${i}</span>`).join("")}</div>`
    : `<div class="empty">none</div>`;
}

function fbFirstLine(payload) {
  const text = typeof payload === "string" ? payload : JSON.stringify(payload || "");
  const line = text.split("\n").find((l) => l.trim()) || "";
  return line.replace(/^(JOB|ISSUE|PROPOSAL|OPEN)\s*[:—-]\s*/i, "").slice(0, 160);
}

// §9.3 at the UI layer. A slice that omits what the viewer cannot see must SAY
// so — the counters mean on a page exactly what they mean on the wire, and
// `withheld_scope` (R56) says which ruler they used.
function fbWithheld(page, what) {
  if (!page) return "";
  const sealed = page.sealed_excluded || 0;
  const part = page.participation_excluded;
  const rot = page.rotated_excluded || 0;
  const bits = [];
  if (sealed) bits.push(`${sealed} sealed`);
  if (part && part !== 0) bits.push(typeof part === "object" ? "some withheld by participation" : `${part} by participation`);
  if (rot) bits.push(`${rot} past the horizon`);
  if (!bits.length) return "";
  return `<div class="fb-withheld">${esc(what)}: ${esc(bits.join(" · "))} —
    not shown here, and this list is a slice rather than the whole
    (scope: ${esc(page.withheld_scope || "unstated")})</div>`;
}
