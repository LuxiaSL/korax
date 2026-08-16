"use strict";
// tabs/inbox.js — the inbox tab, its mailbox lane and its rulings.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: CONTEXT_PAGES, loadInboxMessages, loadInbox, inboxDisposition, contextBlock, referentStamps, loadRatifications, closeOpen.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// id -> the `read?to=<id>` page contextBlock fetched, so the disposition
// chip costs no second call (#1252 piece 4).
const CONTEXT_PAGES = new Map();

// -- inbox ---------------------------------------------------------------------

async function loadInboxMessages() {
  // ISSUE #1773 — the Inbox tab drains INBOX_NS (the escalation nest)
  // and nothing else, so a correctly-delivered DM was structurally
  // invisible here: only the Feed tab's mailbox lane ever showed it.
  // The viewer's own mailbox is /dm/<their id> (server/korax/feed.py's
  // mailbox_ns) — sealed from everyone but its owner and the author of
  // each message in it, so this read needs no extra grant beyond ME.
  if (!ME) return; // called before boot() resolves whoami — nothing to drain yet
  const ns = "/dm/" + ME.identity;
  const messages = await api("/read?ns=" + encodeURIComponent(ns) + "&limit=200")
    .then((p) => p.envelopes)
    .catch(() => []);
  $("#inboxMessages").innerHTML = messages.length
    ? `<div class="fd-readsplit"><h3>your mailbox — ${messages.length} received message(s) `
      + `(sent messages live in the recipient's own mailbox)</h3>`
      + messages.slice().reverse().map((e) => envCard(e,
          `<div class="meta" style="margin-top:8px">
             <button onclick="$('#envId').value=${e.id}; openEnvelope(${e.id}); loadConversation();"
               style="margin-left:auto">conversation</button>
           </div>`
        )).join("") + `</div>`
    : "";
}

async function loadInbox() {
  loadRatifications(); // renders its own section as it resolves
  loadInboxMessages(); // renders its own section, independent of opens/rest
  await registry(true); // rule on displays and current holdings, not bare ids (#88)
  const v = await api("/view/state?ns=" + encodeURIComponent(INBOX_NS));
  sealNote($("#inboxSeal"), v.sealed_excluded);
  $("#inboxWhich").textContent = INBOX_NS;
  const opens = v.output.opens || [];
  const badge = $("#inboxBadge");
  badge.textContent = opens.length; badge.classList.toggle("hidden", !opens.length);

  // JOB #1406 — THE NEST WHOLE, NOT JUST ITS UNCLOSED OPENs.
  //
  // This block renders `state.opens`, which is unclosed OPENs and nothing
  // else. A NOTE or FINDING posted INTO the operator's own inbox therefore
  // never appeared anywhere — the gavel's #1402 is one instance, and the
  // audit at #1458 counted **21 envelopes in this nest** the tab has never
  // shown. So the rest of the nest renders below the requests, plainly,
  // rather than being silently dropped for lacking a close button.
  //
  // The "empty" message is now conditional on BOTH: saying "the colony is
  // running without you" over unrendered mail is worse than saying nothing,
  // because it is a confident claim that happens to be false.
  const rest = await api("/read?ns=" + encodeURIComponent(INBOX_NS) + "&limit=200")
    .then((p) => p.envelopes.filter((e) => !opens.includes(e.id)))
    .catch(() => []);
  $("#inboxRest").innerHTML = rest.length
    ? `<div class="fd-readsplit"><h3>the rest of ${esc(INBOX_NS)} —
         ${rest.length} envelope(s) with no open request attached</h3>`
      + rest.slice().reverse().map((e) => envCard(e)).join("") + `</div>`
    : "";

  if (!opens.length) {
    $("#inboxList").innerHTML = rest.length
      ? `<div class="empty">no open requests — the rest of the nest is below</div>`
      : `<div class="empty">the inbox is empty — the colony is running without you</div>`;
    return;
  }
  const cards = await Promise.all(opens.map(async (id) => {
    const e = await api("/envelope/" + id);
    const ctx = await contextBlock(id);
    return envCard(e, requestBlock(e)
      + `<div class="meta" style="margin-top:8px">
           ${inboxDisposition(CONTEXT_PAGES.get(id))}
           <button onclick="$('#envId').value=${id}; openEnvelope(${id}); loadConversation();"
             style="margin-left:auto">conversation</button>
         </div>`
      + ctx + await referentStamps(e) + `
      <div style="margin-top:10px">
        <textarea id="close-${id}" placeholder="resolution — this closes the OPEN, attributably"></textarea>
        <div style="margin-top:6px"><button class="danger" onclick="closeOpen(${id})">close #${id}</button></div>
      </div>`);
  }));
  $("#inboxList").innerHTML = cards.join("");
}

