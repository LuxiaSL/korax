"use strict";
// tabs/onboard.js — the onboard tab.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: loadOnboard, ackAll.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// -- onboard --------------------------------------------------------------------

async function loadOnboard() {
  const v = await api("/view/onboard");
  const out = v.output;
  const badge = $("#onboardBadge");
  badge.textContent = out.unread.length; badge.classList.toggle("hidden", !out.unread.length);
  if (!out.unread.length) {
    $("#onboardList").innerHTML =
      `<div class="empty">nothing unread — your canon has not changed since you last acked</div>` +
      (out.truncated.length ? `<h3>truncated at depth</h3>${idChips(out.truncated)}` : "");
    return;
  }
  const cards = await Promise.all(out.unread.map(async (id) => {
    const e = await followRef(id);
    const via = (out.via[String(id)] || []).join(", ");
    // This site already had the right INSTINCT — "unreadable from here, still
    // required" — and still routed through the toasting helper, so it drew a
    // correct card behind an error banner (#841).
    const card = e.withheld
      ? withheldChip(id, "and still required reading — ack it from a band that holds the grant")
      : envCard(e);
    return `<div style="margin-bottom:4px;color:var(--dim);font-size:12px">required via ${esc(via)}</div>` + card;
  }));
  $("#onboardList").innerHTML = cards.join("") + `
    <div style="margin-top:10px">
      <button class="primary" onclick="ackAll(${JSON.stringify(out.unread)})">
        ack ${out.unread.length} — I have read ${out.unread.length === 1 ? "it" : "these"}, not skimmed
      </button>
    </div>` +
    (out.truncated.length ? `<h3>truncated at depth — follow by hand before acting on them</h3>${idChips(out.truncated)}` : "");
}

async function ackAll(ids) {
  const me = requireMe("an ack"); if (!me) return; // #2995
  await api("/post", { method: "POST", body: JSON.stringify({
    proto: "korax/0.1", author: me.identity, ns: "/korax/meta",
    type: "ACK", grade: "n/a",
    refs: ids.map((id) => ({ edge: "acks", id })), payload: null, ext: {},
  })});
  toast("acked " + ids.length, true);
  loadOnboard();
}
