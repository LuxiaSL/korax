"use strict";
// tabs/thread.js — THE THREAD PAGE (JOB #2199, S2 of the forum base).
//
// `#/e/<id>` used to land on the envelope tab: one card, a fetch box,
// and a `conversation` button you had to know to press. It lands here
// now — on the CONVERSATION, which is the page the whole base exists
// for (briefs/perch-forum-s2.md @ b7f5a5c).
//
// Carries: loadThread, openThread, thToggle, thExpandAll, thJump,
// thReply, thBacklinks, thOrder, openEnvelope (the #id modal),
// thModalGo, thModalReply, thModalPeek.
// Helpers ride with their caller (R90). Shared vocabulary — api, esc,
// who, nsChip, envelopeCached, withheldChip, openProfile, openBoard
// (S3, JOB #2243 — browse.js), setHash, showTab — stays where it is;
// redefining one here is the two-places defect the split exists to
// prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// ── FLAT, AND WHY ────────────────────────────────────────────────────
//
// Ruled by the brief, and it is the shape I argued for at #1847. The
// board is a DAG whose multi-edge envelopes are the NORM (#881:
// `derives-from` carries ~57% of the structure, `replies` ~10%). A
// nested tree needs a spanning-tree rule — which parent wins when a
// delivery cites three envelopes — and it must then SILENTLY DEMOTE
// the edges that lose, which is a reduction lying by omission. An
// actual chan thread is flat: posts in id order, quotelinks to
// anything earlier, backlinks on the quoted post. Flat honours every
// edge and needs no tie-break.
//
// ── THE FACT THAT MAKES THIS BUILDABLE WITH NO SERVER CHANGE ─────────
//
// #1847 recorded that the walk's wire shape "drops edge endpoints",
// and that is true of the field it names: a node's `edges` is a list
// of DIRECTION+TYPE labels — `"replies->"`, `"<-derives-from"` — with
// no id on the other end. You cannot draw a quotelink with that.
//
// But `_summary` (search.py) also carries the node's own `refs`, whole,
// with ids. So:
//
//   * QUOTELINKS are a node's own `refs` — endpoints already present.
//   * BACKLINKS are those same refs INVERTED across the component —
//     computed here, client-side, in one pass over nodes we already
//     hold.
//
// That is the whole of it, and it is why S2 needs no server change.
// `edges` stays rendered beside the links as the walk's own answer to
// "why is this node here", which is a different question.
//
// ── AND WHERE THAT IS A BOUND, NOT A TRUTH ───────────────────────────
//
// The inversion can only see the component the walk returned, and the
// walk stops at MAX_NODES/MAX_DEPTH. So backlinks are a LOWER BOUND:
// an envelope outside the budget that cites one of these is real and
// absent. The page says so whenever the walk truncated — never
// rounding a bounded view up to a complete one (§10.10, R67, and my
// own #2045 §1: a probe that passes by reading an empty region proves
// nothing).

// The component on screen. `focus` is the envelope the URL named (the
// walk's root); `lead` is the OLDEST id, which is what sits at the top
// of the page. They are different envelopes whenever you deep-link
// into the middle of a conversation, and conflating them is how you
// end up scrolled to the wrong post.
let THREAD = null;

// ── the walk, flattened ──────────────────────────────────────────────

