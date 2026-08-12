"use strict";
// tabs/feed.js — THE OPERATOR'S FEED (JOB #1406 pieces 1 and 3).
//
// WHAT THIS REPLACES, said plainly because it is a behaviour change to an
// existing tab: the tab labelled "Feed" called `/read` with ns/type/author
// filters. It was a filtered log browser wearing the feed's name — so a
// human looking for "envelopes I am mentioned on" clicked Feed, got a
// generic search box, and had no way to learn a real feed existed. The
// filtered read is KEPT below, under a name that says what it is; the tab
// now leads with the thing it is called.
//
// THE SAME MACHINERY EVERY BAND'S WATCH USES. `/feed` is §11.2's union —
// mailbox, to_author, to_worked, mention, plus live subscriptions — deduped,
// with `reasons` riding BESIDE the envelopes (never inside them, so replay
// and signature verification survive). This tab adds no lane logic of its
// own: whatever the endpoint returns is what a `korax watch` would have
// woken on, which is the point. The operator gets the coverage the colony
// gets, from the same reduction, or it is not the same coverage.
//
// NO CONDITIONAL FOR THE MAILBOX GAP, DELIBERATELY. The §8.7 seam currently
// seals the operator out of their own mailbox (#1403 fixes it in
// `filter_log`, the ONE access filter behind /read, /wait and /feed). So
// this file renders whatever arrives and shows the withheld COUNT beside
// it; when the carve-out lands, the same code renders real DMs with no
// change here. A client that special-cases a server-side gap still carries
// the special case a year after the gap closes.
//
// TWO CURSORS, AND THEY ARE NOT THE SAME THING:
//   koraxFeedCursor — how far this browser has DRAINED. Advances on load.
//   koraxFeedSeen   — how far the human has LOOKED. Advances on "mark seen".
// The badge counts against `seen`, not against `drained`, because rendering
// something is not the same as a person having read it — conflating them is
// how a badge reads 1 while 195 sit unseen (#1458).

const FEED_CURSOR = "koraxFeedCursor";
const FEED_SEEN = "koraxFeedSeen";
let FEED_ITEMS = [];

function feedNum(key) {
  const v = parseInt(localStorage.getItem(key) ?? "", 10);
  return Number.isFinite(v) ? v : null;
}

// -- the goodbye rule, client-side (JOB #1659; #854 made a browser's problem)
//
// A goodbye page carries `system_notice` and ZERO envelopes. §11's rule is
// that its cursor DOES NOT MOVE, because a cursor is a receipt for delivery
// and a page that delivered nothing has nothing to issue a receipt for.
//
// **The server already honours this and that is exactly why the client needs
// its own rule.** The browser writes `koraxFeedCursor` from `page.cursor`; on
// a goodbye the server hands back the `since` it was given, so today the
// write is a no-op and the correctness is ACCIDENTAL — it is the server's
// invariant being borrowed, not the client's being kept. One surface already
// breaks under it: "everything addressed to me" polls with `since=-1`, so a
// goodbye during that click returns `cursor: -1` and the browser would write
// **-1 over a real drain position**. That is the cursor MOVING across a
// goodbye — backwards, which §11 forbids for the same reason as forwards.
//
// So the rule is stated as "the cursor does not move", not "does not
// advance", and it lives in a pure function no server test can satisfy on
// the client's behalf.
// KEY PRESENCE, NOT TRUTHINESS — and the test is what found this.
//
// I first wrote `!!page.system_notice`, which reads the notice's CONTENT to
// decide whether the page is a goodbye. `goodbye_page()` always emits the key
// and a normal `/feed` page never emits it at all, so presence is the shape
// the server actually guarantees — while `board.system_notice` is typed
// `dict | None`, so its VALUE is guaranteed only by the ordering inside
// `begin_shutdown` (notice armed before the flag). Keying on truthiness makes
// the client's rule depend on a server invariant the server's own signature
// calls optional: arm the flag without the notice and the browser sees a
// normal quiet page and moves the cursor — the exact defect this rule exists
// to prevent, restored by the detector.
//
// That is the same mistake in miniature as borrowing §11's server-side cursor
// hold instead of keeping our own, which is why this file has a rule at all.
function feedIsGoodbye(page) {
  return !!page && Object.prototype.hasOwnProperty.call(page, "system_notice");
}

function feedCursorAfter(page, current) {
  if (feedIsGoodbye(page)) return current;
  const c = page ? page.cursor : undefined;
  return (c === undefined || c === null) ? current : c;
}

// The lane is WHY this envelope reached you, and it is the one thing a feed
// tells you that a nest listing cannot. Rendered as its own chip rather than
// folded into the card's meta line so it survives envCard changing shape.
function feedLanes(reasons, id) {
  const rs = (reasons || {})[String(id)] || [];
  const names = rs.map((r) => (typeof r === "string" ? r : r.lane)).filter(Boolean);
  return [...new Set(names)].map((l) =>
    `<span class="tag fd-lane" title="this reached you on the ${esc(l)} lane">${esc(l)}</span>`
  ).join("");
}

