// server/tests/perch_forum_s3_driver.js — JOB #2243 (S3, the board and
// user pages), driven end to end. Same CDP rig as perch_thread_driver.js
// (S2); every gesture is a real click judged by its effect, never a
// render-check (#1843's denominator rule, #2045 §1).
//
// Invoked by test_perch_forum_s3_browser.py. Prints one JSON object to
// stdout; Python does the asserting.
const CDP = `http://127.0.0.1:${process.argv[2]}`;
const ORIGIN = process.argv[3];
const TOKEN = process.argv[4];
const OPERATOR = process.argv[5];
const NS = process.argv[6];       // the small conversation's own nest
const LOAD_NS = process.argv[7];  // the prolific fixture's own nest
const CONVO_ROOT = Number(process.argv[8]);
const CONVO_REPLY = Number(process.argv[9]);
const FIRST_PROLIFIC = Number(process.argv[10]);  // the OLDEST of the >budget posts
const LAST_PROLIFIC = Number(process.argv[11]);   // the NEWEST — the #2302 proof
const QUIET = process.argv[12];                   // a band with exactly one post

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
  // THE EXPRESSION IS EVALUATED RAW (S2's own note, repeated because the
  // trap is real): `Runtime.evaluate` takes a statement sequence, so
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

  await call("Page.enable");
  await call("Runtime.enable");

  await call("Page.navigate", { url: ORIGIN });
  await sleep(1500);
  await evil(`localStorage.setItem('koraxToken', ${JSON.stringify(TOKEN)}); 'ok'`);
  await call("Page.navigate", { url: ORIGIN });
  await sleep(2000);

  const report = { thread: {}, board: {}, profile: {}, profileSmall: {},
                   compose: {}, errors: [] };

  // ── 1. the thread page: author chip -> user page ───────────────────
  where = "thread cold load";
  await call("Page.navigate", { url: `${ORIGIN}/#/e/${CONVO_REPLY}` });
  await sleep(2500);
  report.thread.tab = await visibleTab();
  report.thread.cards = await evil(`document.querySelectorAll('#threadList .th-card').length`);

  where = "thread author chip -> profile";
  await evil(`$("#th-${CONVO_REPLY} .who-chip").click(); 'ok'`);
  await sleep(2200);
  // `openProfile` records the hash via `encodeURIComponent(id)` — a band
  // id like `band:xxxx` carries a colon, which percent-encodes. Comparing
  // against the raw id here would fail even when the navigation is
  // correct, so this compares what the hash actually contains.
  report.thread.authorWentToProfile =
    (await evil(`location.hash`)) === `#/band/${encodeURIComponent(OPERATOR)}`
    && (await visibleTab()) === "tab-bands";

  // ── 2. the thread page: ns chip -> board page ───────────────────────
  where = "thread ns chip -> board";
  await call("Page.navigate", { url: `${ORIGIN}/#/e/${CONVO_REPLY}` });
  await sleep(2500);
  await evil(`$("#th-${CONVO_REPLY} .br-nslink").click(); 'ok'`);
  await sleep(2200);
  report.thread.nsWentToBoard =
    (await evil(`location.hash`)) === `#/b${NS}`
    && (await visibleTab()) === "tab-browse";
  report.thread.boardMastheadNamesNs = await evil(
    `($("#browseMasthead h2")?.textContent || "").trim() === ${JSON.stringify(NS)}`);

  // ── 3. the board page: a row opens the thread ───────────────────────
  where = "board row -> thread";
  await evil(`$('#browseList .card[data-id="${CONVO_ROOT}"] .br-line').click(); 'ok'`);
  await sleep(2200);
  report.board.rowWentToThread =
    (await evil(`location.hash`)) === `#/e/${CONVO_ROOT}`
    && (await visibleTab()) === "tab-thread"
    && (await evil(`document.querySelectorAll('#threadList .th-card').length`)) > 0;

  // ── 4. compose, ns prefilled (ruled decision 5's second instalment) ─
  where = "compose";
  await call("Page.navigate", { url: `${ORIGIN}/#/b${NS}` });
  await sleep(2500);
  const cardsBefore = await evil(`document.querySelectorAll('#browseList .card').length`);
  const nsPrefilled = await evil(`$("#brComposeNs").value === ${JSON.stringify(NS)}`);
  await evil(`$("#brComposeType").value = "FINDING";
              $("#brComposeText").value = "S3 driver: posted from the board page"; 'ok'`);
  await evil(`$("#brComposeSend").click(); 'ok'`);
  await sleep(2500);
  // reload to see the fresh state — the send handler already reloads,
  // this just gives the network round trip room to finish
  const cardsAfter = await evil(`document.querySelectorAll('#browseList .card').length`);
  report.compose.nsPrefilled = nsPrefilled;
  report.compose.cardsBefore = cardsBefore;
  report.compose.cardsAfter = cardsAfter;
  report.compose.landed = cardsAfter === cardsBefore + 1;
  report.compose.boxCleared = await evil(`$("#brComposeText").value === ""`);

  // ── 5. the user page: #2302 — recent-first, honestly bounded ────────
  where = "profile (prolific)";
  await call("Page.navigate", { url: `${ORIGIN}/#/band/${encodeURIComponent(OPERATOR)}` });
  await sleep(2500);
  report.profile.tab = await visibleTab();
  report.profile.rowCount = await evil(`document.querySelectorAll('#bandProfile .bp-post').length`);
  report.profile.newestPresent = await evil(
    `!!document.querySelector('#bandProfile .bp-post[data-id="${LAST_PROLIFIC}"]')`);
  // the discriminating negative: if the OLDEST of the over-budget posts
  // is still on the page, the walk read the wrong direction and the
  // fixture has failed to distinguish the fix from the bug (#2045 §1)
  report.profile.oldestOfTheOldHundredAbsent = await evil(
    `!document.querySelector('#bandProfile .bp-post[data-id="${FIRST_PROLIFIC}"]')`);
  report.profile.boundShown = await evil(`!!document.querySelector('#bandProfile .bp-bound')`);
  report.profile.boundSaysLatest = await evil(
    `(document.querySelector('#bandProfile .bp-bound')?.textContent || "").includes("latest")`);

  where = "profile row -> thread";
  const anyPostId = await evil(
    `document.querySelector('#bandProfile .bp-post')?.dataset.id`);
  await evil(`$('#bandProfile .bp-post[data-id="${anyPostId}"] .br-line').click(); 'ok'`);
  await sleep(2200);
  report.profile.rowWentToThread =
    (await visibleTab()) === "tab-thread"
    && (await evil(`document.querySelectorAll('#threadList .th-card').length`)) > 0;

  where = "profile row ns chip -> board";
  await call("Page.navigate", { url: `${ORIGIN}/#/band/${encodeURIComponent(OPERATOR)}` });
  await sleep(2500);
  const anyPostId2 = await evil(
    `document.querySelector('#bandProfile .bp-post')?.dataset.id`);
  await evil(`$('#bandProfile .bp-post[data-id="${anyPostId2}"] .br-nslink').click(); 'ok'`);
  await sleep(2200);
  // the profile's posts live in LOAD_NS, not NS — the small conversation
  // nest above is unrelated to this band's own record
  report.profile.rowWentToBoard =
    (await visibleTab()) === "tab-browse"
    && (await evil(`($("#browseMasthead h2")?.textContent || "").trim()`)) === LOAD_NS;

  // ── 6. the canary direction: an in-budget band claims no bound ──────
  where = "profile (quiet, the canary)";
  await call("Page.navigate", { url: `${ORIGIN}/#/band/${encodeURIComponent(QUIET)}` });
  await sleep(2200);
  report.profileSmall.rowCount = await evil(`document.querySelectorAll('#bandProfile .bp-post').length`);
  report.profileSmall.boundAbsent = await evil(`!document.querySelector('#bandProfile .bp-bound')`);

  where = "(teardown)";
  report.errors = errors;
  console.log(JSON.stringify(report));
  ws.close();
  process.exit(errors.length ? 1 : 0);
}

main().catch((e) => { console.error("DRIVER FAILED:", e); process.exit(2); });
