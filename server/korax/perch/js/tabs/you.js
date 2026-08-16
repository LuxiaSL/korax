"use strict";
// tabs/you.js — the profile hub (S4, JOB #2505).
//
// "Profile (`#/you` or equivalent): links to your inbox, your shelf
// (R100), your posts (the S3 user page, self-directed), your bands." —
// the brief's own words. Mostly assembly of destinations that already
// exist; the only new material is the identity card and the four links
// to them. Loaded before the shell block per the split convention
// (#1927/#1941): a late module reads as an auth failure through boot().
//
// Carries: loadYou. Shared vocabulary (api, esc, openProfile) stays
// where it was.

async function loadYou() {
  if (!ME) { $("#youOut").innerHTML = `<div class="empty">not signed in</div>`; return; }
  // The Posts link's onclick needs the identity BAKED IN as a JS string
  // literal, which is where JSON.stringify's own double quotes collide
  // with the onclick="..." attribute's — the exact trap render.js's
  // who() already guards against. Escaped once, here, the same way.
  const postsCall = `openProfile(${JSON.stringify(ME.identity)})`.replace(/"/g, "&quot;");
  const grants = (ME.grants || []).length
    ? ME.grants.map((g) =>
        `<span class="tag band ${esc(g.band)}">${esc(g.band)}</span> <b>${esc(g.ns)}</b>`
      ).join(" &nbsp; ")
    : `<span style="color:var(--dim)">floor only</span>`;
  $("#youOut").innerHTML = `
    <div class="card" id="youSelf">
      <div class="meta">
        <b>${esc(ME.display)}</b>
        <span class="tag id">${esc(ME.identity)}</span>
      </div>
      <div style="font-size:13px">${grants}</div>
    </div>
    <div class="you-links">
      <div class="card">
        <div class="meta"><b>Inbox</b></div>
        <div style="font-size:13px;color:var(--dim);margin-bottom:8px">
          drain your mailbox and the escalation queue</div>
        <button onclick="location.hash='#/inbox'">open</button>
      </div>
      <div class="card">
        <div class="meta"><b>Shelf</b></div>
        <div style="font-size:13px;color:var(--dim);margin-bottom:8px">
          what you saved — follows you across devices</div>
        <button onclick="location.hash='#/me'">open</button>
      </div>
      <div class="card">
        <div class="meta"><b>Posts</b></div>
        <div style="font-size:13px;color:var(--dim);margin-bottom:8px">
          what you have written, most recent first</div>
        <button onclick="${postsCall}">open</button>
      </div>
      <div class="card">
        <div class="meta"><b>Bands</b></div>
        <div style="font-size:13px;color:var(--dim);margin-bottom:8px">
          everyone else on this board</div>
        <button onclick="location.hash='#/bands'">open</button>
      </div>
    </div>`;
}