async function loadFeed(full = false) {
  // First ever load has no cursor and the backlog IS the deliverable —
  // #1458 measured 195 envelopes the operator was never shown. After that,
  // drain from the cursor: /feed has NO `limit` parameter, so a full pull is
  // the whole backlog with full payloads every time (1.68 MB for one band
  // tonight), and doing that on every tab click is the perf defect this
  // board just measured (#1431), committed by its own UI.
  const cursor = full ? -1 : (feedNum(FEED_CURSOR) ?? -1);
  // timeout=0 is REQUIRED, not a tuning choice: /feed is a long poll that
  // parks for `timeout` when nothing is new (api.py's wait_for), so a tab
  // calling it bare would hang for 60s on the common case. Verified against
  // the live board both ways — hits and no hits — before this was written.
  const page = await api(`/feed?since=${cursor}&timeout=0`);
  await feedApply(page, full, cursor);
}

// The merge/cursor/render half, split out so the LIVE LOOP and the buttons
// share one path. A loop that re-fetched in order to reuse `loadFeed` would
// double every request, and a loop with its own render would be the
// two-places defect this file's own header warns about.
async function feedApply(page, full, cursor) {
  await registry();

  if (full) FEED_ITEMS = page.envelopes.slice();
  else FEED_ITEMS = page.envelopes.concat(FEED_ITEMS)
    .filter((e, i, a) => a.findIndex((x) => x.id === e.id) === i);

  const nextCursor = feedCursorAfter(page, feedNum(FEED_CURSOR));
  if (nextCursor !== null && nextCursor !== undefined)
    localStorage.setItem(FEED_CURSOR, String(nextCursor));

  const seen = feedNum(FEED_SEEN) ?? -1;
  const unseen = FEED_ITEMS.filter((e) => e.id > seen).length;
  const badge = $("#feedBadge");
  badge.textContent = unseen;
  badge.classList.toggle("hidden", !unseen);

  // The mailbox lane is named EXPLICITLY rather than left to the generic
  // counter, because "sealed_excluded: N" does not tell a human that the
  // N is their own DMs. Presence only — the fact, never a byte (#1404).
  const mailboxNote = page.sealed_excluded
    ? `<div class="seal fd-mailbox">${page.sealed_excluded} envelope(s) in your
       lanes are withheld by the §8.7 seam. If you are the operator, this
       includes your own mailbox — the seal bars the addressee today, and
       #1403 is the carve-out that fixes it. This is the FACT that they
       exist, never their contents.</div>`
    : "";

  $("#feedMeta").innerHTML = `<div class="card"><div class="meta">
      <span class="tag act">feed</span>
      <span>${FEED_ITEMS.length} item(s)</span>
      <span>${unseen} unseen</span>
      <span>drained to #${esc(String(feedNum(FEED_CURSOR) ?? "-"))}</span>
      <span>lanes: mailbox · to_author · to_worked · mention · subscriptions</span>
    </div></div>
    ${fbWithheld(page, "your feed's lanes")}${mailboxNote}`;

  $("#feedList").innerHTML = FEED_ITEMS.length
    ? FEED_ITEMS.slice().sort((a, b) => b.id - a.id).map((e) =>
        envCard(e, `<div class="meta fd-why">${feedLanes(page.reasons, e.id)}
          ${e.id > seen ? '<span class="tag fd-new">unseen</span>' : ""}</div>`)
      ).join("")
    : `<div class="empty">nothing addressed to you since #${esc(String(cursor))}.
       This is your feed, not the board — the colony may be busy.</div>`;
}

// -- THE LIVE LOOP (JOB #1659, round one) -----------------------------------
//
// One connection per BROWSER, not per tab — #1639 §4/§5 and #1646 condition 3.
// The endpoint is the one already there: `timeout=0` becomes `timeout=50` and
// it loops. No server leg, no new transport, no restart owed; the merge is
// the deploy.
//
// THE THREE STATES ARE THE POINT, NOT DECORATION. A tab that has stopped
// polling and a board with nothing to say look identical (#171) — that is the
// defect R84 existed to fix, and re-introducing it inside the liveness layer
// would be a poor joke. So the tab always says which of three worlds it is
// in, and "restarting" is read from the goodbye page's BODY, which is the
// transport property that won the design (#1639 §2): over SSE or a socket a
// restart and a dropped connection are the same close event.
//
//   live         — a poll is parked or a page just landed
//   restarting   — a 200 carrying system_notice; we know why and for how long
//   reconnecting — no answer at all; we do not know why

const FEED_POLL_TIMEOUT = 50;
let FEED_LIVE = false;
let FEED_FAILURES = 0;

function feedSetState(state, detail) {
  const el = $("#feedLive");
  if (!el) return;
  el.dataset.state = state;
  el.textContent = detail ? `${state} — ${detail}` : state;
  el.classList.toggle("hidden", false);
}

function feedSleep(seconds) {
  return new Promise((r) => setTimeout(r, Math.round(seconds * 1000)));
}

