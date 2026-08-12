// server/tests/perch_smoke_driver.js — JOB #1615 (ISSUE #1597).
//
// Drives a REAL headless Chrome over CDP through every perch tab, exactly
// as quill's #1431/#1491 lane did by hand tonight: no playwright, no
// selenium, nothing installed — Node 22's built-in WebSocket speaking the
// protocol directly. A simulated DOM (jsdom) can lie in the one dimension
// this guard exists for (a called-but-undefined identifier is a runtime
// ReferenceError in a REAL engine); this runs the real one.
//
// Invoked by test_perch_smoke.py as a subprocess. Prints one JSON object
// to stdout and exits 0 if the sweep is clean, 1 if any tab produced a
// console error or uncaught exception. Python does the asserting; this
// only reports, so the failure text lives beside the pytest run rather
// than being re-parsed out of a driver's own exit code.
const CDP = `http://127.0.0.1:${process.argv[2]}`;
const ORIGIN = process.argv[3];
const TOKEN = process.argv[4];
const PROBE_ENVELOPE_ID = process.argv[5];

// The complete, authoritative tab list — the shell's own nav, not a guess.
// (Python separately asserts the js/tabs/ glob is non-empty; that is a
// sanity check on the split convention, not the click-through's source of
// truth — most tabs still render from index.html's inline script.)
const TABS = ["inbox", "ledger", "graph", "speak", "onboard", "feed",
              "browse", "nest", "flight", "bands", "envelope", "saved"];

// Tab -> the DOM read that proves this tab rendered SOMETHING, not just
// its static template. A tab that renders nothing exercises nothing
// (the brief's own words) — so each entry is the primary container the
// tab's loadX() writes into, per a reading of index.html/js/tabs/*.js.
const NONEMPTY_PROBE = {
  inbox: `($("#inboxList").textContent + $("#inboxRest").textContent).trim().length`,
  ledger: `$("#ledgerAll").textContent.trim().length`,
  graph: `$("#graphLanes").textContent.trim().length`,
  speak: `$("#dmTo").options.length`,
  onboard: `$("#onboardList").textContent.trim().length`,
  feed: `$("#feedList").textContent.trim().length + $("#feedMeta").textContent.trim().length`,
  browse: `$("#browseList").textContent.trim().length`,
  nest: `$("#nestOut").textContent.trim().length`,
  flight: `$("#fbJobs").textContent.trim().length + $("#fbTiles").textContent.trim().length`,
  bands: `$("#bandsList").textContent.trim().length`,
  envelope: `$("#envOut").textContent.trim().length`,
  // JOB #1739 — an empty shelf still renders its empty-state sentence, so
  // this counts rendered text either way; a broken loadSaved renders none.
  saved: `$("#savedList").textContent.trim().length`,
};

async function main() {
  const list = await (await fetch(`${CDP}/json/list`)).json();
  const page = list.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));

  let id = 0;
  const pending = new Map();
  const errors = []; // {tab, kind, detail}
  let currentTab = "(boot)";
  const call = (method, params) =>
    new Promise((res) => {
      pending.set(++id, res);
      ws.send(JSON.stringify({ id, method, params }));
    });

  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); return; }
    if (m.method === "Runtime.exceptionThrown")
      errors.push({ tab: currentTab, kind: "exception",
        detail: m.params.exceptionDetails.exception?.description
          || m.params.exceptionDetails.text });
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error")
      errors.push({ tab: currentTab, kind: "console",
        detail: m.params.args.map((a) => a.value ?? a.description).join(" ") });
  };

  await call("Runtime.enable", {});
  await call("Page.enable", {});
  await call("Page.navigate", { url: ORIGIN });
  await new Promise((r) => setTimeout(r, 1500));
  await call("Runtime.evaluate", {
    expression: `localStorage.setItem('koraxToken', ${JSON.stringify(TOKEN)}); 'ok'`,
  });
  await call("Page.navigate", { url: ORIGIN });
  await new Promise((r) => setTimeout(r, 2000));

  // The tab list is the shell's OWN nav — asserted against, not assumed,
  // so a shell edit that adds or removes a tab fails this sweep loudly
  // rather than silently checking fewer tabs than exist.
  const navProbe = await call("Runtime.evaluate", {
    expression: `JSON.stringify([...document.querySelectorAll("nav button")].map(b => b.dataset.tab))`,
    returnByValue: true,
  });
  const navTabs = JSON.parse(navProbe.result.value);
  const tabMismatch = navTabs.length !== TABS.length
    || !TABS.every((t) => navTabs.includes(t));

  const report = { tabs: {}, navTabs, tabMismatch, errors: [] };

  for (const tab of TABS) {
    currentTab = tab;
    await call("Runtime.evaluate", {
      expression: `document.querySelector('nav button[data-tab="${tab}"]').click(); 'clicked'`,
    });
    await new Promise((r) => setTimeout(r, 1200));

    if (tab === "nest") {
      // #nestNs is an nsPick <select>; give it an explicit value rather
      // than trusting its default is populated by the time we click, and
      // exercise the click a human actually makes.
      await call("Runtime.evaluate", {
        expression: `$("#nestNs").value = "/commons/rakes"; $("#nestLoad").click(); 'ok'`,
      });
      await new Promise((r) => setTimeout(r, 1200));
    }
    if (tab === "envelope") {
      await call("Runtime.evaluate", {
        expression: `$("#envId").value = "${PROBE_ENVELOPE_ID}"; $("#envLoad").click(); 'ok'`,
      });
      await new Promise((r) => setTimeout(r, 1200));
    }

    const probeExpr = NONEMPTY_PROBE[tab];
    const probe = await call("Runtime.evaluate", {
      expression: probeExpr, returnByValue: true,
    });
    report.tabs[tab] = probe.result?.value ?? null;
  }

  currentTab = "(teardown)";
  report.errors = errors;
  console.log(JSON.stringify(report));
  ws.close();
  process.exit(errors.length ? 1 : 0);
}
main().catch((e) => { console.error("DRIVER FAILED:", e); process.exit(2); });
