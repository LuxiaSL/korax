"use strict";
// tabs/ledger.js — the ledger tab.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: LEDGER_TYPES, ledgerKind, loadLedger.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// -- ledger (#operator, 2026-08-10): recollect without the desk's prose --------

const LEDGER_TYPES = new Set(["JOB", "CLAIM", "HANDOVER", "WARN", "POLICY", "STAMP", "OPEN"]);

function ledgerKind(e) {
  const closes = (e.refs || []).some((r) => r.edge === "closes");
  if (closes && e.ns.endsWith("/inbox")) return "rulings";
  if (closes) return "deliveries";
  if (e.type === "SUPERSEDE") return null; // corrections ride their targets
  if (e.type === "JOB") return "jobs posted";
  if (e.type === "CLAIM") return "claims";
  if (e.type === "HANDOVER") return "handovers";
  if (e.type === "POLICY" || e.type === "STAMP") return "governance";
  if (e.type === "OPEN" && e.ns.endsWith("/inbox")) return "asks in the inbox";
  if (e.type === "WARN") return "warns";
  return null;
}

async function loadLedger() {
  await registry();
  const page = await api("/read?limit=5000");
  const seen = parseInt(localStorage.getItem("koraxLedgerSeen") || "-1", 10);
  const signal = page.envelopes
    .map((e) => ({ e, kind: (LEDGER_TYPES.has(e.type) ||
        (e.refs || []).some((r) => r.edge === "closes")) ? ledgerKind(e) : null }))
    .filter((x) => x.kind);

  const fresh = signal.filter((x) => x.e.id > seen);
  $("#ledgerBadge").textContent = fresh.length;
  $("#ledgerBadge").classList.toggle("hidden", !fresh.length);
  $("#ledgerNew").innerHTML = fresh.length
    ? `<h3>since you last looked (${fresh.length})</h3>` +
      fresh.map((x) => envCard(x.e,
        `<div style="font-size:11px;color:var(--accent2);margin-top:4px">${esc(x.kind)}</div>`)).join("")
    : `<div class="empty">nothing new since you last marked — the colony's been quiet, or you're caught up</div>`;

  const groups = {};
  for (const x of signal) (groups[x.kind] = groups[x.kind] || []).push(x.e);
  const order = ["asks in the inbox", "rulings", "deliveries", "jobs posted",
                 "claims", "governance", "handovers", "warns"];
  $("#ledgerAll").innerHTML = "<h3>the whole story, grouped</h3>" +
    order.filter((k) => groups[k]).map((k) => {
      const es = groups[k];
      return `<div class="card"><div class="meta"><b>${esc(k)}</b><span>${es.length}</span></div>
        ${idChips(es.map((e) => e.id).reverse())}</div>`;
    }).join("");
  window._ledgerHead = page.cursor;
}

$("#ledgerSeen").addEventListener("click", () => {
  localStorage.setItem("koraxLedgerSeen", String(window._ledgerHead ?? -1));
  loadLedger(); toast("ledger marked seen", true);
});
