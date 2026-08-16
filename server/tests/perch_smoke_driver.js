// server/tests/perch_smoke_driver.js — JOB #1615 (ISSUE #1597), rewritten
// by JOB #1969 (S1, the router): the TABS list is a ROUTES list now, per
// the forum base's own acceptance line.
//
// Drives a REAL headless Chrome over CDP — no playwright, no selenium,
// nothing installed; Node 22's built-in WebSocket speaks the protocol. A
// simulated DOM can lie in exactly the dimension this guard exists for (a
// called-but-undefined identifier is a runtime ReferenceError only in a
// real engine), and S1 adds the dimensions a router makes real: the URL
// as state, the back button, and a cold load of a deep link.
//
// Four phases, each reported separately so Python can assert them apart:
//   1 warm walk      every route navigated by hash on a live page
//   2 back traversal history.back() through the walk, hash and visible
//                    section checked at every step
//   3 cold loads     a fresh Page.navigate per route — the deep link is
//                    the first thing the page ever sees
//   4 click census   the markup-bound symbols #1941 measured, each
//                    exercised through a real click, with its effect
//                    asserted (not just "no exception")
//
// Invoked by test_perch_smoke.py as a subprocess. Prints one JSON object
// to stdout; Python does the asserting.
const CDP = `http://127.0.0.1:${process.argv[2]}`;
const ORIGIN = process.argv[3];
const TOKEN = process.argv[4];
const PROBE_ENVELOPE_ID = process.argv[5];
const THREAD_ROOT_ID = process.argv[6];

