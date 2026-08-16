// server/tests/perch_forum_s4_driver.js — JOB #2505 (S4: home, profile,
// and the gate), driven end to end. Same CDP rig as the S2/S3 drivers;
// every gesture is a real click judged by its effect, never a
// render-check (#1843's denominator rule, #2045 §1).
//
// Invoked by test_perch_forum_s4_browser.py. Prints one JSON object to
// stdout; Python does the asserting.
const CDP = `http://127.0.0.1:${process.argv[2]}`;
const ORIGIN = process.argv[3];
const TOKEN = process.argv[4];
const OPERATOR = process.argv[5];
const MARKER = "S4 driver -- the DM only a bound visit may see";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const list = await (await fetch(`${CDP}/json/list`)).json();
  const page = list.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));

  let seq = 0;
  const pending = new Map();
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  };
  const call = (method, params = {}) => new Promise((resolve) => {
    const id = ++seq;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });

  const errors = [];
  let where = "(startup)";
  // THE EXPRESSION IS EVALUATED RAW (S2/S3's own note, repeated because
  // the trap is real): `Runtime.evaluate` takes a statement sequence, so
  // `x.click(); 'ok'` is the idiom — wrapping it in `(...)` turns it into
  // a SyntaxError.
  async function evil(expr) {
    const r = await call("Runtime.evaluate", {
      expression: expr, returnByValue: true, awaitPromise: true,
    });
    if (r.result?.exceptionDetails) {
      const d = r.result.exceptionDetails;
      errors.push(`${where}: ${d.exception?.description || d.text}`);
    }
    return r.result?.result?.value;
  }
  const visibleTab = () => evil(
    `[...document.querySelectorAll('main section')].find(s => !s.classList.contains('hidden'))?.id`);
  // COMPUTED style, not the class list (#2686): `.hidden` on `#gate` lands
  // in the DOM regardless of whether the cascade actually hides anything —
  // an ID rule elsewhere can defeat it silently. Only `getComputedStyle`
  // reports what a viewer actually sees.
  const computedHidden = (sel) => evil(
    `getComputedStyle(document.querySelector(${JSON.stringify(sel)})).display === 'none'`);

  await call("Page.enable");
  await call("Runtime.enable");

  const report = { cold: {}, afterLogin: {}, you: {}, coldBound: {}, errors: [] };

  // ── 1. cold, UNBOUND: the gate, and nothing else ────────────────────
  // No token set anywhere yet — this IS the first thing the page has
  // ever seen, exactly the shape residue (c) asked about, but exercised
  // live rather than by fetching the shell's bytes alone: the loaders
  // that would embed data never fire because the gate never reveals the
  // main/nav they render into.
  where = "cold unbound";
  await call("Page.navigate", { url: ORIGIN });
  await sleep(1800);
  report.cold.gateVisible = !(await computedHidden("#gate"));
  report.cold.navHidden = await computedHidden("nav");
  report.cold.mainHidden = await computedHidden("main");
  // the vacuous-absence trap's remedy: the board genuinely HAS the
  // marker (seeded before the server ever answered a request), so its
  // absence from the page's own text is what the gate actually bought,
  // not an artifact of an empty fixture.
  report.cold.markerAbsent = !(await evil(
    `document.body.innerText.includes(${JSON.stringify(MARKER)})`));

  // ── 2. token entry, via the gate's own inline form ──────────────────
  where = "gate token entry";
  await evil(`$("#gateTokenInput").value = ${JSON.stringify(TOKEN)}; 'ok'`);
  await evil(`$("#gateForm").requestSubmit(); 'ok'`);
  await sleep(2500);
  report.afterLogin.gateHidden = await computedHidden("#gate");
  report.afterLogin.navVisible = !(await computedHidden("nav"));
  report.afterLogin.landedTab = await visibleTab();
  report.afterLogin.markerPresent = await evil(
    `document.body.innerText.includes(${JSON.stringify(MARKER)})`);

  // ── 3. the profile hub — the four links, walked ─────────────────────
  where = "you: cold load";
  await call("Page.navigate", { url: `${ORIGIN}/#/you` });
  await sleep(2200);
  report.you.tab = await visibleTab();
  report.you.selfIdentityShown = await evil(
    `($("#youSelf")?.textContent || "").includes(${JSON.stringify(OPERATOR)})`);

  where = "you -> inbox";
  await evil(`$("#youOut .you-links .card:nth-child(1) button").click(); 'ok'`);
  await sleep(1800);
  report.you.toInbox = (await visibleTab()) === "tab-inbox";

  where = "you -> shelf";
  await call("Page.navigate", { url: `${ORIGIN}/#/you` });
  await sleep(2000);
  await evil(`$("#youOut .you-links .card:nth-child(2) button").click(); 'ok'`);
  await sleep(1800);
  report.you.toShelf = (await visibleTab()) === "tab-saved"
    && (await evil(`location.hash`)) === "#/me";

  where = "you -> posts (self-directed)";
  await call("Page.navigate", { url: `${ORIGIN}/#/you` });
  await sleep(2000);
  await evil(`$("#youOut .you-links .card:nth-child(3) button").click(); 'ok'`);
  await sleep(2200);
  report.you.toPosts = (await visibleTab()) === "tab-bands"
    && (await evil(`location.hash`)) === `#/band/${encodeURIComponent(OPERATOR)}`;

  where = "you -> bands";
  await call("Page.navigate", { url: `${ORIGIN}/#/you` });
  await sleep(2000);
  await evil(`$("#youOut .you-links .card:nth-child(4) button").click(); 'ok'`);
  await sleep(1800);
  report.you.toBands = (await visibleTab()) === "tab-bands"
    && (await evil(`location.hash`)) === "#/bands";

  // ── 4. a fresh cold load, bound: home is still the feed ─────────────
  where = "cold, bound, bare hash";
  await call("Page.navigate", { url: ORIGIN });
  await sleep(2200);
  report.coldBound.landedTab = await visibleTab();

  where = "(teardown)";
  report.errors = errors;
  console.log(JSON.stringify(report));
  ws.close();
  process.exit(errors.length ? 1 : 0);
}

main().catch((e) => { console.error("DRIVER FAILED:", e); process.exit(2); });
