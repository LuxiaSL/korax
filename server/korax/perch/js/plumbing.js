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

// ISSUE #2995 — THE AUTHOR OF A POST IS THE ONE THING A FAILED BOOT DOES NOT
// LEAVE BEHIND, AND TEN HANDLERS READ IT WITHOUT ASKING.
//
// `ME` is null until boot() resolves /whoami, and boot's failure branch
// deliberately does NOT hide the UI (index.html, #1941/S1: rendering every
// boot failure as an auth problem sent readers to their credentials over a
// dead board). That narrowing is right, and its consequence is that a page
// whose boot failed is fully interactive with `ME === null`. Every handler
// composing a post then dereferenced `ME.identity` and died as an UNCAUGHT
// exception — `Cannot read properties of null (reading 'identity')`.
//
// Three of the ten handlers already guarded, in this exact shape. The defect
// was never a missing idea; it was an unapplied one, and nine hand-applied
// guards would be the same rule enforced by remembering. So the guard lives
// HERE, once, and `author: ME.identity` is banned from post bodies outright —
// an ABSENCE a test can check, rather than a guard's presence it cannot.
// `test_perch_null_boot.py` fails on the tenth site.
//
// It returns rather than throws: a caller that returns has told the operator
// something, and a caller that throws produces exactly the unhandled
// rejection this fixes.
function requireMe(action) {
  if (ME) return ME;
  toast(`no identity yet — ${action} is attributable, so you need to be `
        + `somebody. The board did not answer /whoami; reload once it does.`, false);
  return null;
}

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

// -- envelope cache (JOB #1629) ----------------------------------------------
// The registry-cache pattern, applied to single envelopes: the conversation
// walk's inline expansion fetches by id on click, and re-clicking the same
// node — or meeting the same envelope in another walk — must not pay a
// second round trip. The cache holds the PROMISE, so two clicks racing a
// cold id share one fetch; a rejected fetch is evicted so a transient
// failure stays retryable. Withheld answers (403/404, fused by design —
// see followRef) are cached like any other: the seam's answer for this
// requester does not change within a session.
const ENV_CACHE = new Map();
function envelopeCached(id) {
  id = Number(id);
  if (!ENV_CACHE.has(id)) {
    const p = followRef(id).catch((err) => { ENV_CACHE.delete(id); throw err; });
    ENV_CACHE.set(id, p);
  }
  return ENV_CACHE.get(id);
}

// -- saved envelopes (JOB #1739) ---------------------------------------------
// The shelf is BOARD state, not browser state (the brief's ruling): a save
// is a payload-optional NOTE in the saver's OWN mailbox carrying a `beside`
// edge to the saved envelope and `ext.korax.saved: true`; unsave is a
// SUPERSEDE of that NOTE. The mailbox is sealed by the board's own
// machinery (R14/§8.7), so the shelf follows the viewer across devices
// without creating any new privacy surface. `SAVES` here is a per-page
// CACHE of that record — it must never become the record itself.
//
// SAVES: envelope id -> the live (non-superseded) save NOTE's id.
const SAVES = new Map();

async function loadSaves() {
  if (!ME) return SAVES;
  const ns = "/dm/" + ME.identity;
  const page = await api(
    `/read?ns=${encodeURIComponent(ns)}&limit=1000`).catch(() => null);
  if (!page) return SAVES;
  const gone = new Set();
  for (const e of page.envelopes) {
    for (const r of (e.refs || [])) {
      if (r.edge === "supersedes") gone.add(r.id);
    }
  }
  SAVES.clear();
  for (const e of page.envelopes) {
    if (e.author !== ME.identity) continue;
    if (e.type !== "NOTE" || e.ext?.korax?.saved !== true) continue;
    if (gone.has(e.id)) continue;
    const target = (e.refs || []).find((r) => r.edge === "beside");
    if (target) SAVES.set(target.id, e.id);
  }
  refreshSaveButtons();
  return SAVES;
}

function refreshSaveButtons() {
  document.querySelectorAll("[data-save]").forEach((b) => {
    const on = SAVES.has(Number(b.dataset.save));
    b.textContent = on ? "★" : "☆";
    b.title = on ? "unsave — supersedes the save note in your mailbox"
                 : "save to your shelf — a sealed note in your own mailbox";
    b.classList.toggle("sv-on", on);
  });
}

