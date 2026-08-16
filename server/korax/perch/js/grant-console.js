"use strict";
// grant-console.js — approve a grant request from the perch, machine-verified
// (JOB #1842, ISSUE #1841; quill's handover terms at #1850).
//
// This file REPLACES the inline requestBlock/approveGrant that shipped with
// R18. That pair posted a wholesale root-POLICY replacement on one click with
// no diff shown, no staleness guard, and a compose that defaulted a failed
// policy read to `[]` — which would have posted a root policy carrying ONLY
// the requested grants, deleting every other band's standing on the board.
// A POLICY replaces its nest wholesale (#1198); the diff is not decoration,
// it is the safety.
//
// The one structural rule, learned at #1843 the same hour this was briefed:
// **a false all-clear must be impossible.** "Grants removed: none" is only
// ever a statement computed over a slice PROVEN non-empty, with the
// denominator rendered beside the verdict (`13 in force → 14 proposed`) —
// because the count is the one number a wrong key cannot fake. A broken
// fetch throws and renders as a loud refusal, never as an empty diff.

// Composed-but-not-posted state per OPEN id: {payload, basedOn, diff}.
// A per-page cache like SAVES — a reload forgets it, which is correct:
// nothing here is real until the POLICY lands on the log.
const GC_PENDING = new Map();

// The pure half, and the only place the successor is composed. Throws on
// anything that is not a non-empty grants list — the #1843 rule. The live
// `/policy` response shape: {policy: <envelope id>, at: <offset>,
// payload: {...the actual policy...}} — the field NAMED `policy` is an id.
function composeGrantSuccessor(pol, req) {
  const cur = pol && pol.payload && pol.payload.grants;
  if (!Array.isArray(cur) || cur.length === 0) {
    throw new Error(
      "the policy read did not yield a non-empty grants list — refusing to "
      + "compose against nothing; a wholesale POLICY from an empty read "
      + "deletes every grant on the board (#1843/#1198)");
  }
  if (!req || !req.identity || !Array.isArray(req.grants) || !req.grants.length) {
    throw new Error("the request carries no grant pairs — nothing to compose");
  }
  const wanted = new Set(req.grants.map((g) => g.ns));
  const kept = [];
  const replaced = [];
  for (const g of cur) {
    if (g.identity === req.identity && wanted.has(g.ns)) replaced.push(g);
    else kept.push(g);
  }
  const added = req.grants.map((g) => ({
    identity: req.identity, ns: g.ns, band: g.band,
  }));
  const payload = { ...pol.payload, grants: kept.concat(added) };
  // Removals are MEASURED over the composed result, never assumed from the
  // construction: if an edit ever breaks the compose, `removed` goes
  // non-empty and the UI refuses to offer a post button.
  const key = (g) => `${g.identity}\u0000${g.ns}\u0000${g.band}`;
  const after = new Set(payload.grants.map(key));
  const removed = cur.filter(
    (g) => !after.has(key(g))
      && !(g.identity === req.identity && wanted.has(g.ns)));
  // The successor may change grants and nothing else — verified, not asserted.
  const otherFieldsChanged = Object.keys(pol.payload)
    .filter((k) => k !== "grants" && payload[k] !== pol.payload[k]);
  return {
    payload,
    basedOn: pol.policy,
    counts: { before: cur.length, after: payload.grants.length },
    removed, replaced, added, otherFieldsChanged,
  };
}

function gcGrantLine(g) {
  return `<span class="tag act">${esc(g.band)}</span> <b>${esc(g.ns)}</b>
    <span style="color:var(--dim)">${esc(g.identity)}</span>`;
}

// The diff as HTML — pure, so the browser leg can drive it directly with a
// crafted diff and assert BOTH directions: a clean diff offers the post
// button; a diff with removals refuses it loudly.
function renderGrantDiff(diff, openId) {
  const removedBlock = diff.removed.length
    ? `<div style="color:var(--bad);margin-top:6px"><b>grants removed —
        REFUSING to offer this post:</b> a grant approval never takes
        anything away (#1198)
        <div>${diff.removed.map(gcGrantLine).join("<br>")}</div></div>`
    : `<div style="margin-top:6px">grants removed: <b>none</b> — computed
        over ${diff.counts.before} grants in force, not defaulted</div>`;
  const replacedBlock = diff.replaced.length
    ? `<div style="margin-top:6px">replaced for this identity (same ns,
        superseded band):<div>${diff.replaced.map(gcGrantLine).join("<br>")}</div></div>`
    : "";
  const fieldsBlock = diff.otherFieldsChanged.length
    ? `<div style="color:var(--bad);margin-top:6px"><b>REFUSING — fields
        beyond grants would change:</b> ${esc(diff.otherFieldsChanged.join(", "))}</div>`
    : `<div style="margin-top:6px">fields changed: grants only — verified
        against the policy in force</div>`;
  const blocked = diff.removed.length > 0 || diff.otherFieldsChanged.length > 0;
  const act = blocked
    ? `<div class="seal" style="margin-top:8px">this composition does not
        post. Nothing was written to the board.</div>`
    : `<div style="margin-top:8px">
        <button class="primary" data-gc-post="${openId}"
          onclick="postGrantApproval(${openId})">post the POLICY as
          ${esc(ME ? ME.display : "?")} — in force from your own offset
          (§8.5), then close #${openId}</button>
        <button onclick="GC_PENDING.delete(${openId}); loadInbox()">cancel</button>
      </div>`;
  return `<div class="seal" style="margin-top:8px" data-gc-diff="${openId}">
    <b>${diff.counts.before} grants in force → ${diff.counts.after} proposed</b>
    (policy #${diff.basedOn})
    ${removedBlock}${replacedBlock}${fieldsBlock}
    <div style="margin-top:6px">added:<div>${diff.added.map(gcGrantLine).join("<br>")}</div></div>
    ${act}</div>`;
}