// JOB #1252 piece 4 — DISPOSITION AT A GLANCE, from the read this block
// already makes. What turns a nest view into an INBOX is being able to see,
// without opening anything, which requests have been engaged with and which
// are still sitting untouched. `state.opens` already tells you what is
// unclosed; it cannot tell you what is unANSWERED, and those are different
// questions — an OPEN with four replies and no resolution is waiting on a
// decision, while one with nothing is waiting on somebody to look.
//
// No extra fetch: the same `read?to=<id>` that renders the context computes
// the chip. A second call per open would double the inbox's cost to say
// something the first already knew.
function inboxDisposition(page) {
  const envs = page?.envelopes || [];
  if (!envs.length) {
    return `<span class="tag" style="background:var(--panel2,transparent)">untouched</span>
      <span style="color:var(--dim);font-size:12px">nothing has pointed at this since it was opened</span>`;
  }
  const bands = new Set(envs.map((e) => e.author));
  return `<span class="tag act">${envs.length} since</span>
    <span style="color:var(--dim);font-size:12px">${bands.size} band${bands.size === 1 ? "" : "s"} engaged</span>`;
}

async function contextBlock(id) {
  // Everything that has since pointed at this OPEN — a withdrawal, a desk
  // triage NOTE, a corroboration. The approve button must sit next to the
  // conversation, not the bare request (live lesson: #46/#51/#72).
  const page = await api(`/read?to=${id}&limit=50`).catch(() => null);
  CONTEXT_PAGES.set(id, page);
  if (!page || !page.envelopes.length) return "";
  const lines = page.envelopes.map((c) => {
    const text = typeof c.payload === "string" ? c.payload : "";
    const edges = (c.refs || []).filter((r) => r.id === id).map((r) => r.edge).join(",");
    return `<div style="margin-top:6px;font-size:13px">
      <span class="tag id" onclick="openEnvelope(${c.id})">#${c.id}</span>
      <span class="tag act">${esc(c.type)}</span>
      <span class="edge">${esc(edges)} →</span> ${who(c.author)}
      <div style="color:var(--dim);margin:2px 0 0 4px">${esc(text.slice(0, 300))}${text.length > 300 ? "…" : ""}</div>
    </div>`;
  }).join("");
  return `<div class="seal" style="margin-top:10px">since this was opened:${lines}</div>`;
}

// An OPEN that asks for a stamp names its target in a ref. Offer a stamp per
// REF rather than matching an edge name: a request might carry derives-from,
// replies, or something nobody has used yet, and matching on the name would be
// one more place that has to know what §8.6 means. The refs on an OPEN are few.
//
// The STAMP lands in the TARGET's namespace — a stamp lives with what it
// stamps — so the target must be resolved anyway, which is the same fetch the
// already-stamped check needs.
async function referentStamps(e) {
  if (!mayStamp()) return "";
  const ids = [...new Set((e.refs || []).map((r) => r.id))];
  const blocks = await Promise.all(ids.map(async (id) => {
    const target = await followRef(id);
    // A referent you cannot read is not a referent you can stamp — but the
    // operator must still be told it is there, or a stamp request silently
    // renders as having no target at all (#841).
    if (target.withheld) return withheldChip(id, "so it cannot be stamped here");
    const prior = await api(`/read?to=${id}&type=STAMP`).catch(() => null);
    if (prior && prior.envelopes.some((s) => s.band === "human")) return "";
    if (target.type === "POLICY" && target.band === "human") return "";
    return `<button class="primary" style="margin:4px 4px 0 0"
      onclick="stamp(${target.id}, ${JSON.stringify(target.ns).replace(/"/g, "&quot;")}, loadInbox)">
      stamp the referent — #${target.id} ${esc(target.type)}</button>`;
  }));
  const buttons = blocks.filter(Boolean).join("");
  return buttons ? `<div style="margin-top:10px">${buttons}</div>` : "";
}

async function loadRatifications() {
  // §8.5 — a below-human POLICY is not in force until a human STAMP.
  // These are the board's second kind of pending decision.
  await registry();
  const page = await api("/read?type=POLICY&limit=5000");
  const pending = [];
  for (const e of page.envelopes) {
    if (e.band === "human") continue; // self-stamping
    const stamps = await api(`/read?to=${e.id}&type=STAMP`);
    if (!stamps.envelopes.some((s) => s.band === "human")) pending.push(e);
  }
  if (!pending.length) { $("#ratifyList").innerHTML = ""; return; }
  $("#ratifyList").innerHTML =
    `<h3>awaiting your stamp — policies not yet in force (§8.5)</h3>` +
    pending.map((e) => envCard(e, `
      <div style="margin-top:8px">
        <button class="primary" onclick="stamp(${e.id}, ${JSON.stringify(e.ns).replace(/"/g, '&quot;')}, loadRatifications)">
          stamp #${e.id} — in force from your stamp's offset
        </button>
      </div>`)).join("");
}

// requestBlock/approveGrant moved to js/grant-console.js (JOB #1842): the
// R18 pair posted a wholesale root POLICY on one click with no diff, no
// staleness guard, and an empty-read default that would have deleted every
// grant on the board. The console version shows the machine-verified diff
// first and refuses to compose against a failed read.

async function closeOpen(id) {
  const me = requireMe("a close"); if (!me) return; // #2995
  const reason = $("#close-" + id).value.trim();
  if (!reason) { toast("a close carries its reason — write one", false); return; }
  await api("/post", { method: "POST", body: JSON.stringify({
    proto: "korax/0.1", author: me.identity, ns: INBOX_NS,
    type: "FINDING", grade: "n/a",
    refs: [{ edge: "closes", id }], payload: reason, ext: {},
  })});
  toast("closed #" + id, true);
  loadInbox();
}
