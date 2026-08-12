"use strict";
// tabs/saved.js — the shelf (JOB #1739).
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: loadSaved.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// -- the shelf (JOB #1739) ----------------------------------------------------
//
// Reading the shelf is reading your OWN mailbox filtered on the save
// marker — client-side, per the brief's default; if this ever genuinely
// needs a server-side filter param, that seam gets argued on the record,
// not silently added. Each entry resolves its `beside` target through
// R95's envelope cache and renders the full card (which carries its own
// save affordance, so unsaving from the shelf is the same gesture as
// anywhere else). A target the viewer can no longer read renders as an
// honest stub — the SAVE is intact, the reach is what changed.
async function loadSaved() {
  await loadSaves();
  await registry();
  const entries = [...SAVES.entries()]
    .map(([target, saveId]) => ({ target, saveId }))
    .sort((a, b) => b.saveId - a.saveId); // newest save first
  if (!entries.length) {
    $("#savedList").innerHTML = `<div class="empty">nothing saved yet —
      the ☆ on any card puts it here, as a sealed note in your own
      mailbox</div>`;
    return;
  }
  const cards = await Promise.all(entries.map(async ({ target, saveId }) => {
    const e = await envelopeCached(target);
    const footer = `<div class="meta" style="margin-top:8px">
      <span class="sv-note">save note #${saveId}, in your mailbox</span>
    </div>`;
    if (e.withheld) {
      return withheldChip(target,
        "the save is intact; the envelope has moved beyond your reach "
        + "(rotation or seal) — that is a fact about the board, not a bug "
        + "in your shelf");
    }
    return envCard(e, footer);
  }));
  $("#savedList").innerHTML = cards.join("");
  refreshSaveButtons();
}
