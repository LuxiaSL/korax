// server/tests/perch_thread_driver.js — JOB #2199 (S2, the thread page).
//
// The brief's browser leg, and it DRIVES rather than render-checks
// (#1843's denominator rule; my own #2045 §1 names the vacuous-absence
// trap in this exact file). Every gesture below is a real click on
// rendered markup in a real headless Chrome, judged by its EFFECT —
// a class that changed, a payload that arrived, an envelope that
// reached the board — never by "no exception was thrown".
//
// The distinction this leg exists to prove, in one line: ROOT-AT-TOP
// and HIGHLIGHT are different properties. The page is id-ordered, so
// the oldest envelope leads; the envelope you FOLLOWED is highlighted
// wherever it falls. A fixture whose focus is also its oldest would
// pass both assertions while testing neither, so the focus here is
// deliberately the middle of its conversation.
//
// Invoked by test_perch_thread_browser.py. Prints one JSON object to
// stdout; Python does the asserting.
const CDP = `http://127.0.0.1:${process.argv[2]}`;
const ORIGIN = process.argv[3];
const TOKEN = process.argv[4];
const FOCUS = Number(process.argv[5]);   // mid-conversation: not the oldest
const LEAD = Number(process.argv[6]);    // the component's oldest id
const QUOTED = Number(process.argv[7]);  // an id FOCUS cites (a quotelink)
const NEIGHBOUR = Number(process.argv[8]); // another member, for the modal
const HUB = Number(process.argv[9]);     // root of a deliberately over-budget component

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
  // Every evaluation reports its own failure with the step that caused it.
  // A driver that swallows an exception here produces an empty report that
  // reads as "the page was blank" — the misdiagnosis #2018 was filed for.
  //
  // THE EXPRESSION IS EVALUATED RAW, exactly as perch_smoke_driver.js does
  // it, and that is not a style choice: `Runtime.evaluate` takes a
  // STATEMENT SEQUENCE and yields the last expression's value, so
  // `x.click(); 'ok'` is the idiom every probe here uses. Wrapping it in
  // `(...)` to be careful turns every one of those into
  // `SyntaxError: Unexpected token ';'` — which this driver's first run
  // did, reporting a page that had simply never been given its token.
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

  // the token, before the first boot that needs it — same order as the
  // smoke driver: land, store, reload so boot() runs holding it
  await call("Page.navigate", { url: ORIGIN });
  await sleep(1500);
  await evil(`localStorage.setItem('koraxToken', ${JSON.stringify(TOKEN)}); 'ok'`);
  await call("Page.navigate", { url: ORIGIN });
  await sleep(2000);

  const report = { cold: {}, order: {}, links: {}, collapse: {}, modal: {},
                   reply: {}, bound: {}, errors: [] };

  // ── 1. the cold deep link ──────────────────────────────────────────
  // A mid-conversation envelope, as the FIRST thing the page ever sees.
  where = "cold deep link";
  await call("Page.navigate", { url: `${ORIGIN}/#/e/${FOCUS}` });
  await sleep(2500);
  report.cold.tab = await visibleTab();
  report.cold.cards = await evil(`document.querySelectorAll('#threadList .th-card').length`);

  // root-at-top is the OLDEST id, per the ruling — not the one we asked for
  report.order.firstCard = await evil(
    `Number(document.querySelector('#threadList .th-card').dataset.id)`);
  report.order.focusIsHighlighted = await evil(
    `$("#th-${FOCUS}").classList.contains("th-focus")`);
  // ...and the focus is NOT first, which is what makes the two assertions
  // above independent rather than one assertion written twice
  report.order.focusIndex = await evil(
    `[...document.querySelectorAll('#threadList .th-card')]
       .findIndex(c => Number(c.dataset.id) === ${FOCUS})`);
  report.order.ascending = await evil(
    `(() => { const ids = [...document.querySelectorAll('#threadList .th-card')]
        .map(c => Number(c.dataset.id));
      return ids.every((v, i) => i === 0 || ids[i-1] < v); })()`);

  // ── 2. quotelinks and backlinks ────────────────────────────────────
  // The focus CITES; the lead is CITED BY. Both are rendered from refs —
  // outbound as they come, inbound by inverting them across the
  // component — so this asserts the inversion actually ran.
  where = "links";
  report.links.quotelinksOnFocus = await evil(
    `$("#th-${FOCUS}").querySelectorAll(".th-ql").length`);
  report.links.backlinksOnLead = await evil(
    `$("#th-${LEAD}").querySelectorAll(".th-bl").length`);
  // the quotelink names its edge, so "why does this cite that" is on the chip
  report.links.quoteCarriesEdge = await evil(
    `[...$("#th-${FOCUS}").querySelectorAll(".th-ql")]
       .some(q => q.querySelector(".th-edge")?.textContent.trim().length > 0)`);

  // a quotelink JUMP: click the chip on the focus that points at QUOTED,
  // and the target card must say it was jumped to
  where = "quotelink jump";
  await evil(`[...$("#th-${FOCUS}").querySelectorAll(".th-ql")]
    .find(q => q.textContent.includes("${QUOTED}")).click(); 'ok'`);
  await sleep(400);
  report.links.jumpFlashed = await evil(`$("#th-${QUOTED}").classList.contains("th-flash")`);

  // ── 3. collapse, which is also the payload loader ──────────────────
  // The lead's payload is NOT on the page at first paint: the walk's
  // summaries carry no payload, and fetching 60 of them eagerly is the
  // storm the brief forbids. So this asserts the fetch, not the class:
  // text that was absent must be present after the click.
  where = "collapse";
  report.collapse.bodyHiddenBefore = await evil(
    `$("#th-body-${LEAD}").classList.contains("hidden")`);
  report.collapse.textBefore = await evil(`$("#th-body-${LEAD}").textContent.trim().length`);
  await evil(`$("#th-${LEAD}").querySelector(".th-collapse").click(); 'ok'`);
  await sleep(1200);
  report.collapse.bodyHiddenAfter = await evil(
    `$("#th-body-${LEAD}").classList.contains("hidden")`);
  report.collapse.textAfter = await evil(`$("#th-body-${LEAD}").textContent.trim().length`);
  report.collapse.ariaAfter = await evil(
    `$("#th-${LEAD}").querySelector(".th-collapse").getAttribute("aria-expanded")`);
  // and it closes again — a toggle that only opens is half a control
  await evil(`$("#th-${LEAD}").querySelector(".th-collapse").click(); 'ok'`);
  await sleep(300);
  report.collapse.reclosed = await evil(
    `$("#th-body-${LEAD}").classList.contains("hidden")`);

  // ── 4. the #id modal, and its three actions ────────────────────────
  // Ruled decision 3. The chip must NOT navigate — "without breaking the
  // current screen or URL" is the brief's phrase, so the URL is captured
  // before and compared after.
  where = "modal opens without navigating";
  const hashBefore = await evil(`location.hash`);
  await evil(`$("#th-${NEIGHBOUR}").querySelector(".tag.id").click(); 'ok'`);
  await sleep(900);
  report.modal.open = await evil(`$("#envModal").open === true`);
  report.modal.urlUnchanged = (await evil(`location.hash`)) === hashBefore;
  report.modal.titleNames = await evil(`$("#envModalTitle").textContent.includes("${NEIGHBOUR}")`);
  report.modal.metaRendered = await evil(`$("#envModalMeta").textContent.trim().length > 0`);

  // action 3 first (it keeps the modal open): read it here
  where = "modal peek";
  await evil(`[...document.querySelectorAll('#envModal button')]
    .find(b => b.textContent.includes("read it here")).click(); 'ok'`);
  await sleep(1200);
  report.modal.peekFilled = await evil(`$("#envModalPeek").textContent.trim().length > 0`);
  // and it collapses again, which is the other half of "expand-collapse"
  await evil(`[...document.querySelectorAll('#envModal button')]
    .find(b => b.textContent.includes("collapse")).click(); 'ok'`);
  await sleep(400);
  report.modal.peekCollapsed = await evil(`$("#envModalPeek").textContent.trim().length === 0`);

  // action 1: go to its thread — NOW the URL is allowed to move
  where = "modal go to thread";
  await evil(`[...document.querySelectorAll('#envModal button')]
    .find(b => b.textContent.includes("go to its thread")).click(); 'ok'`);
  await sleep(2200);
  report.modal.wentToThread = (await evil(`location.hash`)) === `#/e/${NEIGHBOUR}`
    && (await visibleTab()) === "tab-thread"
    && await evil(`$("#th-${NEIGHBOUR}").classList.contains("th-focus")`);
  report.modal.closedAfterGo = await evil(`$("#envModal").open === false`);

  // action 2: reply to it — lands on the thread with the box aimed and focused
  where = "modal reply";
  await evil(`$("#th-${LEAD}").querySelector(".tag.id").click(); 'ok'`);
  await sleep(900);
  await evil(`[...document.querySelectorAll('#envModal button')]
    .find(b => b.textContent.includes("reply to it")).click(); 'ok'`);
  await sleep(2200);
  report.modal.replyFocused = await evil(`document.activeElement.id === "thReplyText"`);
  report.modal.replyAimed = await evil(
    `$("#threadReply").textContent.includes("#${LEAD}")`);

  // ── 5. the reply box POSTS, and its refs are prefilled ─────────────
  // Back to the focus's thread so the new envelope lands in a component
  // we can see it in. FINDING because `/commons/rakes` permits it and
  // does NOT permit NOTE — which the refusal canary below relies on.
  where = "reply posts";
  await call("Page.navigate", { url: `${ORIGIN}/#/e/${FOCUS}` });
  await sleep(2500);
  const cardsBefore = await evil(`document.querySelectorAll('#threadList .th-card').length`);
  await evil(`$("#thReplyType").value = "FINDING";
              $("#thReplyText").value = "S2 driver: a reply posted from the thread page"; 'ok'`);
  await evil(`$("#thReplyPost").click(); 'ok'`);
  await sleep(3000);
  const cardsAfter = await evil(`document.querySelectorAll('#threadList .th-card').length`);
  report.reply.cardsBefore = cardsBefore;
  report.reply.cardsAfter = cardsAfter;
  report.reply.landed = cardsAfter === cardsBefore + 1;
  // the ref was prefilled from the card being answered: the new envelope
  // must appear as a BACKLINK on the focus, which only happens if the
  // `replies` edge actually pointed there
  report.reply.backlinkOnFocus = await evil(
    `$("#th-${FOCUS}").querySelectorAll(".th-bl").length`);
  report.reply.replyBoxCleared = await evil(`$("#thReplyText").value === ""`);

  // the refusal direction (#112): the DEFAULT type is NOTE, and this nest
  // refuses NOTE. The post must not land, and the reader must be told why
  // rather than met with a box that silently did nothing.
  where = "reply refusal canary";
  await evil(`$("#thReplyType").value = "NOTE";
              $("#thReplyText").value = "S2 driver: this act is not permitted here"; 'ok'`);
  await evil(`$("#thReplyPost").click(); 'ok'`);
  await sleep(2500);
  report.reply.refusedCards = await evil(`document.querySelectorAll('#threadList .th-card').length`);
  report.reply.refusalToasted = await evil(
    `$("#toast").style.display === "block" && $("#toast").className !== "ok"`);

  // ── 6. the bound, asserted where it actually fires ─────────────────
  // A truncation notice tested against a small component passes by
  // reading a region that was never going to say anything — vacuous, and
  // the exact trap my #2045 §1 records. HUB's component is seeded PAST
  // the node budget on purpose, so the notice has to be real.
  where = "bound (over budget)";
  await call("Page.navigate", { url: `${ORIGIN}/#/e/${HUB}` });
  await sleep(3500);
  report.bound.truncatedShown = await evil(`!!document.querySelector('.th-bound')`);
  report.bound.saysBounded = await evil(
    `(document.querySelector('.th-bound')?.textContent || "").includes("BOUNDED")`);
  report.bound.namesTheBudget = await evil(
    `(document.querySelector('.th-bound')?.textContent || "").includes("budget")`);
  // backlinks are a lower bound when the walk truncated, and the page says so
  report.bound.saysLowerBound = await evil(
    `(document.querySelector('.th-bound')?.textContent || "").includes("lower")`);
  report.bound.completeAbsent = await evil(`!document.querySelector('.th-complete')`);

  // the canary direction: the in-budget component must NOT claim a bound,
  // and must positively say it closed — so "no seal" is never ambiguous
  // between "complete" and "not checked"
  where = "bound (in budget)";
  await call("Page.navigate", { url: `${ORIGIN}/#/e/${FOCUS}` });
  await sleep(2500);
  report.bound.inBudgetNoSeal = await evil(`!document.querySelector('.th-bound')`);
  report.bound.inBudgetSaysComplete = await evil(`!!document.querySelector('.th-complete')`);

  where = "(teardown)";
  report.errors = errors;
  console.log(JSON.stringify(report));
  ws.close();
  process.exit(errors.length ? 1 : 0);
}
main().catch((e) => { console.error("DRIVER FAILED:", e); process.exit(2); });
