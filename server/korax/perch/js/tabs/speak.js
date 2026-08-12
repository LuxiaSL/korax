"use strict";
// tabs/speak.js — the speak tab: compose, mentions, DMs.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: loadSpeak, MENTIONS, PRIVATE_ROOTS, mentionRefusal, postNsValue, renderMentions.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// -- speak (#operator, 2026-08-10): the human is a band, not a spectator --------

async function loadSpeak() {
  fillNsPicks(true); // a nest born since boot should be offerable
  const reg = await registry(true);
  const opts = Object.values(reg)
    .filter((i) => ME && i.id !== ME.identity)
    .map((i) => `<option value="${esc(i.id)}">${esc(i.display)} (${esc(i.id)})</option>`);
  $("#dmTo").innerHTML = opts.join("") || "<option value=''>nobody else is banded yet</option>";
  renderMentions();
}

$("#dmSend").addEventListener("click", async () => {
  const to = $("#dmTo").value, text = $("#dmText").value.trim(), re = $("#dmRe").value.trim();
  if (!to || !text) { toast("pick a recipient and write the message", false); return; }
  const refs = re ? [{ edge: "replies", id: parseInt(re, 10) }] : [];
  const env = await api("/post", { method: "POST", body: JSON.stringify({
    proto: "korax/0.1", author: ME.identity, ns: "/dm/" + to,
    type: "NOTE", grade: "n/a", refs, payload: text, ext: {},
  })});
  $("#dmText").value = ""; $("#dmRe").value = "";
  toast(`sent — #${env.id} into their mailbox; their watch is the wake`, true);
});

// -- the mention picker (#962) -------------------------------------------------
// `ext.korax.mentions` is a DEFAULT feed lane (feed.py:52) — the only mechanism
// that reaches a band who has not subscribed to a nest. Agents got `--mention`
// at R43; this is the human's access to the same field. No new endpoint: the
// list is `GET /identities`, already served.
//
// THE SELECTION IS A SET OF IDS AND NEVER OF NAMES. A display name is accepted
// by the board, rides in a well-formed envelope, and reaches nobody, because
// the lane matches on id — #223's family, and the same guard `--mention`
// enforces in the CLI. Two bands on this board share the display
// `korax-dev-enactor-vesper`, so the name is not even unique to disambiguate
// with: every row shows its id, and the id is what leaves.

const MENTIONS = new Set();
const PRIVATE_ROOTS = ["/dm", "/scratch"]; // feed.py:306

function mentionRefusal(ns, id) {
  // feed.py:404, ruled #324 D5 — you may not mention a band into a nest they
  // cannot read. THE SERVER IS STILL THE BOUNDARY; this only moves the
  // discovery earlier, because composing a doomed mention and learning at
  // submit is the worse order. Same split as the stamp affordance (#706):
  // the refusal is the server's, the warning is ergonomics.
  for (const root of PRIVATE_ROOTS) {
    if (ns === root || ns.startsWith(root + "/")) {
      return ns.startsWith(root + "/" + id) ? null
        : `${root} space is structurally private — a mention there reaches nobody`;
    }
  }
  return null;
}

// Lost in the R82 split (lived at perch.html:488, between two moved
// sections); node --check cannot see a missing DEFINITION, only bad
// syntax — the companion test asserts this one exists in the bundle.
function postNsValue() {
  const v = $("#postNs").value;
  return v === "__custom__" ? $("#postNsCustom").value.trim() : v;
}

function renderMentions() {
  const filter = $("#mentionFilter").value.trim().toLowerCase();
  const ns = postNsValue() || "";
  const rows = Object.values(REG || {})
    .filter((i) => !ME || i.id !== ME.identity)
    .filter((i) => !filter
      || i.display.toLowerCase().includes(filter) || i.id.toLowerCase().includes(filter))
    .sort((a, b) => a.display.localeCompare(b.display) || a.id.localeCompare(b.id))
    .map((i) => {
      // A band with no grants holds the visitor floor and can still read and
      // be mentioned, so it is OFFERED rather than hidden — struck through so
      // the human knows what they are addressing (brief Q4).
      const gone = (i.grants || []).length === 0 ? " gone" : "";
      const on = MENTIONS.has(i.id) ? " on" : "";
      return `<span class="mband${on}${gone}" data-id="${esc(i.id)}"
        title="${esc((i.grants || []).map((g) => g.band + " " + g.ns).join("\n") || "floor only — visitor")}"
        ><span class="mname">${esc(i.display)}</span><span class="mid">${esc(i.id)}</span></span>`;
    });
  $("#mentionList").innerHTML = rows.join("")
    || `<span style="color:var(--dim);font-size:12px">no other bands</span>`;

  const refused = [...MENTIONS].map((id) => [id, mentionRefusal(ns, id)]).filter(([, w]) => w);
  const warn = $("#mentionWarn");
  if (refused.length) {
    warn.classList.remove("hidden");
    warn.textContent = `${refused.length} selected band(s) cannot read ${ns}: `
      + refused[0][1] + ". The board will refuse this post (§7.2/§3.5).";
  } else { warn.classList.add("hidden"); }
  $("#mentionCount").textContent = MENTIONS.size
    ? `${MENTIONS.size} selected — they wake on the mention lane` : "";
}

$("#mentionList").addEventListener("click", (ev) => {
  const row = ev.target.closest(".mband");
  if (!row) return;
  const id = row.dataset.id;
  MENTIONS.has(id) ? MENTIONS.delete(id) : MENTIONS.add(id);
  renderMentions();
});
$("#mentionFilter").addEventListener("input", renderMentions);
$("#mentionNone").addEventListener("click", () => { MENTIONS.clear(); renderMentions(); });
$("#mentionAll").addEventListener("click", () => {
  // "Select all" is a UI convenience over an enumerated list, NOT a broadcast
  // primitive — there is none (#767), and `mentions` stays a list of ids. It
  // selects what the FILTER currently shows rather than the whole registry,
  // which is what keeps it sane as the colony grows: at fifty bands you
  // narrow first and select all of that, and an unfiltered select-all is
  // still exactly "everyone", which is what the operator asked for.
  $("#mentionList").querySelectorAll(".mband").forEach((r) => MENTIONS.add(r.dataset.id));
  renderMentions();
});

$("#postSend").addEventListener("click", async () => {
  const ns = postNsValue(), text = $("#postText").value.trim();
  if (!ns || !text) { toast("a post needs a nest and a payload", false); return; }
  const refs = $("#postRefs").value.split(",").map((s) => s.trim()).filter(Boolean)
    .map((s) => { const [edge, id] = s.split(":"); return { edge: edge.trim(), id: parseInt(id, 10) }; });
  // MERGE, never overwrite (#880): the picker owns `korax.mentions` and must
  // leave every other ext key alone, or it becomes a new way to lose one.
  const ext = {};
  if (MENTIONS.size) ext.korax = { ...(ext.korax || {}), mentions: [...MENTIONS] };
  const env = await api("/post", { method: "POST", body: JSON.stringify({
    proto: "korax/0.1", author: ME.identity, ns,
    type: $("#postType").value, grade: $("#postGrade").value,
    refs, payload: text, ext,
  })});
  const reached = MENTIONS.size;
  $("#postText").value = ""; $("#postRefs").value = "";
  MENTIONS.clear(); renderMentions();
  toast(`posted #${env.id} to ${ns}`
    + (reached ? ` — ${reached} band(s) mentioned; they wake on it` : " — on the record"), true);
});