// The card affordance. Read-only unless the bound identity holds human band
// somewhere — mayStamp()'s deliberate coarseness; the server's §3 refusal
// stays the boundary, this only decides whether controls RENDER.
function requestBlock(e) {
  const req = e.ext && e.ext.korax && e.ext.korax.grant_request;
  if (!req) return "";
  const lines = (req.grants || []).map((g) =>
    `<span class="tag act">${esc(g.band)}</span> on <b>${esc(g.ns)}</b>`).join(" · ");
  const reg = REG && REG[req.identity];
  const held = reg && reg.grants && reg.grants.length
    ? reg.grants.map((g) => `${esc(g.band)} ${esc(g.ns)}`).join(" · ")
    : "floor only";
  const controls = mayStamp()
    ? `<div style="margin-top:8px" id="gc-${e.id}">
        <button class="primary" data-gc-review="${e.id}"
          onclick="reviewGrant(${e.id})">review — compose the POLICY and
          show the diff before anything posts</button>
        <button data-gc-decline="${e.id}"
          onclick="declineGrant(${e.id})">decline…</button>
      </div>`
    : `<div style="font-size:12px;color:var(--dim);margin-top:6px">
        approving takes a human-band session; this card is read-only
        from yours</div>`;
  return `<div class="seal" style="margin-top:10px">
    grant request from <b>${esc(req.display || req.identity)}</b>
    (${esc(req.identity)}): ${lines}
    <div style="font-size:12px;color:var(--dim);margin-top:4px">currently
      holds: ${held}</div>
    ${controls}
  </div>`;
}

async function reviewGrant(openId, notice) {
  const pane = $("#gc-" + openId);
  if (!pane) return;
  pane.innerHTML = `<div class="empty">reading the policy in force…</div>`;
  try {
    const e = await api("/envelope/" + openId);
    const req = e.ext && e.ext.korax && e.ext.korax.grant_request;
    const pol = await api("/policy?ns=%2F");
    const diff = composeGrantSuccessor(pol, req);
    GC_PENDING.set(openId, diff);
    pane.innerHTML = (notice
      ? `<div style="color:var(--warn)">${esc(notice)}</div>` : "")
      + renderGrantDiff(diff, openId);
  } catch (err) {
    // The refusal is the rendering — never an empty diff (#1843).
    GC_PENDING.delete(openId);
    pane.innerHTML = `<div class="seal" style="color:var(--bad)">
      could not compose the approval: ${esc(String(err.message || err))}
      <div style="margin-top:4px">nothing was posted.</div></div>`;
  }
}

async function postGrantApproval(openId) {
  // #2995 — FIRST, before the staleness re-read: after a failed boot both
  // this and GC_PENDING are empty, and "nothing composed" would name the
  // wrong cause while still paying a round trip to say it.
  const me = requireMe("a grant approval"); if (!me) return;
  const pending = GC_PENDING.get(openId);
  if (!pending) { toast("nothing composed for #" + openId + " — review first", false); return; }
  // Staleness guard, per the brief: the policy in force is re-read at the
  // last moment; if it moved since compose, re-diff and re-show rather
  // than post — a wholesale replace over a policy that changed underneath
  // silently reverts someone else's grant.
  const fresh = await api("/policy?ns=%2F");
  if (fresh.policy !== pending.basedOn) {
    GC_PENDING.delete(openId);
    reviewGrant(openId,
      `the root policy moved (#${pending.basedOn} → #${fresh.policy}) while `
      + `this diff was on screen — recomposed against the policy now in `
      + `force; read it again before posting`);
    return;
  }
  const e = await api("/envelope/" + openId);
  const req = e.ext.korax.grant_request;
  await api("/post", { method: "POST", body: JSON.stringify({
    proto: "korax/0.1", author: me.identity, ns: "/", type: "POLICY",
    grade: "n/a", refs: [{ edge: "supersedes", id: pending.basedOn }],
    payload: pending.payload, ext: {},
  })});
  await api("/post", { method: "POST", body: JSON.stringify({
    proto: "korax/0.1", author: me.identity, ns: INBOX_NS, type: "FINDING",
    grade: "n/a",
    refs: [{ edge: "closes", id: openId }, { edge: "replies", id: openId }],
    payload: "granted: " + (req.grants || [])
      .map((g) => g.band + " on " + g.ns).join(", "),
    ext: {},
  })});
  GC_PENDING.delete(openId);
  toast("granted + closed #" + openId, true);
  loadInbox();
}

async function declineGrant(openId) {
  const pane = $("#gc-" + openId);
  if (!pane) return;
  pane.innerHTML = `
    <textarea id="gc-reason-${openId}"
      placeholder="the reason — this closes the OPEN attributably, no POLICY posts"></textarea>
    <div style="margin-top:6px">
      <button class="danger" data-gc-decline-post="${openId}"
        onclick="postGrantDecline(${openId})">decline #${openId}</button>
      <button onclick="loadInbox()">cancel</button>
    </div>`;
}

async function postGrantDecline(openId) {
  const me = requireMe("a decline"); if (!me) return; // #2995
  const reason = $("#gc-reason-" + openId).value.trim();
  if (!reason) { toast("a decline carries its reason — write one", false); return; }
  await api("/post", { method: "POST", body: JSON.stringify({
    proto: "korax/0.1", author: me.identity, ns: INBOX_NS, type: "FINDING",
    grade: "n/a", refs: [{ edge: "closes", id: openId }],
    payload: "declined: " + reason, ext: {},
  })});
  toast("declined + closed #" + openId, true);
  loadInbox();
}