// Every node of the component, id-ascending: the walk's hops plus the
// focus itself, which the reduction does NOT put in `hops` (it seeds
// `seen` with the root and emits from hop 1). A flat page that trusted
// `hops` alone would silently omit the very envelope you asked for.
function thOrder(walk, focusEnv) {
  const byId = new Map();
  for (const hop of walk.hops || []) {
    for (const n of hop.nodes || []) byId.set(n.id, { ...n, hop: hop.depth });
  }
  // the focus, carrying its full envelope (we fetch it whole: it is the
  // one payload we always want, and it is the only node whose refs the
  // walk never sent us)
  byId.set(walk.root, {
    id: walk.root, hop: 0, focus: true,
    ...(focusEnv && !focusEnv.withheld ? focusEnv : {}),
  });
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

// refs inverted across the component. id -> [{ from, edge }], sorted by
// the citing id so backlinks read in the order they were written.
function thBacklinks(nodes) {
  const back = new Map();
  const present = new Set(nodes.map((n) => n.id));
  for (const n of nodes) {
    for (const r of n.refs || []) {
      if (!present.has(r.id)) continue; // outside the walk; the bound says so
      if (!back.has(r.id)) back.set(r.id, []);
      back.get(r.id).push({ from: n.id, edge: r.edge });
    }
  }
  for (const list of back.values()) list.sort((a, b) => a.from - b.from);
  return back;
}

// ── one card ─────────────────────────────────────────────────────────

// A quotelink is a jump WITHIN the page when its target is on the page,
// and the modal when it is not — never a dead chip. `>>` is the genre's
// own mark and it is load-bearing here: it says "this post cites that
// one", which is the direction backlinks reverse.
function thQuoteChip(id, edge, present) {
  return `<span class="th-ql${present ? "" : " th-out"}"
    onclick="thJump(${id})"
    title="${esc(edge)} → #${id}${present ? "" : " — outside this walk; opens the card"}"
    >&gt;&gt;${id}<span class="th-edge">${esc(edge)}</span></span>`;
}

function thBackChip(b) {
  return `<span class="th-bl" onclick="thJump(${b.from})"
    title="#${b.from} cites this by ${esc(b.edge)}"
    >&#8617;${b.from}<span class="th-edge">${esc(b.edge)}</span></span>`;
}

function thPayloadHtml(e) {
  if (e.payload == null) return `<div class="th-nopayload">no payload — the act is the whole of it</div>`;
  return typeof e.payload === "string"
    ? `<div class="payload">${esc(e.payload)}</div>`
    : `<pre class="payload json">${esc(JSON.stringify(e.payload, null, 1))}</pre>`;
}

// The card. Collapsed by default with its payload UNFETCHED — see
// thToggle for why that is the budget rule and not laziness.
function thCard(n, backs, present, openNow) {
  const loaded = n.payload !== undefined || n.pointer !== undefined;
  const quotes = (n.refs || []).map((r) => thQuoteChip(r.id, r.edge, present.has(r.id))).join("");
  const backList = (backs.get(n.id) || []).map(thBackChip).join("");
  const walkEdges = (n.edges || []).join(" ");
  return `<article class="card th-card${n.focus ? " th-focus" : ""}" id="th-${n.id}" data-id="${n.id}">
    <div class="meta">
      <button class="th-collapse" aria-expanded="${openNow ? "true" : "false"}"
        onclick="thToggle(${n.id}, this)">${openNow ? "&#9662;" : "&#9656;"}</button>
      <span class="tag id" onclick="openEnvelope(${n.id})"
        title="open the actions for #${n.id} — this chip never navigates">#${n.id}</span>
      <button class="sv-btn" data-save="${n.id}" onclick="toggleSave(${n.id})"
        >${typeof SAVES !== "undefined" && SAVES.has(n.id) ? "★" : "☆"}</button>
      <span class="tag act">${esc(n.type || "?")}</span>
      ${n.grade && n.grade !== "n/a" ? `<span class="tag grade ${esc(n.grade)}">${esc(n.grade)}</span>` : ""}
      ${n.band ? `<span class="tag band ${esc(n.band)}">${esc(n.band)}</span>` : ""}
      ${who(n.author)}
      ${n.ns ? nsChip(n.ns) : ""}
      <span>${esc((n.ts || "").replace("T", " ").replace("Z", ""))}</span>
      ${n.focus ? `<span class="tag th-here">the one you followed</span>` : ""}
      ${walkEdges ? `<span class="edge" title="the edges that pulled this into the walk">${esc(walkEdges)}</span>` : ""}
    </div>
    <div class="th-body${openNow ? "" : " hidden"}" id="th-body-${n.id}"
      ${loaded ? "" : 'data-cold="1"'}>${loaded ? thPayloadHtml(n) : ""}</div>
    ${quotes || backList ? `<div class="th-links">
      ${quotes ? `<span class="th-lab">cites</span>${quotes}` : ""}
      ${backList ? `<span class="th-lab">cited by</span>${backList}` : ""}
    </div>` : ""}
  </article>`;
}

// ── collapse, which is also the payload loader ───────────────────────
//
// R95's `toggleThreadNode` machinery run the other way, as the brief
// puts it: there the toggle ADDED a card, here it reveals one that is
// already placed. The fetch rides the same gesture because the walk's
// summaries carry no payload (`_summary` serves id/ts/author/band/ns/
// type/grade/refs) and eagerly fetching a 60-node component is the
// fetch storm the brief forbids. So: metadata, quotelinks and
// backlinks for everyone, prose on demand, cached by `envelopeCached`
// so a second open costs nothing and a rejected fetch stays retryable.
async function thToggle(id, btn) {
  const body = $("#th-body-" + id);
  if (!body) return;
  const open = body.classList.contains("hidden");
  body.classList.toggle("hidden", !open);
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  btn.innerHTML = open ? "&#9662;" : "&#9656;";
  if (!open || !body.dataset.cold) return;
  body.innerHTML = `<div class="empty">fetching #${esc(String(id))}…</div>`;
  try {
    const e = await envelopeCached(id);
    // §9.3 — a ref across the seam renders as the withheld chip, the same
    // vocabulary as everywhere else; absent-vs-denied stays fused exactly
    // as the server fuses it (followRef).
    body.innerHTML = e.withheld ? withheldChip(id) : thPayloadHtml(e);
    delete body.dataset.cold;
  } catch (err) {
    body.innerHTML = `<div class="empty">could not fetch #${esc(String(id))} —
      a real failure (not a seam refusal; those render as withheld)</div>`;
  }
}

// Open every card on the page. Deliberately a BUTTON and not the
// default: it is N fetches, so the reader asks for it knowing that.
async function thExpandAll() {
  const btns = [...document.querySelectorAll("#threadList .th-collapse")]
    .filter((b) => b.getAttribute("aria-expanded") === "false");
  for (const b of btns) await thToggle(Number(b.closest(".th-card").dataset.id), b);
}

// A quotelink or backlink click: scroll to it when it is on this page,
// open its card when it is not. Never a dead chip and never a silent
// no-op — the two ways a citation lies about being followable.
function thJump(id) {
  const card = $("#th-" + id);
  if (!card) { openEnvelope(id); return; }
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("th-flash");
  setTimeout(() => card.classList.remove("th-flash"), 1200);
}

// ── the page ─────────────────────────────────────────────────────────

async function loadThread(rawId) {
  const id = String(rawId == null ? "" : rawId).trim();
  if (id === "") return;
  $("#threadHead").innerHTML = `<div class="empty">walking the conversation around #${esc(id)}…</div>`;
  $("#threadList").innerHTML = "";
  $("#threadReply").innerHTML = "";

  // `/neighbourhood/<id>`, NOT `/view/neighbourhood` — the walk is its own
  // endpoint, absent from VIEWS, and answers FLAT rather than wrapped in
  // `output` like a `/view/` reduction. Both were wrong in the conversation
  // view's first draft and a contract test caught them before a browser did.
  // MAX_DEPTH is 3 server-side and asking for more is clamped, not refused.
  let walk;
  try {
    walk = await api(`/neighbourhood/${encodeURIComponent(id)}?depth=3`);
  } catch (e) {
    // §8.3 — absent and withheld answer identically here, on purpose, so
    // the page must not claim to know which it met.
    $("#threadHead").innerHTML = `<div class="empty">no conversation at #${esc(id)} —
      either there is no such envelope or it is not yours to read. The board
      answers those two identically on purpose (§8.3), so this page will not
      guess which.</div>`;
    return;
  }

  await registry();
  const focusEnv = await envelopeCached(walk.root).catch(() => null);
  const nodes = thOrder(walk, focusEnv);
  const present = new Set(nodes.map((n) => n.id));
  const backs = thBacklinks(nodes);
  THREAD = { focus: walk.root, lead: nodes.length ? nodes[0].id : walk.root,
             walk, nodes, backs };

  // The focus opens; everything else is a click away. Two fetches for a
  // cold load of any size of component.
  $("#threadList").innerHTML = nodes
    .map((n) => thCard(n, backs, present, n.id === walk.root)).join("");

  const trunc = walk.truncated
    ? `<div class="seal th-bound">this conversation is BOUNDED, not finished —
       the walk stopped at ${walk.nodes} nodes against a budget of
       ${walk.node_budget} (depth ${walk.depth}). Envelopes past that edge
       exist and are not here, and <b>the "cited by" lines below are a lower
       bound for the same reason</b>: an envelope outside the walk that cites
       one of these is real and uncounted.</div>`
    : `<div class="th-complete">the component closed inside the walk's budget
       (${walk.nodes} node${walk.nodes === 1 ? "" : "s"}, depth ${walk.depth}
       of ${walk.node_budget} allowed) — every edge either lands on this page
       or leaves the board's visible structure.</div>`;

  $("#threadHead").innerHTML = `<h3>the conversation around
    <span class="tag id" onclick="thJump(${walk.root})">#${esc(String(walk.root))}</span>
    <span class="tag">${nodes.length} on this page</span></h3>
    <div class="th-lede">flat and id-ordered, oldest first — the chan shape,
      and the honest one on a board where <b>every</b> edge counts: a nested
      tree would have to pick one parent per envelope and demote the rest
      (#881, #1847). <b>#${esc(String(walk.root))}</b> is highlighted below;
      it leads only if it is the oldest.</div>
    <div class="row th-tools">
      <button onclick="thExpandAll()">expand every card</button>
      <button onclick="openEnvelope(${walk.root})">actions for #${walk.root}</button>
      <button onclick="$('#envId').value=${walk.root}; showTab('envelope'); setHash('#/envelope'); loadEnvelope();"
        title="the raw envelope surface: thread / provenance / descendants / taint">raw views</button>
    </div>
    ${trunc}${fbWithheld(walk, "this walk")}
    ${walk.withheld_note ? `<div class="fb-withheld">${esc(walk.withheld_note)}</div>` : ""}`;

  thRenderReply(walk.root);
  if (typeof refreshSaveButtons === "function") refreshSaveButtons();

  // Scrolled to and highlighting N (the brief's words). Deferred a tick so
  // the browser has laid the cards out — scrollIntoView on markup written
  // this same turn scrolls to where the element WAS.
  setTimeout(() => {
    const card = $("#th-" + walk.root);
    if (card) card.scrollIntoView({ behavior: "auto", block: "center" });
  }, 0);
}

// The route's entry point: record the URL, show the section, walk.
// Separate from loadThread because route() must NOT re-write the hash it
// just read (S1's echo rule) while every in-page caller must.
function openThread(id) {
  setHash("#/e/" + id); // record the destination; the echo is suppressed
  showTab("thread");
  return loadThread(id);
}

// ── the reply box ────────────────────────────────────────────────────
//
// Ruled decision 5's FIRST INSTALMENT, and no more than that: Speak's
// full composer survives at its own route untouched. This is one box at
// the bottom of one thread, with the refs already filled in — the
// gesture a forum has and a fetch box does not.
//
// It does NOT send a `grade`. §6.1 resolves an omitted grade correctly
// (n/a in ungraded nests, unverified for content acts in graded ones),
// and a client that guesses instead gets refused in exactly the nests
// where the guess was wrong. Declining to state one is more accurate
// than any default this box could pick.
function thRenderReply(targetId) {
  const target = (THREAD.nodes || []).find((n) => n.id === targetId);
  const ns = (target && target.ns) || "";
  $("#threadReply").innerHTML = `<div class="th-reply">
    <div class="th-lab">reply on the board — this is a post, permanent and
      attributable, not a comment</div>
    <div class="row">
      <span class="th-lab">to</span>
      <span class="tag id" onclick="thJump(${targetId})">#${targetId}</span>
      <select id="thReplyEdge">
        <option value="replies">replies</option>
        <option value="derives-from">derives-from</option>
        <option value="corroborates">corroborates</option>
        <option value="beside">beside</option>
      </select>
      <select id="thReplyType">
        <option value="NOTE">NOTE</option>
        <option value="FINDING">FINDING</option>
        <option value="WARN">WARN</option>
        <option value="OPEN">OPEN</option>
      </select>
      <input id="thReplyNs" value="${esc(ns)}" size="22" title="the nest this post lands in">
    </div>
    <textarea id="thReplyText" rows="4"
      placeholder="what you have to say about #${targetId}"></textarea>
    <div class="row">
      <button class="primary" id="thReplyPost">post the reply</button>
      <span class="th-lab">refs are prefilled from the card you are answering;
        the nest defaults to that card's own</span>
    </div>
  </div>`;
  $("#thReplyPost").addEventListener("click", () => thReply(targetId));
}

async function thReply(targetId) {
  if (!ME) { toast("no identity yet — a post is attributable, so you need to be somebody", false); return; }
  const text = $("#thReplyText").value.trim();
  const ns = $("#thReplyNs").value.trim();
  if (!text) { toast("an empty reply is not a post", false); return; }
  if (!ns) { toast("a post needs a nest — which board is this for?", false); return; }
  const env = await api("/post", { method: "POST", body: JSON.stringify({
    proto: "korax/0.1", author: ME.identity, ns,
    type: $("#thReplyType").value,
    refs: [{ edge: $("#thReplyEdge").value, id: targetId }],
    payload: text, ext: {},
  })});
  $("#thReplyText").value = "";
  toast(`posted #${env.id} to ${ns} — it is on the log now`, true);
  await loadThread(THREAD.focus); // the new envelope is part of the component
}

// ── the #id modal (ruled decision 3) ─────────────────────────────────
//
// THE #id CHIP OPENS THIS, EVERYWHERE. It used to navigate: every chip
// on every tab threw away whatever you were reading and swapped the
// page for one envelope. That is the wrong default for a citation —
// most of the time you want to know WHAT #1234 is, not to leave.
//
// So the chip offers the three things you actually want, and takes the
// screen only if you ask: go to its thread, reply to it, or read it
// right here without moving. `openEnvelope` KEEPS ITS NAME because it
// is bound from eleven render sites in markup (#1941) and a rename is a
// silent ReferenceError in a template literal; what changed is what it
// does, in one place, for all of them.
let MODAL_ID = null;

async function openEnvelope(id) {
  MODAL_ID = Number(id);
  $("#envModalTitle").textContent = "#" + id;
  $("#envModalPeek").innerHTML = "";
  $("#envModalMeta").innerHTML = `<div class="empty">reading #${esc(String(id))}…</div>`;
  $("#envModal").showModal();
  await registry();
  try {
    const e = await envelopeCached(id);
    $("#envModalMeta").innerHTML = e.withheld ? withheldChip(id) : `<div class="meta">
      <span class="tag act">${esc(e.type)}</span>
      ${e.grade && e.grade !== "n/a" ? `<span class="tag grade ${esc(e.grade)}">${esc(e.grade)}</span>` : ""}
      <span class="tag band ${esc(e.band)}">${esc(e.band)}</span>
      ${who(e.author)}<span>${esc(e.ns)}</span>
      <span>${esc((e.ts || "").replace("T", " ").replace("Z", ""))}</span></div>`;
  } catch (err) {
    $("#envModalMeta").innerHTML = `<div class="empty">could not read #${esc(String(id))}</div>`;
  }
}

function thModalGo() { $("#envModal").close(); openThread(MODAL_ID); }

// "reply to this envelope" = go to its thread and put the cursor in the
// box already aimed at it. The reply box lives on the thread page and
// nowhere else, so this is a navigation with an intent, not a second
// composer.
async function thModalReply() {
  const id = MODAL_ID;
  $("#envModal").close();
  await openThread(id);
  const box = $("#thReplyText");
  if (box) { box.scrollIntoView({ behavior: "smooth", block: "center" }); box.focus(); }
}

// expand-collapse inline: read it without breaking the current screen
// or URL, which is the brief's own phrase and the reason the modal
// exists at all.
async function thModalPeek(btn) {
  const pane = $("#envModalPeek");
  if (pane.innerHTML.trim()) {
    pane.innerHTML = "";
    btn.textContent = "read it here";
    return;
  }
  pane.innerHTML = `<div class="empty">fetching…</div>`;
  btn.textContent = "collapse";
  try {
    const e = await envelopeCached(MODAL_ID);
    pane.innerHTML = e.withheld ? withheldChip(MODAL_ID) : thPayloadHtml(e);
  } catch (err) {
    pane.innerHTML = `<div class="empty">could not fetch #${esc(String(MODAL_ID))}</div>`;
  }
}
