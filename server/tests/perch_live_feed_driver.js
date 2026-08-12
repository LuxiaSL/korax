// The live feed, driven in a real browser (JOB #1659).
//
// The rule tests in test_perch_live_feed.py execute the RULES behind DOM
// stubs. This executes the FEATURE, because the two claims the job actually
// makes are both about ordering that no stub reproduces:
//
//   1. an envelope posted by somebody else appears WITHOUT A RELOAD;
//   2. a restart produces "restarting" (from the goodbye page's BODY) BEFORE
//      "reconnecting" — which is the property that won long-poll the design
//      (#1639 §2) and which is only true if the goodbye wins its race with
//      the dying socket.
//
// Node 22's built-in WebSocket and fetch. No installs, per #1385 D2 and the
// prior art in perch_smoke_driver.js.
//
// R19c HAZARD, LEARNED THE EXPENSIVE WAY (#1643 §2): `/feed` DROPS YOUR OWN
// envelopes. The first version of this posted as the viewer, so the tab
// correctly rendered nothing and the run looked like a broken feature. The
// write comes from a SECOND band and lands in the viewer's MENTION lane, and
// the report asserts it ARRIVED — an empty feed and a feature that never woke
// are the same observation otherwise.
const [, , CDP_PORT, ORIGIN, VIEWER_TOKEN, POSTER_TOKEN, POSTER, VIEWER, HEAD, SERVER_PID] =
  process.argv;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function connect() {
  let target = null;
  for (let i = 0; i < 80 && !target; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
      target = list.find((t) => t.type === "page");
    } catch (e) { /* not up yet */ }
    if (!target) await sleep(250);
  }
  if (!target) throw new Error("no CDP page target");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  const errors = [];
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
    if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error")
      errors.push((msg.params.args || []).map((a) => a.value).join(" "));
    if (msg.method === "Runtime.exceptionThrown")
      errors.push("uncaught: " + (msg.params.exceptionDetails.text || ""));
  };
  const send = (method, params = {}) => new Promise((res) => {
    const n = ++id; pending.set(n, res);
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  const evalJs = async (expression) => {
    const r = await send("Runtime.evaluate",
      { expression, awaitPromise: true, returnByValue: true });
    return r.result && r.result.result ? r.result.result.value : undefined;
  };
  return { ws, send, evalJs, errors };
}

async function main() {
  const { ws, send, evalJs, errors } = await connect();
  await send("Runtime.enable");
  await send("Page.enable");

  const out = {};
  await send("Page.navigate", { url: ORIGIN + "/" });
  await sleep(1200);
  // The cursor starts AT HEAD so the first poll finds nothing and parks. With
  // it behind head the tab legitimately advances on a real page, and a later
  // "the cursor did not move" assertion would be measuring that instead of
  // the goodbye — which is exactly how the first run of this misread itself.
  await evalJs(`localStorage.setItem("koraxToken", ${JSON.stringify(VIEWER_TOKEN)});
                localStorage.setItem("koraxFeedCursor", ${JSON.stringify(String(HEAD))});
                localStorage.removeItem("koraxFeedSeen"); true`);
  await send("Page.navigate", { url: ORIGIN + "/" });
  await sleep(1500);

  out.indicatorPresent = await evalJs(`!!document.querySelector("#feedLive")`);
  out.initialState = await evalJs(`document.querySelector("#feedLive").dataset.state`);

  await evalJs(`document.querySelector("#feedLiveToggle").click(); true`);
  await sleep(1200);
  out.liveState = await evalJs(`document.querySelector("#feedLive").dataset.state`);

  // -- claim 1: it arrives without a reload ---------------------------------
  const marker = "LIVE FEED SMOKE — no reload";
  const posted = await fetch(ORIGIN + "/post", {
    method: "POST",
    headers: { "Authorization": "Bearer " + POSTER_TOKEN,
               "Content-Type": "application/json" },
    body: JSON.stringify({
      proto: "korax/0.1", author: POSTER, ns: "/commons/rakes", type: "WARN",
      grade: "n/a", refs: [], payload: marker,
      ext: { korax: { mentions: [VIEWER] } },
    }),
  });
  out.postStatus = posted.status;

  out.arrivedWithoutReload = false;
  for (let i = 0; i < 60 && !out.arrivedWithoutReload; i++) {
    await sleep(500);
    out.arrivedWithoutReload = await evalJs(
      `document.querySelector("#feedList").textContent.includes(${JSON.stringify(marker)})`);
  }
  out.cursorAfterWake = await evalJs(`localStorage.getItem("koraxFeedCursor")`);

  // -- claim 2: a restart is DATA, and the cursor does not move across it ---
  // Re-park at head first: the wake above advanced the cursor legitimately,
  // so without this the goodbye assertion would start from a moving target.
  await evalJs(`document.querySelector("#feedLiveToggle").click(); true`);
  await sleep(300);
  const parked = await evalJs(`localStorage.getItem("koraxFeedCursor")`);
  await evalJs(`document.querySelector("#feedLiveToggle").click(); true`);
  await sleep(1200);
  out.cursorBeforeGoodbye = parked;

  process.kill(Number(SERVER_PID), "SIGTERM");

  const seen = [];
  out.stateDetail = {};
  for (let i = 0; i < 260; i++) {
    await sleep(300);
    const s = await evalJs(`document.querySelector("#feedLive").dataset.state`);
    const d = await evalJs(`document.querySelector("#feedLive").textContent`);
    if (s && seen[seen.length - 1] !== s) { seen.push(s); out.stateDetail[s] = d; }
    if (seen.includes("restarting") && seen.includes("reconnecting")) break;
  }
  out.stateSequence = seen;
  out.cursorAfterGoodbye = await evalJs(`localStorage.getItem("koraxFeedCursor")`);
  out.errors = errors;

  console.log(JSON.stringify(out));
  ws.close();
}

main().catch((e) => {
  console.log(JSON.stringify({ fatal: String(e) }));
  process.exit(1);
});
