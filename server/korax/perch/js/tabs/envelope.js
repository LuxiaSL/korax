"use strict";
// tabs/envelope.js — the single-envelope page.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: stampBlock, loadEnvelope.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// The stamp affordance for one envelope, or the reason there is not one.
// Generic by ruling: `stamps` carries no target constraint (the board serves
// {sources:["STAMP"]}), so an allow-list here would be a second source of
// truth for §8.6. Offer, and let the nest policy and §4.3 refuse.
async function stampBlock(e) {
  const prior = await api(`/read?to=${e.id}&type=STAMP`).catch(() => null);
  const human = prior && prior.envelopes.find((s) => s.band === "human");
  if (human) {
    return `<div class="seal" style="margin-top:10px">stamped by
      ${who(human.author)} — <span class="tag id" onclick="openEnvelope(${human.id})">#${human.id}</span>
      ${esc((human.ts || "").replace("T", " ").replace("Z", ""))}</div>`;
  }
  // §8.5 — a human-band POLICY is in force from its own posting; stamping it
  // is meaningless, which is what loadRatifications' skip encodes. This is the
  // ONLY case a rule forbids: nothing anywhere stops an operator stamping a
  // PROPOSAL they authored, and inventing that here would be the perch
  // deciding governance it does not decide.
  if (e.type === "POLICY" && e.band === "human") {
    return `<div class="seal" style="margin-top:10px">in force from its own
      offset — a human-band POLICY needs no stamp (§8.5)</div>`;
  }
  if (!mayStamp()) return "";
  return `<div style="margin-top:8px">
    <button class="primary" onclick="stamp(${e.id}, ${JSON.stringify(e.ns).replace(/"/g, "&quot;")}, loadEnvelope)">
      stamp #${e.id} — ${esc(e.type)} in ${esc(e.ns)}
    </button>
  </div>`;
}

async function loadEnvelope() {
  const id = $("#envId").value.trim();
  if (id === "") return;
  const e = await api("/envelope/" + id);
  await registry();  // stampBlock renders an author line for an existing stamp
  $("#envOut").innerHTML = envCard(e,
    (e.required_unmet ? `<div class="seal" style="margin-top:10px">reading list before acting on this:
      ${e.required_unmet.unread.map((i) => `<span class="tag id" onclick="openEnvelope(${i})">#${i}</span>`).join(" ")}</div>` : "")
    + await stampBlock(e));
  $("#envView").innerHTML = "";
}
// S1 (JOB #1969): a fetched envelope is a place, so the fetch button
// records #/e/<id> — the echo is suppressed and the load runs here, once.
$("#envLoad").addEventListener("click", () => {
  const id = $("#envId").value.trim();
  if (id !== "") setHash("#/e/" + id);
  loadEnvelope();
});
$("#envConvo").addEventListener("click", loadConversation);
document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", async () => {
  const id = $("#envId").value.trim();
  if (id === "") return;
  const v = await api(`/view/${b.dataset.view}?id=${id}`);
  $("#envView").innerHTML = `<h3>${b.dataset.view} @ ${v.at}</h3>
    <pre>${esc(JSON.stringify(v.output, null, 1))}</pre>`;
}));
