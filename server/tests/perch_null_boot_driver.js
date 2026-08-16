// server/tests/perch_null_boot_driver.js — ISSUE #2995, product half.
//
// THE DEFECT THIS DRIVES, AND WHY IT NEEDS A REAL BROWSER.
//
// `ME` is null until boot() resolves /whoami. boot()'s failure branch
// deliberately does NOT hide the UI (#1941/S1: rendering every boot failure
// as an auth problem sent readers to their credentials over a dead board), so
// a page whose boot failed stays fully interactive with `ME === null`. Ten
// handlers composed a post from `ME.identity`; three guarded, seven did not,
// and the seven died as UNCAUGHT exceptions —
// `Cannot read properties of null (reading 'identity')`.
//
// **An uncaught exception is the whole property, so nothing here may catch.**
// Wrapping a handler in try/catch to see whether it throws destroys the thing
// being measured: a caught error produces no `Runtime.exceptionThrown` and the
// page looks healthy. So every probe INVOKES THE HANDLER THE WAY AN onclick
// DOES — fire and forget — and reads CDP's exception stream, which is the same
// surface `test_perch_smoke.py` sweeps and the same one that caught this.
//
// The boot failure is forced rather than raced. #2995 observed it at 2-of-5
// under 2-CPU pinning; a test that waited for that would be the flake it is
// documenting. Overriding fetch for /whoami reproduces the STATE the race
// produces, deterministically, which is the state the handlers meet.
//
// Prints one JSON object to stdout; exit 0 iff every probe held.
const CDP = `http://127.0.0.1:${process.argv[2]}`;
const ORIGIN = process.argv[3];
const TOKEN = process.argv[4];

// Every handler that composes a post, with an invocation that reaches it.
// The three that already guarded are here too: the guard is now one helper,
// so a regression in it would take all ten at once and a probe set covering
// only the seven repaired ones would not see it.
const HANDLERS = [
  ["ackAll",            `ackAll([1])`],
  ["stamp",             `stamp(1, "/korax/canon")`],
  ["closeOpen",         `closeOpen(1)`],
  ["postGrantDecline",  `postGrantDecline(1)`],
  ["dmSend",            `$("#dmTo").innerHTML = '<option value="band:x">x</option>';`
                        + `$("#dmTo").value = "band:x"; $("#dmText").value = "hi";`
                        + `$("#dmSend").click()`],
  ["postSend",          `$("#postText").value = "hi"; $("#postSend").click()`],
  ["toggleSave",        `toggleSave(1)`],
  ["brCompose",         `brCompose()`],
  ["thReply",           `thReply()`],
];

