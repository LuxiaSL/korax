// server/tests/perch_grant_console_driver.js — JOB #1842 (ISSUE #1841).
//
// Drives the grant console end to end in a REAL headless Chrome over CDP,
// the R94 pattern: a grant-request OPEN is on the board; the operator's
// session opens the inbox, clicks review, SEES the machine-verified diff
// (denominator + removed:none computed, not defaulted), posts the approval,
// and the card closes. Python owns the server-side half (the POLICY landed
// with every prior grant carried forward, the OPEN reads closed, the grant
// is queryable); this driver proves the browser half and reports.
//
// It also drives the two refusal directions that CANNOT be reached through
// the happy path, directly against the pure functions in the real engine:
//   - a broken policy read must render as a loud refusal, never an empty
//     diff (the #1843 false-all-clear class), and
//   - a diff carrying removals must NOT offer a post button.
//
// Prints one JSON object to stdout; exit 0 iff every step held.
const CDP = `http://127.0.0.1:${process.argv[2]}`;
const ORIGIN = process.argv[3];
const TOKEN = process.argv[4];   // the operator's (human band)
const OPEN_ID = process.argv[5]; // the grant-request OPEN

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
  await sleep(1000); // loadInbox fires at boot; let the cards land

  // 1. the request card renders with the review control (human session)
  out.steps.card_has_review = await evaluate(
    `!!document.querySelector('[data-gc-review="${OPEN_ID}"]')`);

  // 2. review → the diff renders: denominator, removed:none, a post button
  await evaluate(`reviewGrant(${OPEN_ID}).then(() => "ok")`);
  await sleep(800);
  out.steps.diff_rendered = await evaluate(
    `!!document.querySelector('[data-gc-diff="${OPEN_ID}"]')`);
  out.steps.diff_has_denominator = await evaluate(
    `/\\d+ grants in force → \\d+ proposed/.test(
       document.querySelector('[data-gc-diff="${OPEN_ID}"]')?.textContent || "")`);
  out.steps.diff_says_removed_none = await evaluate(
    `(document.querySelector('[data-gc-diff="${OPEN_ID}"]')?.textContent || "")
       .includes("grants removed: none")`);
  out.steps.diff_offers_post = await evaluate(
    `!!document.querySelector('[data-gc-post="${OPEN_ID}"]')`);

  // 3. the refusal directions, driven against the pure functions in the
  //    real engine — unreachable through the UI on a healthy board.
  out.steps.broken_fetch_refused = await evaluate(
    `(() => { try {
        composeGrantSuccessor({policy: 3, at: 5},
          {identity: "band:x", grants: [{ns: "/x", band: "claimant"}]});
        return false;                    // composing from nothing = defect
      } catch (e) {
        return String(e.message).includes("refusing to compose");
      } })()`);
  out.steps.removal_diff_withholds_post = await evaluate(
    `(() => {
        const html = renderGrantDiff({
          counts: {before: 5, after: 5}, basedOn: 1,
          removed: [{identity: "band:victim", ns: "/x", band: "claimant"}],
          replaced: [], added: [{identity: "band:y", ns: "/y", band: "poster"}],
          otherFieldsChanged: [],
        }, 999999);
        return html.includes("REFUSING") && !html.includes('data-gc-post="999999"');
      })()`);

  // 4. the staleness guard, exercised live: the root policy moves while
  //    the diff is on screen (a no-op supersession — same payload, new
  //    envelope), and the post click must RECOMPOSE rather than post.
  await evaluate(`(async () => {
      const pol = await api("/policy?ns=%2F");
      await api("/post", { method: "POST", body: JSON.stringify({
        proto: "korax/0.1", author: ME.identity, ns: "/", type: "POLICY",
        grade: "n/a", refs: [{ edge: "supersedes", id: pol.policy }],
        payload: pol.payload, ext: {},
      })});
      return "moved";
    })()`);
  await evaluate(`postGrantApproval(${OPEN_ID}).then(() => "ok")`);
  await sleep(1200);
  out.steps.stale_post_blocked_and_recomposed = await evaluate(
    `(document.querySelector('#gc-${OPEN_ID}')?.textContent || "")
       .includes("moved") &&
     !!document.querySelector('[data-gc-diff="${OPEN_ID}"]')`);
  // nothing closed: the OPEN still renders its console pane
  out.steps.open_still_pending_after_block = await evaluate(
    `!!document.querySelector('#gc-${OPEN_ID}')`);

  // 5. post the recomposed approval; the card should close
  await evaluate(`postGrantApproval(${OPEN_ID}).then(() => "ok")`);
  await sleep(1500);
  out.steps.card_closed_after_post = await evaluate(
    `!document.querySelector('[data-gc-review="${OPEN_ID}"]')`);

  out.ok = out.errors.length === 0
    && Object.values(out.steps).every((v) => v === true);
  console.log(JSON.stringify(out, null, 1));
  process.exit(out.ok ? 0 : 1);
}

main().catch((e) => {
  console.log(JSON.stringify({ ok: false, driver_crash: String(e) }));
  process.exit(1);
});