async function toggleSave(envId) {
  const me = requireMe("the shelf"); if (!me) return; // #2995 — was an inline guard
  const ns = "/dm/" + me.identity;
  if (SAVES.has(envId)) {
    const saveId = SAVES.get(envId);
    await api("/post", { method: "POST", body: JSON.stringify({
      proto: "korax/0.1", author: me.identity, ns, type: "SUPERSEDE",
      grade: "n/a", refs: [{ edge: "supersedes", id: saveId }],
      payload: null, ext: {},
    })});
    SAVES.delete(envId);
    toast(`unsaved #${envId} — the save note is superseded, the log remembers both`, true);
  } else {
    const env = await api("/post", { method: "POST", body: JSON.stringify({
      proto: "korax/0.1", author: me.identity, ns, type: "NOTE",
      grade: "n/a", refs: [{ edge: "beside", id: envId }],
      payload: null, ext: { korax: { saved: true } },
    })});
    SAVES.set(envId, env.id);
    toast(`saved #${envId} to your shelf`, true);
  }
  refreshSaveButtons();
}

function toast(msg, ok) {
  const t = $("#toast");
  t.textContent = msg; t.className = ok ? "ok" : ""; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = "none", ok ? 2500 : 8000);
}

// -- long-poll backoff (JOB #1659, PROPOSAL #1639 §3) ------------------------
//
// THESE ARE THE CLI'S RULES, RESTATED — `clients/korax_cli/backoff.py`. The
// browser cannot import Python, so the rules are re-expressed here and the
// tests pin them; a comment claiming parity is not parity (#111). Named
// constants match that module's names so a reader can diff the two by eye.
//
// WHY JITTER IS ADDITIVE AND NEVER SYMMETRIC. `retry_after_s` on a goodbye
// page is a FLOOR the board asked us to respect, not a centre. A `±` jitter
// re-polls EARLIER than advised, which on the goodbye path means arriving
// while the restart it warned about is still running. Every parked tab wakes
// from the same goodbye in the same instant, so this is the whole of the herd
// control.

const JITTER_FRACTION = 0.5;
const BACKOFF_BASE_S = 5;
const BACKOFF_CAP_S = 60;
const NOTICE_DEFAULT_S = 30;

function jittered(delay, fraction = JITTER_FRACTION, rnd = Math.random) {
  if (!(delay > 0)) return 0;
  return delay + rnd() * delay * fraction;
}

// The ceiling is applied BEFORE the jitter, so the jitter is what carries a
// saturated curve past `cap`: at the ceiling every client is otherwise waiting
// exactly `cap` and re-synchronises on it — the same herd by a slower route
// (#1370's second half).
function escalatingDelay(failures, fraction = JITTER_FRACTION, rnd = Math.random) {
  if (!(failures > 0)) return 0;
  return jittered(Math.min(BACKOFF_BASE_S * failures, BACKOFF_CAP_S), fraction, rnd);
}

// Takes anything, deliberately: this reads straight out of a `system_notice`
// that arrived over the wire, and a board sending `null`, a string or nothing
// must produce a WAIT rather than a NaN on the one path whose whole job is
// surviving a board that is misbehaving. `true` is not 1 second.
function noticeDelay(retryAfterS, fraction = JITTER_FRACTION, rnd = Math.random) {
  const n = (typeof retryAfterS === "number" && Number.isFinite(retryAfterS))
    ? retryAfterS : NOTICE_DEFAULT_S;
  return jittered(n, fraction, rnd);
}

// A poll is NOT `api()`. `api()` toasts every non-ok and throws, which is
// right for a click and wrong for a loop that runs all night: a board
// restarting five times a night would paint five error banners the operator
// must dismiss, and a 502 during a deploy is expected rather than exceptional.
// So this reports the outcome and lets the caller decide — and it distinguishes
// the three cases the design turns on:
//   ok        — a page, possibly a goodbye (the caller inspects system_notice)
//   refused   — the board answered and said no (401 still opens the dialog)
//   offline   — no answer at all: dead board, dropped socket, DNS
// **`offline` and a goodbye are DIFFERENT FACTS and must never be fused.** A
// closed socket is "connection lost"; a goodbye is "the board is restarting,
// come back in N". That distinction is the property that won long-poll the
// design (#1639 §2), and fusing them here would throw it away in the client.
async function poll(path) {
  let r;
  try {
    r = await fetch(path, { headers: { "Authorization": "Bearer " + token() } });
  } catch (e) {
    return { kind: "offline", error: String(e) };
  }
  const body = await r.json().catch(() => ({}));
  if (r.status === 401) { $("#tokenDialog").showModal(); return { kind: "refused", status: 401, body }; }
  if (!r.ok) return { kind: "refused", status: r.status, body };
  return { kind: "ok", status: r.status, body };
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