async function main() {
  const list = await (await fetch(`${CDP}/json/list`)).json();
  const page = list.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));

  let id = 0;
  const pending = new Map();
  const thrown = [];   // uncaught exceptions and unhandled rejections ONLY
  const consoles = []; // console.error, kept apart: boot's own is expected
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
      thrown.push(d.exception?.description || d.text || "exception");
    } else if (msg.method === "Runtime.consoleAPICalled"
               && msg.params.type === "error") {
      consoles.push((msg.params.args || [])
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

  const out = { steps: {}, probes: {}, thrown, consoles };

  // 1. a normal boot first, so the page is the real thing and not a blank
  //    document — the handlers must be DEFINED for their absence to be a
  //    failure rather than a silently skipped probe.
  await nav();
  await evaluate(`localStorage.setItem("koraxToken", ${JSON.stringify(TOKEN)})`);
  await nav();
  let booted = false;
  for (let i = 0; i < 40 && !booted; i++) {
    const who = await evaluate(`$("#who").textContent`);
    if (who && who !== "…" && who !== "no token") booted = true;
    else await sleep(250);
  }
  out.steps.booted_normally = booted;
  out.steps.every_handler_defined = await evaluate(
    `${JSON.stringify(HANDLERS.map((h) => h[0]))}`
    + `.every((n) => typeof window[n] === "function" || n === "dmSend" || n === "postSend")`);

  // 2. now break /whoami and re-boot: this is the post-failed-boot state
  await evaluate(`
    (() => {
      const orig = window.fetch;
      window.fetch = (u, o) => String(u).includes("/whoami")
        ? Promise.reject(new TypeError("Failed to fetch"))
        : orig(u, o);
      ME = null;
      return true;
    })()`);
  await evaluate(`boot().then(() => "done").catch(() => "caught")`);
  await sleep(600);
  out.steps.me_is_null = await evaluate(`ME === null`);
  out.steps.who_says_boot_failed = await evaluate(
    `$("#who").textContent.startsWith("boot failed")`);
  // boot's own console.error is EXPECTED and is the half #2995 leaves open.
  out.steps.boot_console_error_present =
    consoles.some((c) => c.includes("boot failed"));

  const thrownBefore = thrown.length;

  // 3. every handler, fired the way a click fires it. Nothing is caught.
  for (const [name, expr] of HANDLERS) {
    const before = thrown.length;
    await evaluate(`$("#toast").style.display = "none"; $("#toast").textContent = "";`);
    await evaluate(`(() => { try { ${expr}; } catch (e) { window.__sync = String(e); } return true; })()`);
    await sleep(350);
    const toastText = await evaluate(`$("#toast").textContent`);
    const toastShown = await evaluate(`$("#toast").style.display === "block"`);
    out.probes[name] = {
      threw: thrown.length - before,
      sync_throw: (await evaluate(`window.__sync || ""`)) || null,
      toast_shown: toastShown,
      toast_names_identity: (toastText || "").includes("no identity yet"),
    };
    await evaluate(`window.__sync = ""`);
  }

  // 4. postGrantApproval, which the loop above CANNOT reach — the site is
  //    masked TWICE on unmodified main and a naive probe measures neither
  //    the defect nor its absence (#3273 vesper, #3275 desk):
  //
  //      mask 1  `if (!pending) return` — GC_PENDING is empty after a failed
  //              boot, so it answers "nothing composed" and never continues
  //      mask 2  a staleness re-read of /policy must succeed and AGREE, or it
  //              recomposes and returns
  //
  //    and a third that only appears once you clear those two: `e.ext.korax
  //    .grant_request` throws on an envelope without one, which is a TypeError
  //    that is NOT this defect. A probe reddening there would be measuring its
  //    own fixture. So all three are satisfied and the ONLY thing left to fail
  //    is `author: ME.identity`.
  //
  //    The technique is vesper's, cited rather than reconstructed.
  await evaluate(`
    (() => {
      const real = window.fetch;
      const json = (o) => Promise.resolve(new Response(JSON.stringify(o), {
        status: 200, headers: { "Content-Type": "application/json" } }));
      window.fetch = (u, o) => {
        const url = String(u);
        if (url.includes("/whoami")) return Promise.reject(new TypeError("Failed to fetch"));
        if (url.includes("/policy")) return json({ policy: 999 });
        if (url.includes("/envelope/")) return json({
          id: 1, ext: { korax: { grant_request: { grants: [
            { ns: "/x", band: "reader" } ] } } } });
        if (o && o.method === "POST") return Promise.reject(new TypeError("Failed to fetch"));
        return real(u, o);
      };
      GC_PENDING.set(1, { basedOn: 999, payload: [] });
      return true;
    })()`);
  {
    const before = thrown.length;
    await evaluate(`$("#toast").style.display = "none"; $("#toast").textContent = "";`);
    await evaluate(`(() => { try { postGrantApproval(1); } catch (e) { window.__sync = String(e); } return true; })()`);
    await sleep(500);
    const toastText = await evaluate(`$("#toast").textContent`);
    out.probes.postGrantApproval = {
      threw: thrown.length - before,
      sync_throw: (await evaluate(`window.__sync || ""`)) || null,
      toast_shown: await evaluate(`$("#toast").style.display === "block"`),
      toast_names_identity: (toastText || "").includes("no identity yet"),
      // proof the masks were cleared rather than merely not hit
      reached_past_masks: await evaluate(`GC_PENDING.has(1)`),
    };
  }

  out.steps.no_handler_threw = thrown.length === thrownBefore;
  // over out.probes, NOT over HANDLERS — postGrantApproval is probed
  // separately above and iterating the list would silently exclude it.
  out.steps.every_handler_toasted = Object.values(out.probes).every(
    (p) => p.toast_shown && p.toast_names_identity);
  out.steps.grant_approval_masks_cleared =
    out.probes.postGrantApproval.reached_past_masks === true;

  out.ok = Object.values(out.steps).every((v) => v === true);
  console.log(JSON.stringify(out, null, 1));
  process.exit(out.ok ? 0 : 1);
}

main().catch((e) => {
  console.log(JSON.stringify({ ok: false, driver_crash: String(e) }));
  process.exit(1);
});