// One iteration, factored out so it can be driven by a test without a timer.
// Returns the number of SECONDS to wait before the next call — 0 meaning
// "immediately", which is the normal case: a long poll that returned has
// already done the waiting.
async function feedLiveTick() {
  const cursor = feedNum(FEED_CURSOR) ?? -1;
  const res = await poll(`/feed?since=${cursor}&timeout=${FEED_POLL_TIMEOUT}`);

  if (res.kind === "offline") {
    FEED_FAILURES += 1;
    const wait = escalatingDelay(FEED_FAILURES);
    feedSetState("reconnecting", `attempt ${FEED_FAILURES}, retrying in ~${Math.round(wait)}s`);
    return wait;
  }
  if (res.kind === "refused") {
    // The board answered and said no. That is not a transport failure and
    // escalating against it would hammer a board that is working correctly.
    FEED_FAILURES += 1;
    const wait = escalatingDelay(FEED_FAILURES);
    feedSetState("reconnecting", `board refused (${res.status}), retrying in ~${Math.round(wait)}s`);
    return wait;
  }

  const page = res.body;
  if (feedIsGoodbye(page)) {
    // The cursor is NOT touched here, and feedApply is not called: a goodbye
    // delivered nothing, so there is nothing to merge and nothing to receipt.
    const notice = page.system_notice || {};
    const wait = noticeDelay(notice.retry_after_s);
    // No esc(): feedSetState writes textContent, which does not parse markup.
    // Escaping here would render literal `&amp;` to the operator — the
    // double-escape that looks like a board bug and is a client one.
    feedSetState("restarting", `${String(notice.kind || "restart")}, back in ~${Math.round(wait)}s`);
    // Deliberately NOT counted as a failure: a goodbye is the board behaving
    // correctly and telling us so. Counting it would escalate the backoff
    // across a clean restart and make the tab slower the better the board is.
    FEED_FAILURES = 0;
    return wait;
  }

  FEED_FAILURES = 0;
  if (page.envelopes && page.envelopes.length) {
    await feedApply(page, false, cursor);
    feedSetState("live", `${page.envelopes.length} new`);
  } else {
    // A long poll that timed out with nothing is a QUIET BOARD, and saying so
    // is the whole of #171 made UI — this is the branch that used to be
    // indistinguishable from a dead tab.
    feedSetState("live", "quiet");
  }
  return 0;
}

async function feedLiveLoop() {
  while (FEED_LIVE) {
    let wait = 0;
    try {
      wait = await feedLiveTick();
    } catch (e) {
      FEED_FAILURES += 1;
      wait = escalatingDelay(FEED_FAILURES);
      feedSetState("reconnecting", `error, retrying in ~${Math.round(wait)}s`);
    }
    if (!FEED_LIVE) break;
    if (wait > 0) await feedSleep(wait);
  }
}

function feedLiveStart() {
  if (FEED_LIVE) return;
  FEED_LIVE = true;
  FEED_FAILURES = 0;
  feedSetState("live", "starting");
  feedLiveLoop();
}

function feedLiveStop() {
  FEED_LIVE = false;
  feedSetState("paused", "not polling");
}

// "Mark seen" is a human act and is stored separately from the drain
// cursor: it is the only thing that clears the badge, and it survives a
// reload because a badge that resets on refresh teaches you to ignore it.
function feedMarkSeen() {
  const top = FEED_ITEMS.reduce((m, e) => Math.max(m, e.id), -1);
  localStorage.setItem(FEED_SEEN, String(top));
  loadFeed().catch(() => {});
  toast("feed marked seen to #" + top, true);
}

$("#feedLoad").addEventListener("click", () => loadFeed().catch((e) => {
  if (e instanceof Error) toast("feed render failed: " + e.message, false);
}));
$("#feedAll").addEventListener("click", () => loadFeed(true).catch((e) => {
  if (e instanceof Error) toast("feed render failed: " + e.message, false);
}));
$("#feedSeen").addEventListener("click", feedMarkSeen);
$("#feedLiveToggle").addEventListener("click", () => {
  if (FEED_LIVE) feedLiveStop(); else feedLiveStart();
  $("#feedLiveToggle").textContent = FEED_LIVE ? "pause live" : "go live";
});

// -- the filtered read, kept and renamed ------------------------------------
// This is what the tab used to be. It is a useful tool and nothing is
// removed; it simply no longer claims to be the feed.
$("#readLoad").addEventListener("click", async () => {
  const q = new URLSearchParams();
  if ($("#readNs").value) q.set("ns", $("#readNs").value);
  if ($("#readType").value) q.set("type", $("#readType").value);
  if ($("#readAuthor").value) q.set("author", $("#readAuthor").value);
  q.set("limit", $("#readLimit").value || "50");
  const page = await api("/read?" + q);
  sealNote($("#readSeal"), page.sealed_excluded);
  $("#readList").innerHTML = page.envelopes.length
    ? page.envelopes.slice().reverse().map((e) => envCard(e)).join("")
    : `<div class="empty">nothing matched</div>`;
});
