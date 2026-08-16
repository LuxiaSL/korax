// The live feed, driven in a real browser (JOB #1659).
//
// The rule tests in test_perch_live_feed.py execute the RULES behind DOM
// stubs. This executes the FEATURE, because the two claims the job actually
// makes are both about ordering that no stub reproduces:
//
//   1. an envelope posted by somebody else appears WITHOUT A RELOAD;
//   2. a restart produces "restarting" (from the goodbye page's BODY) BEFORE
//      "reconnecting", AND HOLDS IT LONG ENOUGH TO READ — which is the
//      property that won long-poll the design (#1639 §2) and which is only
//      true if the goodbye wins its race with the dying socket.
//
// **CLAIM 2 CHANGED MEANING IN JOB #2966 AND THIS IS THE FILE THAT DID IT.**
// It used to assert PRESENCE of "restarting" in a 300 ms sample. Presence was
// standing in for the thing #1639 actually bought, which is that an operator
// LEARNS the board is restarting — and a 60 ms flash satisfies presence while
// telling nobody anything. Worse, the sampler that measured presence was blind
// to exactly those short states, so the old test failed on real ones while
// reporting a cause it could not observe. Transitions are now RECORDED and the
// assertion is on DWELL.
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

  // THE RECORDER GOES IN BEFORE THE SIGNAL, NOT AFTER (JOB #2966).
  //
  // What this replaces: a loop that read `dataset.state` every 300 ms and
  // called the result `stateSequence`. That is a SAMPLE, and a sampled
  // instrument cannot see a state shorter than its interval — measured miss
  // rate `1 - dwell/300ms`, so a displayed 60 ms state was missed 80% of the
  // time (#2908 §2). The old assertion then reported "no 'restarting' state
  // was ever shown", which is a claim about the DOM that a sampler has no
  // standing to make, and which was FALSE in the one instance anybody
  // observed end to end (#2930 §2: displayed at t=4774, overwritten at
  // t=4780, six milliseconds).
  //
  // A MutationObserver cannot miss a transition regardless of its duration,
  // and the rig control for that is in the delivery: it caught a displayed
  // state 15/15 in every dwell cell tested, including 60 ms.
  await evalJs(`
    (() => {
      const el = document.querySelector("#feedLive");
      const R = { t0: Math.round(performance.now()), rows: [] };
      window.__feedRec = R;
      const push = () => R.rows.push({
        t: Math.round(performance.now()),
        state: el.dataset.state,
        text: el.textContent,
      });
      push();
      new MutationObserver(push).observe(el, {
        attributes: true, attributeFilter: ["data-state"],
        childList: true, characterData: true, subtree: true,
      });
      return true;
    })()`);

  process.kill(Number(SERVER_PID), "SIGTERM");

  // The poll below decides only WHEN TO STOP WATCHING. It no longer decides
  // what was seen, so its interval bounds this driver's patience and nothing
  // about the measurement — which is the whole point of the change.
  const POLL_MS = 300;
  const CAP = 260;
  let iterations = 0;
  let capExhausted = true;
  for (let i = 0; i < CAP; i++) {
    iterations = i + 1;
    await sleep(POLL_MS);
    const done = await evalJs(`
      (() => { const s = new Set(window.__feedRec.rows.map(r => r.state));
               return s.has("restarting") && s.has("reconnecting"); })()`);
    if (done) { capExhausted = false; break; }
  }

  const rec = JSON.parse(await evalJs(`JSON.stringify(window.__feedRec)`));
  out.transitions = rec.rows;

  // Deduped run-length sequence, the same shape the assertions consume — but
  // now derived from a recording rather than from samples.
  const seen = [];
  out.stateDetail = {};
  for (const r of rec.rows) {
    if (r.state && seen[seen.length - 1] !== r.state) seen.push(r.state);
    if (r.state) out.stateDetail[r.state] = r.text;
  }
  out.stateSequence = seen;

  // DWELL: how long `restarting` was actually readable. Measured from its
  // first appearance to the first row showing a DIFFERENT state. If it never
  // gave way inside the window, the dwell is a lower bound and is reported as
  // such rather than silently truncated — an underestimate that reads as a
  // measurement is how a green becomes unfalsifiable.
  let dwell = null;
  let dwellIsLowerBound = false;
  const first = rec.rows.find((r) => r.state === "restarting");
  if (first) {
    const after = rec.rows.find((r) => r.t > first.t && r.state !== "restarting");
    if (after) {
      dwell = after.t - first.t;
    } else {
      dwell = rec.rows[rec.rows.length - 1].t - first.t;
      dwellIsLowerBound = true;
    }
  }
  out.restartingDwellMs = dwell;
  out.restartingDwellIsLowerBound = dwellIsLowerBound;

  // PROPERTY 4 — the instrument states its own parameters, so a red never
  // needs the reader to open this file to learn how it was watched.
  out.observation = {
    mode: "recorded (MutationObserver on #feedLive[data-state])",
    pollIntervalMs: POLL_MS,
    pollPurpose: "stop condition only; transitions are recorded, not sampled",
    capIterations: CAP,
    iterationsUsed: iterations,
    capExhausted,
    watchedMs: rec.rows.length ? rec.rows[rec.rows.length - 1].t - rec.t0 : 0,
  };

  out.cursorAfterGoodbye = await evalJs(`localStorage.getItem("koraxFeedCursor")`);
  out.errors = errors;

  console.log(JSON.stringify(out));
  ws.close();
}

main().catch((e) => {
  console.log(JSON.stringify({ fatal: String(e) }));
  process.exit(1);
});
