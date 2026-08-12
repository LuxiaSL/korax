"use strict";
// tabs/graph.js — the graph tab.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: TYPE_COLOR, G, loadGraph, laneOf, drawGraph, selectGraphNode.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// -- graph (#operator, 2026-08-10): the board as a diagram ----------------------
// x is log order, lanes are namespaces, edges point back in time. Click a
// node: ancestors (what it grew from) warm, descendants (what grew from
// it) cold. The log is already a DAG — this only draws what refs assert.

const TYPE_COLOR = {
  JOB: "#7c8cff", CLAIM: "#9a6cf0", FINDING: "#58c08a", WARN: "#e0b054",
  POLICY: "#e06c75", STAMP: "#e06c75", OPEN: "#5ab6d8", NOTE: "#8b90a0",
  HANDOVER: "#c9a9e8", PROPOSAL: "#58c08a", ACK: "#4a4f5d",
  SUPERSEDE: "#e0b054", PIN: "#e06c75", BESIDE: "#8b90a0", UNSEAL: "#e06c75",
};

let G = null; // {envs, byId, children, order}

async function loadGraph() {
  await registry();
  const nsFilter = $("#graphNs").value.trim();
  const page = await api("/read?limit=5000");
  const envs = page.envelopes.filter((e) => !nsFilter || e.ns.startsWith(nsFilter));
  const byId = new Map(envs.map((e) => [e.id, e]));
  const children = new Map();
  for (const e of envs) for (const r of (e.refs || []))
    if (byId.has(r.id)) (children.get(r.id) || children.set(r.id, []).get(r.id)).push(e.id);
  G = { envs, byId, children, order: new Map(envs.map((e, i) => [e.id, i])) };
  drawGraph(null);
}

function laneOf(ns) {
  const segs = ns.split("/").filter(Boolean);
  return "/" + segs.slice(0, 2).join("/");
}

function drawGraph(selected) {
  if (!G) return;
  const DX = 26, DY = 46, R = 7, PADX = 30, PADY = 34;
  const lanes = [];
  for (const e of G.envs) { const l = laneOf(e.ns); if (!lanes.includes(l)) lanes.push(l); }
  const laneY = new Map(lanes.map((l, i) => [l, PADY + i * DY]));
  const W = PADX * 2 + G.envs.length * DX, H = PADY * 2 + lanes.length * DY;

  // reachability for the selected node
  let past = new Set(), future = new Set();
  if (selected != null) {
    const walk = (start, step, out) => {
      const q = [start];
      while (q.length) {
        const id = q.pop();
        for (const nxt of step(id)) if (!out.has(nxt)) { out.add(nxt); q.push(nxt); }
      }
    };
    walk(selected, (id) => (G.byId.get(id)?.refs || []).map((r) => r.id).filter((i) => G.byId.has(i)), past);
    walk(selected, (id) => G.children.get(id) || [], future);
  }
  const dim = (id) => selected != null && id !== selected && !past.has(id) && !future.has(id);

  const pos = (id) => {
    const e = G.byId.get(id);
    return [PADX + G.order.get(id) * DX, laneY.get(laneOf(e.ns))];
  };
  let edges = "", nodes = "";
  for (const e of G.envs) {
    const [x2, y2] = pos(e.id);
    for (const r of (e.refs || [])) {
      if (!G.byId.has(r.id)) continue;
      const [x1, y1] = pos(r.id);
      // an edge lights when it lies on the selected node's lineage:
      // (selected|past) → past is the warm chain, future → (selected|future) the cold one
      const pastLit = (e.id === selected || past.has(e.id)) && past.has(r.id);
      const futureLit = future.has(e.id) && (r.id === selected || future.has(r.id));
      const lit = selected != null && (pastLit || futureLit);
      const stroke = selected == null ? "#3a3f4d" : lit ? "#7c8cff" : "#23262e";
      const mid = (x1 + x2) / 2, arc = y1 === y2 ? y1 - 14 - Math.min(30, (x2 - x1) / 8) : (y1 + y2) / 2;
      edges += `<path d="M${x1},${y1} Q${mid},${arc} ${x2},${y2}" fill="none" stroke="${stroke}" stroke-width="1.2" opacity="${selected == null ? .55 : lit ? .9 : .25}"/>`;
    }
  }
  for (const e of G.envs) {
    const [x, y] = pos(e.id);
    const c = TYPE_COLOR[e.type] || "#8b90a0";
    const halo = e.id === selected ? `<circle cx="${x}" cy="${y}" r="${R + 4}" fill="none" stroke="#fff" stroke-width="1.5"/>`
      : past.has(e.id) ? `<circle cx="${x}" cy="${y}" r="${R + 3}" fill="none" stroke="#e0b054" stroke-width="1.2"/>`
      : future.has(e.id) ? `<circle cx="${x}" cy="${y}" r="${R + 3}" fill="none" stroke="#5ab6d8" stroke-width="1.2"/>` : "";
    const disp = REG && REG[e.author] ? REG[e.author].display : e.author;
    nodes += `<g style="cursor:pointer" onclick="event.stopPropagation();selectGraphNode(${e.id})" opacity="${dim(e.id) ? .25 : 1}">
      ${halo}<circle cx="${x}" cy="${y}" r="${R}" fill="${c}"/>
      <title>#${e.id} ${esc(e.type)} — ${esc(disp)} — ${esc(e.ns)}</title>
      <text x="${x}" y="${y - R - 4}" text-anchor="middle" font-size="8" fill="var(--dim)" font-family="var(--mono)">${e.id}</text></g>`;
  }
  $("#graphLanes").innerHTML = lanes.map((l) =>
    `<div style="height:${DY}px;display:flex;align-items:center;padding:0 8px 0 2px;margin-top:${l === lanes[0] ? PADY - DY / 2 : 0}px">${esc(l)}</div>`).join("");
  $("#graphScroll").innerHTML =
    `<svg width="${W}" height="${H}" onclick="selectGraphNode(null)">${edges}${nodes}</svg>`;
  if (selected != null) {
    const e = G.byId.get(selected);
    $("#graphDetail").innerHTML = envCard(e,
      `<div style="margin-top:8px"><h3 style="margin:8px 0 4px">grew from (${past.size})</h3>${idChips([...past].sort((a, b) => a - b))}
       <h3 style="margin:8px 0 4px">grew into (${future.size})</h3>${idChips([...future].sort((a, b) => a - b))}</div>`);
  } else {
    $("#graphDetail").innerHTML = `<div class="empty">select an envelope to see its lineage</div>`;
  }
}

function selectGraphNode(id) { drawGraph(id); }
$("#graphLoad").addEventListener("click", loadGraph);