// route -> the section that must be visible, and the DOM read that proves
// the view rendered SOMETHING (the primary container its loader writes).
const ROUTES = [
  { hash: "#/inbox",   tab: "inbox",
    probe: `($("#inboxList").textContent + $("#inboxMessages").textContent + $("#inboxRest").textContent).trim().length` },
  { hash: "#/ledger",  tab: "ledger",  probe: `$("#ledgerAll").textContent.trim().length` },
  { hash: "#/graph",   tab: "graph",   probe: `$("#graphLanes").textContent.trim().length` },
  { hash: "#/speak",   tab: "speak",   probe: `$("#dmTo").options.length` },
  { hash: "#/onboard", tab: "onboard", probe: `$("#onboardList").textContent.trim().length` },
  { hash: "#/feed",    tab: "feed",
    probe: `$("#feedList").textContent.trim().length + $("#feedMeta").textContent.trim().length` },
  { hash: "#/browse",  tab: "browse",  probe: `$("#browseList").textContent.trim().length` },
  { hash: "#/nest",    tab: "nest",    probe: `$("#nestOut").textContent.trim().length` },
  { hash: "#/flight",  tab: "flight",
    probe: `$("#fbJobs").textContent.trim().length + $("#fbTiles").textContent.trim().length` },
  { hash: "#/bands",   tab: "bands",   probe: `$("#bandsList").textContent.trim().length` },
  // S4 (JOB #2505): the profile hub. Probes the identity card + link
  // grid, which loadYou() always renders for a bound identity.
  { hash: "#/you",     tab: "you",     probe: `$("#youOut").textContent.trim().length` },
  // the parameterized shapes, exercised with real params: a cold #/e/<id>
  // must LOAD the conversation, which the old tab walk could not express.
  // S2 (JOB #2199) moved this route's destination from the single-envelope
  // tab to the thread page; the URL shape is deliberately unchanged.
  { hash: `#/e/${PROBE_ENVELOPE_ID}`, tab: "thread", probe: `$("#threadList").textContent.trim().length` },
  // ...and the raw envelope surface at its own name, which #/e/<id> used
  // to cover. It auto-loads nothing by design — it is a fetch box and four
  // reductions — so the probe asserts its CONTROLS are there, which is the
  // real invariant for a tool surface with no loader.
  { hash: "#/envelope", tab: "envelope",
    probe: `document.querySelectorAll("#tab-envelope button").length` },
  // #/me is the ruled name for the shelf; #/you (above) is S4's separate
  // profile hub — the two answer different questions.
  { hash: "#/me",      tab: "saved",   probe: `$("#savedList").textContent.trim().length` },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const list = await (await fetch(`${CDP}/json/list`)).json();
  const page = list.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));

  let id = 0;
  const pending = new Map();
  const errors = []; // {where, kind, detail}
  let where = "(boot)";
  const call = (method, params) =>
    new Promise((res) => {
      pending.set(++id, res);
      ws.send(JSON.stringify({ id, method, params }));
    });
  const evil = async (expression) =>
    (await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }))
      .result?.value;

  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); return; }
    if (m.method === "Runtime.exceptionThrown")
      errors.push({ where, kind: "exception",
        detail: m.params.exceptionDetails.exception?.description
          || m.params.exceptionDetails.text });
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error")
      errors.push({ where, kind: "console",
        detail: m.params.args.map((a) => a.value ?? a.description).join(" ") });
  };

  await call("Runtime.enable", {});
  await call("Page.enable", {});
  await call("Page.navigate", { url: ORIGIN });
  await sleep(1500);
  await evil(`localStorage.setItem('koraxToken', ${JSON.stringify(TOKEN)}); 'ok'`);
  await call("Page.navigate", { url: ORIGIN });
  await sleep(2000);

  // The route list must cover the shell's own nav — a shell edit that adds
  // a tab without a route fails loudly rather than silently checking fewer
  // views than exist.
  //
  // S2 (JOB #2199) RELAXED THE COUNT AND TIGHTENED THE CHECK. This was
  // `navTabs.length !== ROUTES.length`, which was a cheap proxy for "routes
  // and nav are one-to-one" and held only while every routed view had a nav
  // button. The thread page is a routed view with NO nav button on purpose
  // — you reach a conversation by following a citation, not by picking it
  // off a bar — so the count now disagrees for a legitimate reason. What
  // replaces it is stronger in the direction that matters: every route's
  // tab must name a REAL section, so a typo in ROUTES still fails here
  // instead of quietly probing a view that does not exist.
  const navTabs = JSON.parse(await evil(
    `JSON.stringify([...document.querySelectorAll("nav button")].map(b => b.dataset.tab))`));
  const sectionTabs = JSON.parse(await evil(
    `JSON.stringify([...document.querySelectorAll("main section")].map(s => s.id.replace(/^tab-/, "")))`));
  const routeTabs = ROUTES.map((r) => r.tab);
  const routeMismatch = !navTabs.every((t) => routeTabs.includes(t))
    || !routeTabs.every((t) => sectionTabs.includes(t));

  const visibleTab = () => evil(
    `[...document.querySelectorAll("main section")].filter(s => !s.classList.contains("hidden")).map(s => s.id).join(",")`);

  const report = { navTabs, routeMismatch, routes: {}, backTrail: [],
                   cold: {}, census: {}, errors: [] };

  // ── phase 1: the warm walk ────────────────────────────────────────────
  for (const r of ROUTES) {
    where = `warm ${r.hash}`;
    await evil(`location.hash = ${JSON.stringify(r.hash)}; 'ok'`);
    await sleep(1200);
    if (r.tab === "nest") {
      await evil(`$("#nestNs").value = "/commons/rakes"; $("#nestLoad").click(); 'ok'`);
      await sleep(1200);
    }
    const shown = await visibleTab();
    const value = await evil(r.probe);
    report.routes[r.hash] = (shown === "tab-" + r.tab) ? value : 0;
  }

  // the inboxDisposition census rides the inbox render (it is a lexical
  // call since S0, not a markup binding — #1941's record, corrected by
  // #1960): the seeded OPEN is untouched, so the chip must say so. Read
  // it back from the warm walk before phase-4's close mutates the inbox.
  where = "census inboxDisposition";
  await evil(`location.hash = "#/inbox"; 'ok'`); await sleep(1200);
  report.census.inboxDisposition = await evil(
    `$("#inboxList").textContent.includes("untouched") || $("#inboxList").textContent.includes("engaged")`);

  // ── phase 2: the back button ──────────────────────────────────────────
  // The walk above pushed ROUTES in order, then #/inbox. Walking back must
  // revisit them in reverse, hash and visible section agreeing at each
  // step — this is the history integrity the echo-suppression could break
  // silently if it ever suppressed a USER navigation.
  const trail = [...ROUTES.map((r) => r), { hash: "#/inbox", tab: "inbox" }];
  for (let i = trail.length - 2; i >= 0; i--) {
    where = `back to ${trail[i].hash}`;
    await evil(`history.back(); 'ok'`);
    await sleep(900);
    const gotHash = await evil(`location.hash`);
    const shown = await visibleTab();
    report.backTrail.push({ expected: trail[i].hash, gotHash,
      ok: gotHash === trail[i].hash && shown === "tab-" + trail[i].tab });
  }

  // ── phase 3: cold deep-loads ──────────────────────────────────────────
  for (const r of ROUTES) {
    where = `cold ${r.hash}`;
    await call("Page.navigate", { url: `${ORIGIN}/${r.hash}` });
    await sleep(1800);
    if (r.tab === "nest") {
      await evil(`$("#nestNs").value = "/commons/rakes"; $("#nestLoad").click(); 'ok'`);
      await sleep(1200);
    }
    const shown = await visibleTab();
    const value = await evil(r.probe);
    report.cold[r.hash] = (shown === "tab-" + r.tab) ? value : 0;
  }

  // ── phase 4: the click census (#1941's markup-bound symbols) ─────────
  // Each symbol is reached the way a person reaches it — a real click on
  // rendered markup — and judged by its EFFECT. Mutations land on the
  // throwaway seeded board.

  // openEnvelope: a #id chip anywhere; browse renders eleven of them.
  // S2 (JOB #2199) changed what the chip DOES — it opens the modal now
  // rather than navigating — so the effect asserted here changed with it:
  // the dialog must be open and the URL must NOT have moved. The old
  // assertion (hash starts #/e/, envelope tab shown) would now be a test
  // of the behaviour the ruling replaced.
  where = "census openEnvelope";
  await call("Page.navigate", { url: `${ORIGIN}/#/browse` });
  await sleep(1800);
  const hashBeforeChip = await evil(`location.hash`);
  await evil(`document.querySelector('#browseList .tag.id').click(); 'ok'`);
  await sleep(1200);
  report.census.openEnvelope =
    (await evil(`$("#envModal").open === true`))
    && (await evil(`location.hash`)) === hashBeforeChip
    && !!(await evil(`$("#envModalMeta").textContent.trim().length`));
  // and its "go to its thread" action is the navigation that used to be
  // the chip's whole behaviour — still reachable, now asked for
  where = "census openThread";
  await evil(`[...document.querySelectorAll('#envModal button')]
    .find(b => b.textContent.includes("go to its thread")).click(); 'ok'`);
  await sleep(2000);
  report.census.openThread =
    (await evil(`location.hash.startsWith("#/e/")`))
    && (await visibleTab()) === "tab-thread"
    && !!(await evil(`$("#threadList").textContent.trim().length`));

  // openProfile: the bands list's profile button; the URL must follow
  where = "census openProfile";
  await call("Page.navigate", { url: `${ORIGIN}/#/bands` });
  await sleep(1800);
  await evil(`[...document.querySelectorAll('#bandsList button')].find(b => b.textContent === 'profile').click(); 'ok'`);
  await sleep(1200);
  report.census.openProfile =
    (await evil(`location.hash.startsWith("#/band/")`))
    && !!(await evil(`$("#bandProfile").textContent.trim().length`));

  // ...and the profile's back control routes to #/bands and restores the list
  where = "census profileBack";
  await evil(`[...document.querySelectorAll('#bandProfile button')].find(b => b.textContent.includes('all bands')).click(); 'ok'`);
  await sleep(1200);
  report.census.profileBack =
    (await evil(`location.hash`)) === "#/bands"
    && !!(await evil(`$("#bandsList").textContent.trim().length`));

  // selectGraphNode: a node in the SVG; the detail pane must fill
  where = "census selectGraphNode";
  await call("Page.navigate", { url: `${ORIGIN}/#/graph` });
  await sleep(2000);
  await evil(`document.querySelector('#graphScroll svg g').dispatchEvent(new MouseEvent('click', {bubbles: true})); 'ok'`);
  await sleep(1000);
  report.census.selectGraphNode = !!(await evil(`$("#graphDetail").textContent.trim().length`));

  // ackAll: the operator has unread canon by construction (fresh identity,
  // seeded pins); acking must empty the list, not merely not throw
  where = "census ackAll";
  await call("Page.navigate", { url: `${ORIGIN}/#/onboard` });
  await sleep(1800);
  await evil(`[...document.querySelectorAll('#onboardList button')].find(b => b.textContent.includes('ack')).click(); 'ok'`);
  await sleep(1500);
  report.census.ackAll = await evil(`$("#onboardList").textContent.includes("nothing unread")`);

  // stamp: the envelope page offers the operator a stamp; after the click
  // the reloaded page must show the stamp as a fact, not an offer
  // S2: #/e/<id> is the thread now, so the raw envelope surface is reached
  // by its own route and its fetch box — which is what a person does too.
  where = "census stamp";
  await call("Page.navigate", { url: `${ORIGIN}/#/envelope` });
  await sleep(1500);
  await evil(`$("#envId").value = "${PROBE_ENVELOPE_ID}"; $("#envLoad").click(); 'ok'`);
  await sleep(1800);
  await evil(`document.querySelector('#envOut button[onclick^="stamp("]').click(); 'ok'`);
  await sleep(1500);
  report.census.stamp = await evil(`$("#envOut").textContent.includes("stamped by")`);

  // toggleThreadNode + fbHopLabel: the conversation walk renders hop
  // labels (fbHopLabel is a lexical call in that render since S0) and
  // ▸ toggles; opening one must expand its inline pane
  // S2: reached through the raw surface's own route and fetch box, since
  // #/e/<id> is the thread page now. The walk-with-inline-expansion this
  // exercises survives beside the thread page and answers a narrower
  // question (#881's ruling did not delete `thread`, and this did not
  // delete the walk view).
  where = "census toggleThreadNode";
  await call("Page.navigate", { url: `${ORIGIN}/#/envelope` });
  await sleep(1500);
  await evil(`$("#envId").value = "${THREAD_ROOT_ID}"; $("#envLoad").click(); 'ok'`);
  await sleep(1500);
  await evil(`$("#envConvo").click(); 'ok'`);
  await sleep(1500);
  report.census.fbHopLabel = !!(await evil(`$("#envView").textContent.trim().length`));
  await evil(`document.querySelector('#envView button.ti-toggle').click(); 'ok'`);
  await sleep(1500);
  report.census.toggleThreadNode = await evil(
    `document.querySelector('#envView button.ti-toggle').getAttribute('aria-expanded') === 'true'
     && !document.querySelector('#envView .ti-inline').classList.contains('hidden')`);

  // closeOpen: fill the resolution, close, and the open must LEAVE the
  // inbox on its own reload. Last, because it mutates what inbox renders.
  // The card's PRESENCE is asserted first — "no close textarea afterward"
  // is satisfied vacuously by an inbox that never rendered one, which is
  // exactly how the seed's scoped-grant defect hid from the old probe
  // (#1843: never green-by-empty-read).
  where = "census closeOpen";
  await call("Page.navigate", { url: `${ORIGIN}/#/inbox` });
  await sleep(1800);
  const hadOpenCard = await evil(`!!document.querySelector('[id^="close-"]')`);
  await evil(`document.querySelector('[id^="close-"]').value = "smoke: closed by the census"; 'ok'`);
  await evil(`document.querySelector('#inboxList button.danger').click(); 'ok'`);
  await sleep(1800);
  report.census.closeOpen = hadOpenCard
    && await evil(`!document.querySelector('[id^="close-"]')`);

  where = "(teardown)";
  report.errors = errors;
  console.log(JSON.stringify(report));
  ws.close();
  process.exit(errors.length ? 1 : 0);
}
main().catch((e) => { console.error("DRIVER FAILED:", e); process.exit(2); });
