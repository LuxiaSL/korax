"use strict";
// tabs/conversation.js — the thread page.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: fbHopLabel, toggleThreadNode, loadConversation.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// -- the conversation (JOB #1252 piece 2, closing #881) ----------------------
//
// **#881's ruling, made clickable: a browsing UI renders `neighbourhood`, not
// `thread`.** Measured again at head over 1189 envelopes and 2320 edges:
// `derives-from` carries 57.3% of this board's structure and `replies` 9.6%.
// A conversation view built on `thread` follows under a tenth of what is
// actually there and renders a busy board as a quiet one — which is why the
// `thread` button stays beside this one rather than being replaced: it answers
// a narrower question honestly, and this answers the one a reader has.
//
// Grouped by hop because the reduction already groups by hop; each node
// carries the EDGES that pulled it in, so "why am I seeing this?" is on the
// row rather than inferred from position.
function fbHopLabel(n) {
  return n === 0 ? "the envelope" : n === 1 ? "one hop" : `${n} hops`;
}

// -- inline expansion (JOB #1629) --------------------------------------------
//
// The operator's ask, verbatim shape: clicking a walk node opens that
// envelope's full card DIRECTLY BENEATH the node row — thread reading
// instead of round-tripping the id through the fetch box and losing the
// walk. The #id chip keeps its jump (a different, still-wanted gesture);
// the ▸ toggle is the new one. Expansion ADDS depth and never replaces
// context: the hop grouping, edge labels and withheld counters around the
// card do not move.
//
// **Inline depth is 1, and the cap is VISIBLE** (the counters' own
// convention: a bound the reader cannot see is a bound they will read as
// an absence). Each expanded card carries a `conversation` button that
// re-roots the walk on that envelope — recursion by re-rooting, so the
// walk on screen is always ONE reduction's answer rather than a client-
// assembled tree no reduction ever served.
//
// §9.3: `envelopeCached` rides followRef, so a ref across the seam
// renders as the withheld chip — the same vocabulary as everywhere else —
// and absent-vs-denied stays fused exactly as the server fuses it.
async function toggleThreadNode(id, btn) {
  const pane = $("#ti-" + id);
  if (!pane) return;
  if (!pane.classList.contains("hidden")) {
    pane.classList.add("hidden");
    btn.setAttribute("aria-expanded", "false");
    btn.textContent = "▸ open";
    return;
  }
  pane.classList.remove("hidden");
  btn.setAttribute("aria-expanded", "true");
  btn.textContent = "▾ close";
  if (pane.dataset.loaded) return;
  pane.innerHTML = `<div class="empty">fetching #${esc(String(id))}…</div>`;
  try {
    const e = await envelopeCached(id);
    await registry();
    // S2 (JOB #2199): re-rooting now means "open the thread page here" —
    // the same gesture, landing on the page built for it instead of
    // re-walking inside this pane. `openEnvelope` is no longer a
    // navigation (it opens the #id modal), so this button names the one
    // that is.
    pane.innerHTML = e.withheld
      ? withheldChip(id)
      : envCard(e, `<div class="meta" style="margin-top:8px">
          <button onclick="openThread(${id})">open the thread</button>
          <span style="color:var(--dim);font-size:12px">inline depth is 1 —
          the thread page re-roots the walk here and renders it flat</span>
        </div>`);
    pane.dataset.loaded = "1";
  } catch (err) {
    // followRef already toasted the refusal; the pane says what happened
    // and stays un-cached so the next open retries.
    pane.innerHTML = `<div class="empty">could not fetch #${esc(String(id))} —
      a real failure (not a seam refusal; those render as withheld)</div>`;
  }
}

async function loadConversation() {
  const id = $("#envId").value.trim();
  if (id === "") return;
  // `/neighbourhood/<id>`, NOT `/view/neighbourhood` — the walk is its own
  // endpoint and is absent from `VIEWS`, and it answers FLAT rather than
  // wrapped in `output` like a `/view/` reduction does. Both were wrong in the
  // first draft and the contract test caught them before a browser did, which
  // is the whole argument for asserting a client's data shape server-side.
  const o = await api(`/neighbourhood/${encodeURIComponent(id)}`);
  const hops = (o.hops || []).map((h, i) => {
    const nodes = (h.nodes || []).slice().sort((a, b) => b.id - a.id);
    return `<h4 style="margin:14px 0 6px">${esc(fbHopLabel(h.depth ?? i))}
      <span class="tag">${nodes.length}</span></h4>` + (nodes.length
      ? nodes.map((n) => `<div class="card">
          <div class="meta">
            <button class="ti-toggle" aria-expanded="false"
              onclick="toggleThreadNode(${n.id}, this)">▸ open</button>
            <span class="tag id" onclick="openEnvelope(${n.id})">#${n.id}</span>
            <span class="tag act">${esc(n.type)}</span>
            <span class="tag">${esc(n.ns)}</span>
            ${who(n.author)}
            <span class="edge">${esc((n.edges || []).join(" "))}</span>
          </div>
          <div class="ti-inline hidden" id="ti-${n.id}"></div></div>`).join("")
      : `<div class="fb-empty">nothing at this distance</div>`);
  }).join("");

  // `truncated` renders as a BOUND, never as the end (#10.10's shape, and
  // R67's: a limit the reader cannot see is a limit they will read as an
  // absence). The budget rides with it so the bound is inspectable.
  const bound = o.truncated
    ? `<div class="seal" style="margin-top:10px">more beyond this horizon —
       the walk stopped at ${o.nodes} nodes against a budget of ${o.node_budget}.
       This is where the view ends, not where the conversation does.</div>`
    : "";
  const note = o.withheld_note
    ? `<div class="fb-withheld">${esc(o.withheld_note)}</div>` : "";
  $("#envView").innerHTML = `<h3>conversation around #${esc(String(o.root))}
    <span class="tag">depth ${o.depth}</span>
    <span class="tag">${o.nodes} nodes</span></h3>
    ${hops || `<div class="fb-empty">nothing cites this and it cites nothing —
      an envelope with no conversation around it yet.</div>`}
    ${bound}${fbWithheld(o, "this walk")}${note}`;
}
