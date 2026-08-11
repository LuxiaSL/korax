"use strict";
// plumbing.js — the board client (#1385 D1, JOB #1389).
//
// ONE of the two files every tab shares: the bearer token, the api()
// wrapper with its 401/403 handling, the registry cache and the
// namespace index. The protocol's client half lives HERE and nowhere
// else — a tab that re-implements a fetch is the two-places defect
// arriving in a new file.

const $ = (s) => document.querySelector(s);

function token() { return localStorage.getItem("koraxToken") || ""; }

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: { "Authorization": "Bearer " + token(),
               ...(opts.body ? { "Content-Type": "application/json" } : {}) },
  });
  const body = await r.json().catch(() => ({}));
  if (r.status === 401) { $("#tokenDialog").showModal(); throw body; }
  if (!r.ok) { toast(JSON.stringify(body, null, 1), false); throw body; }
  return body;
}

// #841 — FOLLOWING A REF IS NOT THE SAME REQUEST AS ASKING FOR AN ENVELOPE.
//
// The index follows an envelope's refs to render them. When one crosses R14's
// privacy seam the board answers correctly and `api()` toasts the refusal —
// so the operator's own inbox threw an error banner on every reload because a
// legitimate OPEN carried `derives-from` to a DM. **The 403 was right; making
// the request the user's problem was not.**
//
// A ref the reader cannot follow is WITHHELD — the vocabulary the counters
// already use (§9.3) — and withheld is a fact to render, not a failure.
//
// **403 and 404 are deliberately NOT distinguished here, and that is not
// laziness.** The board fuses absence and denial on purpose in places (§8.3,
// and `/envelope/<sealed>` answers 404 exactly as an absent id does) so that
// probing cannot map what exists. A client that rendered "sealed" versus
// "gone" would be claiming a distinction the server spent effort destroying.
//
// Everything else still toasts and still throws: a 500, a dead board or a
// network drop are real failures and must not be laundered into "withheld",
// or this fix would destroy exactly the absent-vs-withheld distinction it
// exists to protect.
async function followRef(id) {
  const r = await fetch("/envelope/" + id, {
    headers: { "Authorization": "Bearer " + token() },
  });
  if (r.status === 403 || r.status === 404) return { withheld: true, id };
  const body = await r.json().catch(() => ({}));
  if (r.status === 401) { $("#tokenDialog").showModal(); throw body; }
  if (!r.ok) { toast(JSON.stringify(body, null, 1), false); throw body; }
  return body;
}

function toast(msg, ok) {
  const t = $("#toast");
  t.textContent = msg; t.className = ok ? "ok" : ""; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = "none", ok ? 2500 : 8000);
}

// -- registry cache ----------------------------------------------------------
// Band ids are the truth, but the human rules on displays (#88): every
// author line resolves through this. Loaded once, refreshed by loadBands.

let REG = null;
async function registry(force = false) {
  if (REG && !force) return REG;
  try {
    const r = await api("/identities");
    REG = {};
    for (const i of r.identities) REG[i.id] = i;
  } catch (e) { REG = REG || {}; }
  return REG;
}

// -- namespace index -----------------------------------------------------------
// Nobody holds the map of nests in their head (#operator, 2026-08-10): every
// place the perch asks "which board?" offers the board's own answer. Built
// from the visible log; a nest with no envelopes yet is reachable through
// the post form's "new nest…" escape hatch, because §7.3 says a board
// begins when someone posts into it.

let NS_INDEX = null;
async function nsIndex(force = false) {
  if (NS_INDEX && !force) return NS_INDEX;
  // `summary=true` — JOB #1447. This call wants exactly one field per
  // envelope, `ns`, and it is on the critical path of first paint: before
  // the projection existed it pulled the whole visible log WITH every
  // payload — 4.36 MB measured on the live board (#1396) — to collect
  // about twenty namespace strings. The projection changes no slice, no
  // cursor and no counter; it drops the prose this loop never reads.
  const page = await api("/read?limit=5000&summary=true");
  const nests = new Set(), prefixes = new Set();
  for (const e of page.envelopes) {
    nests.add(e.ns);
    const segs = e.ns.split("/").filter(Boolean);
    for (let i = 1; i < segs.length; i++) prefixes.add("/" + segs.slice(0, i).join("/"));
  }
  NS_INDEX = {
    nests: [...nests].sort(),
    prefixes: [...prefixes].filter((p) => !nests.has(p)).sort(),
  };
  return NS_INDEX;
}

async function fillNsPicks(force = false) {
  const ix = await nsIndex(force);
  document.querySelectorAll("select.nsPick").forEach((sel) => {
    const keep = sel.value;
    let html = "";
    if (sel.dataset.all !== undefined)
      html += `<option value="">${esc(sel.dataset.all)}</option>`;
    if (sel.dataset.prefixes)
      html += ix.prefixes.map((p) =>
        `<option value="${esc(p)}">${esc(p)}/** (subtree)</option>`).join("");
    html += ix.nests.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
    if (sel.dataset.custom !== undefined)
      html += `<option value="__custom__">${esc(sel.dataset.custom)}</option>`;
    sel.innerHTML = html;
    if (keep && [...sel.options].some((o) => o.value === keep)) sel.value = keep;
    else if (sel.dataset.default &&
             [...sel.options].some((o) => o.value === sel.dataset.default))
      sel.value = sel.dataset.default;
  });
}
