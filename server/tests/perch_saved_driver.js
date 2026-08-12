// server/tests/perch_saved_driver.js — JOB #1739 (ISSUE #1734).
//
// Drives the shelf's whole life in a REAL headless Chrome over CDP, the
// R94 pattern (Node 22's built-in WebSocket, nothing installed): save an
// envelope from its card, RELOAD (a fresh boot — the cache dies, the
// board is the record), see it on the Saved tab, unsave it there, RELOAD
// again, see the shelf empty. Python owns the server-side half of the
// assertion (the NOTE's edge and marker, the SUPERSEDE) by reading the
// mailbox over the API; this driver proves the browser half and reports.
//
// Prints one JSON object to stdout; exit 0 iff every step held.
const CDP = `http://127.0.0.1:${process.argv[2]}`;
const ORIGIN = process.argv[3];
const TOKEN = process.argv[4];
const TARGET = process.argv[5]; // envelope id to save

async function main() {
  const list = await (await fetch(`${CDP}/json/list`)).json();
  const page = list.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));

  let id = 0;
  const pending = new Map();
  const errors = [];
  const call = (method, params) =>
    new Promise((res) => {
      pending.set(++id, res);
      ws.send(JSON.stringify({ id, method, params }));
    });
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg.result || msg.error);
      pending.delete(msg.id);
    } else if (msg.method === "Runtime.exceptionThrown") {
      const d = msg.params.exceptionDetails;
      errors.push(d.exception?.description || d.text || "exception");
    } else if (msg.method === "Runtime.consoleAPICalled"
               && msg.params.type === "error") {
      errors.push("console.error: " + (msg.params.args || [])
        .map((a) => a.value ?? a.description ?? "").join(" "));
    }
  };
  await call("Page.enable");
  await call("Runtime.enable");

  const evaluate = async (expr) => {
    const r = await call("Runtime.evaluate",
      { expression: expr, returnByValue: true, awaitPromise: true });
    return r?.result?.value;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const nav = async () => {
    await call("Page.navigate", { url: ORIGIN + "/" });
    await sleep(1500);
  };
  const booted = async () => {
    for (let i = 0; i < 40; i++) {
      const who = await evaluate(`$("#who").textContent`);
      if (who && who !== "…" && who !== "no token") return true;
      await sleep(250);
    }
    return false;
  };

  const out = { steps: {}, errors };

  await nav();
  await evaluate(`localStorage.setItem("koraxToken", ${JSON.stringify(TOKEN)})`);
  await nav();
  out.steps.booted = await booted();

  // 1. open the target on the envelope tab and SAVE from its card
  await evaluate(`document.querySelector('nav button[data-tab="envelope"]').click()`);
  await evaluate(`$("#envId").value = ${TARGET}; loadEnvelope().then(() => "ok")`);
  await sleep(800);
  out.steps.card_has_affordance = await evaluate(
    `!!document.querySelector('#envOut [data-save="${TARGET}"]')`);
  await evaluate(
    `document.querySelector('#envOut [data-save="${TARGET}"]').click()`);
  await sleep(800);
  out.steps.glyph_on_after_save = await evaluate(
    `document.querySelector('#envOut [data-save="${TARGET}"]').textContent === "★"`);

  // 2. reload — fresh boot, cache dead — the shelf must remember
  await nav();
  await booted();
  await sleep(500);
  await evaluate(`document.querySelector('nav button[data-tab="saved"]').click()`);
  await sleep(1200);
  out.steps.shelf_lists_target_after_reload = await evaluate(
    `!!document.querySelector('#savedList [data-save="${TARGET}"]')`);
  out.steps.shelf_glyph_on = await evaluate(
    `document.querySelector('#savedList [data-save="${TARGET}"]')?.textContent === "★"`);

  // 3. unsave FROM the shelf (same gesture as anywhere), reload, gone
  await evaluate(
    `document.querySelector('#savedList [data-save="${TARGET}"]').click()`);
  await sleep(800);
  await nav();
  await booted();
  await sleep(500);
  await evaluate(`document.querySelector('nav button[data-tab="saved"]').click()`);
  await sleep(1200);
  out.steps.shelf_empty_after_unsave = await evaluate(
    `!document.querySelector('#savedList [data-save]')`);
  out.steps.empty_state_says_so = await evaluate(
    `$("#savedList").textContent.includes("nothing saved")`);

  out.ok = out.errors.length === 0
    && Object.values(out.steps).every((v) => v === true);
  console.log(JSON.stringify(out, null, 1));
  process.exit(out.ok ? 0 : 1);
}

main().catch((e) => {
  console.log(JSON.stringify({ ok: false, driver_crash: String(e) }));
  process.exit(1);
});
